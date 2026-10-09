"""Registered pooled API/worker controls using explicitly synthetic trusted ports."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters import composite_pooled_mwr_source as source_adapter
from app.adapters.composite_pooled_mwr_repository import get_composite_pooled_mwr_input_store
from app.core.config import get_settings
from app.models.composite_authority import authority_digest
from app.models.composite_pooled_mwr import PooledSourceBundle
from app.ports.composite_pooled_mwr import PooledSourceAdmissionError
from app.services.async_result_store import get_async_result_store
from app.services.compute_job_store import ComputeJobStatus, get_compute_job_store
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks.postgres_runtime_helpers import RUNTIME_STORE_MODULES
from tests.composite_principal_helpers import install_principal_deployment
from tests.unit.services.test_composite_pooled_mwr_admission import controlled_request, controlled_source_payload

PATH = "/performance/composites/analytics"


class ControlledPooledReader:
    """Synthetic supplier fixture; no actual Core/Manage qualification is claimed."""

    def __init__(self):
        self.payloads = {"controlled-original-v1": controlled_source_payload()}
        self.metadata_reads = 0
        self.money_reads = 0
        self.available = True

    def _payload(self, request, tenant_id):
        if not self.available:
            raise PooledSourceAdmissionError(
                "SOURCE_AUTHORITY_UNAVAILABLE", "Controlled source intentionally unavailable."
            )
        if tenant_id != "controlled-tenant" or request.source_manifest_id not in self.payloads:
            raise PooledSourceAdmissionError("SOURCE_CUT_UNAVAILABLE", "Controlled cut is absent in this tenant.")
        return self.payloads[request.source_manifest_id]

    def read_population_scope(self, request, *, tenant_id):
        self.metadata_reads += 1
        return tuple(self._payload(request, tenant_id)["expected_portfolio_ids"])

    def read_pinned(self, request, *, tenant_id):
        self.money_reads += 1
        return PooledSourceBundle.model_validate(deepcopy(self._payload(request, tenant_id)))

    def add_correction(self):
        payload = deepcopy(self.payloads["controlled-original-v1"])
        payload["source_manifest_id"] = "controlled-correction-v2"
        payload["valuations"][1]["amount"] = "70"
        self.payloads[payload["source_manifest_id"]] = payload
        self.rebind(payload)

    @staticmethod
    def rebind(payload):
        payload["raw_source_bodies"]["money"] = {
            name: deepcopy(payload[name]) for name in ("valuations", "flows", "flow_coverage")
        }
        for pin in payload["source_pins"]:
            pin["payload_digest"] = authority_digest(payload["raw_source_bodies"][pin["pin_id"]])


@pytest.fixture
def pooled_api_database_url(tmp_path):
    return f"sqlite:///{tmp_path / 'registered-pooled.db'}"


@pytest.fixture
def pooled_api_runtime(monkeypatch, tmp_path, pooled_api_database_url):
    settings = get_settings()
    monkeypatch.setattr(settings, "LINEAGE_METADATA_DATABASE_URL", pooled_api_database_url)
    monkeypatch.setattr(settings, "LINEAGE_STORAGE_PATH", tmp_path / "lineage")
    assert apply_durable_schema(database_url=pooled_api_database_url).status == "passed"
    reader = ControlledPooledReader()
    monkeypatch.setattr(source_adapter, "_deployment", source_adapter.PooledMonetarySourceDeployment(reader))
    authority, mint = install_principal_deployment(
        monkeypatch, app, tenant="controlled-tenant", portfolios=["member-a", "member-b"]
    )
    headers = {"X-Tenant-Id": "controlled-tenant", "Authorization": "Bearer " + mint()}
    try:
        with TestClient(app) as client:
            yield client, reader, authority, mint, headers
    finally:
        for name in (*RUNTIME_STORE_MODULES, "app.adapters.composite_pooled_mwr_repository"):
            module = import_module(name)
            owned = module._store_cache.pop(pooled_api_database_url, None)
            if owned is not None:
                owned._engine.dispose()


def _run_request(runtime, request=None):
    client, _, _, _, headers = runtime
    request = request or controlled_request()
    submitted = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert submitted.status_code == 202, submitted.text
    pending = client.get(submitted.json()["result_path"], headers=headers)
    assert pending.status_code == 202, pending.text
    assert process_pending_jobs(limit=1) == 1
    result = client.get(submitted.json()["result_path"], headers=headers)
    assert result.status_code == 200, result.text
    return request, submitted.json(), result.json()


def test_registered_pooled_original_worker_and_source_independent_replay(pooled_api_runtime):
    client, reader, _, _, headers = pooled_api_runtime
    request, accepted, result = _run_request(pooled_api_runtime)
    assert result["outcome"]["availability"] == "AVAILABLE"
    assert abs(Decimal(result["outcome"]["return_value"]) - Decimal("0.10")) < Decimal("1e-9")
    assert result["outcome"]["units"] == "DECIMAL_FRACTION"
    assert result["outcome"]["root_precision"] == "FLOAT64"
    assert result["observation"]["source_bundle"]["qualification"] == "CONTROLLED_SYNTHETIC_ONLY"
    assert result["observation"]["source_bundle"]["institutional_attestation"] == "NOT_ATTESTED"
    job = get_compute_job_store().get_job(request.calculation_id)
    assert job.job_status == ComputeJobStatus.COMPLETE and job.attempt_count == 1
    assert get_async_result_store().get_result(request.calculation_id).response_payload == result
    assert reader.money_reads == 1
    reads = (reader.metadata_reads, reader.money_reads)
    reader.available = False
    retry = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert retry.status_code == 202, retry.text
    assert client.get(accepted["result_path"], headers=headers).json() == result
    assert (reader.metadata_reads, reader.money_reads) == reads


def test_registered_pooled_correction_preserves_both_originals(pooled_api_runtime):
    client, reader, _, _, headers = pooled_api_runtime
    original, accepted, result = _run_request(pooled_api_runtime)
    reader.add_correction()
    correction = original.model_copy(
        update={
            "calculation_id": uuid4(),
            "source_manifest_id": "controlled-correction-v2",
            "correction_of_calculation_id": original.calculation_id,
        }
    )
    _, corrected_accepted, corrected = _run_request(pooled_api_runtime, correction)
    assert abs(Decimal(corrected["outcome"]["return_value"]) - Decimal("0.20")) < Decimal("1e-9")
    assert corrected["input_manifest_digest"] != result["input_manifest_digest"]
    assert corrected["correction_of_calculation_id"] == str(original.calculation_id)
    reader.available = False
    assert client.get(accepted["result_path"], headers=headers).json() == result
    assert client.get(corrected_accepted["result_path"], headers=headers).json() == corrected


@pytest.mark.parametrize("denial", ["missing", "wrong_audience", "capability", "scope", "tenant"])
def test_registered_pooled_authority_refuses_before_financial_source_read(pooled_api_runtime, denial):
    client, reader, authority, mint, headers = pooled_api_runtime
    headers = {
        **headers,
        "X-Actor-Id": "forged-maker",
        "X-Role": "admin",
        "X-Capabilities": "operations.runtime.manage,operations.runtime.read",
    }
    if denial == "missing":
        headers.pop("Authorization")
    elif denial == "wrong_audience":
        headers["Authorization"] = "Bearer " + mint(aud="wrong")
    elif denial == "capability":
        authority.capabilities = frozenset()
    elif denial == "scope":
        authority.portfolios = frozenset({"member-a"})
    else:
        headers["X-Tenant-Id"] = "foreign"
    response = client.post(PATH, json=controlled_request().model_dump(mode="json"), headers=headers)
    assert response.status_code == (401 if denial in ("missing", "wrong_audience") else 403), response.text
    assert reader.money_reads == 0


def test_registered_pooled_unconfigured_source_is_typed_unavailable(pooled_api_runtime, monkeypatch):
    client, _, _, _, headers = pooled_api_runtime
    monkeypatch.setattr(source_adapter, "_deployment", source_adapter.PooledMonetarySourceDeployment())
    response = client.post(PATH, json=controlled_request().model_dump(mode="json"), headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "SOURCE_AUTHORITY_UNAVAILABLE"


def test_registered_pooled_missing_terminal_records_operational_failure_only(pooled_api_runtime):
    client, reader, _, _, headers = pooled_api_runtime
    payload = reader.payloads["controlled-original-v1"]
    payload["valuations"] = [row for row in payload["valuations"] if row["source_row_id"] != "member-b-TERMINAL"]
    reader.rebind(payload)
    request = controlled_request()
    accepted = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert accepted.status_code == 202, accepted.text
    assert process_pending_jobs(limit=1) == 1
    job = get_compute_job_store().get_job(request.calculation_id)
    assert job.job_status == ComputeJobStatus.FAILED
    assert get_async_result_store().get_result(request.calculation_id) is None
    assert get_composite_pooled_mwr_input_store().get(request.calculation_id, tenant_id="controlled-tenant") is None
    refused = client.get(accepted.json()["result_path"], headers=headers)
    assert refused.status_code == 409, refused.text


def test_registered_pooled_retry_reuses_snapshot_after_transient_solver_failure(pooled_api_runtime, monkeypatch):
    from app.services.composite_pooled_mwr import application

    client, reader, _, _, headers = pooled_api_runtime
    original_calculator = application.calculate_pooled_xirr
    calls = []

    def interrupted(request, observation):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("controlled transient failure after snapshot custody")
        return original_calculator(request, observation)

    monkeypatch.setattr(application, "calculate_pooled_xirr", interrupted)
    request = controlled_request()
    accepted = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert accepted.status_code == 202, accepted.text
    assert process_pending_jobs(limit=1) == 1
    assert get_async_result_store().get_result(request.calculation_id) is None
    assert get_composite_pooled_mwr_input_store().get(request.calculation_id, tenant_id="controlled-tenant") is not None
    reader.available = False
    assert process_pending_jobs(limit=1) == 1
    result = client.get(accepted.json()["result_path"], headers=headers)
    assert result.status_code == 200, result.text
    assert get_compute_job_store().get_job(request.calculation_id).attempt_count == 2
    assert reader.money_reads == 1 and len(calls) == 2


@pytest.mark.parametrize("forged_tenant", [False, True])
def test_registered_pooled_audit_uses_verified_principal_and_ignores_header_grants(
    pooled_api_runtime, monkeypatch, caplog, forged_tenant
):
    client, reader, _, _, headers = pooled_api_runtime
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    headers = {**headers, "X-Actor-Id": "forged-maker", "X-Role": "admin", "X-Capabilities": "*"}
    if forged_tenant:
        headers["X-Tenant-Id"] = "forged-tenant"
    with caplog.at_level("INFO", logger="enterprise_readiness"):
        response = client.post(PATH, json=controlled_request().model_dump(mode="json"), headers=headers)
    assert response.status_code == (403 if forged_tenant else 202), response.text
    audits = [
        record.audit
        for record in caplog.records
        if hasattr(record, "audit") and record.audit["action"] == "POST " + PATH
    ]
    assert audits
    assert {(audit["actor_id"], audit["tenant_id"], audit["role"]) for audit in audits} == {
        ("verified-test-maker", "controlled-tenant", "user")
    }
    assert audits[-1]["metadata"]["governed_surface"] == "composite_pooled_mwr"
    assert reader.money_reads == 0


def test_registered_pooled_duplicate_authorization_refuses_before_source(pooled_api_runtime):
    client, reader, _, _, headers = pooled_api_runtime
    repeated = [*headers.items(), ("Authorization", headers["Authorization"])]
    response = client.post(PATH, json=controlled_request().model_dump(mode="json"), headers=repeated)
    assert response.status_code == 401, response.text
    assert reader.metadata_reads == 0 and reader.money_reads == 0


@pytest.mark.parametrize("length", [None, "1", "99999"])
def test_registered_pooled_streamed_size_limit_preserves_security_headers(pooled_api_runtime, monkeypatch, length):
    client, reader, _, _, headers = pooled_api_runtime
    monkeypatch.setenv("ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES", "64")
    headers = {**headers, "Content-Type": "application/json"}
    if length is not None:
        headers["Content-Length"] = length
    body = b'{"metric_id":"POOLED_MONEY_WEIGHTED_RETURN"}' + b" " * 50
    response = client.post(PATH, content=iter([body[:50], b"", body[50:]]), headers=headers)
    assert response.status_code == 413, response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert reader.metadata_reads == 0 and reader.money_reads == 0


@pytest.mark.parametrize("origin,expected", [("http://localhost:3000", 200), ("https://untrusted.test", 400)])
def test_registered_pooled_cors_preflight_precedes_principal(pooled_api_runtime, origin, expected):
    client, reader, _, _, _ = pooled_api_runtime
    response = client.options(
        PATH,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert response.status_code == expected, response.text
    assert reader.metadata_reads == 0 and reader.money_reads == 0


@pytest.mark.parametrize("members", [None, [], [""], ["member-a", "member-a"], ["member-a", 1]])
def test_registered_pooled_invalid_population_metadata_refuses_before_money(pooled_api_runtime, monkeypatch, members):
    client, reader, _, _, headers = pooled_api_runtime
    monkeypatch.setattr(reader, "read_population_scope", lambda *args, **kwargs: members)
    response = client.post(PATH, json=controlled_request().model_dump(mode="json"), headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "MISSING_POPULATION_COVERAGE"
    assert reader.money_reads == 0


@pytest.mark.parametrize("change", [{"composite_id": "other"}, {"input_manifest_digest": "other"}])
def test_pooled_published_contract_refuses_unbound_result_identity(pooled_api_runtime, change):
    from pydantic import ValidationError

    from app.models.composite_pooled_mwr import CompositePooledMWRResponse

    _, _, result = _run_request(pooled_api_runtime)
    assert CompositePooledMWRResponse.model_validate(result).input_manifest_digest == result["input_manifest_digest"]
    with pytest.raises(ValidationError, match="retained monetary observation"):
        CompositePooledMWRResponse.model_validate({**result, **change})


def test_registered_pooled_dated_flow_matches_independent_quadratic_oracle(pooled_api_runtime):
    _, reader, _, _, _ = pooled_api_runtime
    payload = deepcopy(reader.payloads["controlled-original-v1"])
    payload["source_manifest_id"] = "controlled-dated-oracle-v1"
    payload["period_end"] = "2027-01-01"
    for row in payload["membership"]:
        row["effective_to"] = "2027-01-01"
    for row in payload["valuations"]:
        row["amount"] = "100" if row["role"] == "OPENING" else "121" if row["portfolio_id"] == "member-a" else "220"
        if row["role"] == "TERMINAL":
            row["economic_date"] = "2027-01-01"
    payload["flows"] = [
        {
            "portfolio_id": "member-b",
            "economic_date": "2026-01-01",
            "source_date": "2026-01-01",
            "amount": "100",
            "currency": "USD",
            "timing": "BOD",
            "classification": "EXTERNAL",
            "flow_scope": "PORTFOLIO",
            "source_pin_id": "money",
            "identity_namespace": "controlled-owner-events",
            "identity_scope": "PORTFOLIO",
            "event_id": "member-b-subscription",
            "revision": "v1",
            "lifecycle_status": "ACTIVE",
        }
    ]
    for row in payload["flow_coverage"]:
        row["coverage_to"] = "2027-01-01"
        if row["portfolio_id"] == "member-b":
            row["active_event_ids"] = ["member-b-subscription"]
            row["explicitly_empty"] = False
    payload["raw_source_bodies"]["population"]["membership"] = deepcopy(payload["membership"])
    for pin in payload["source_pins"]:
        pin["coverage_to"] = "2027-01-01"
        pin["revision"] += "-dated-oracle"
        pin["source_cut_id"] += "-dated-oracle"
    reader.rebind(payload)
    reader.payloads[payload["source_manifest_id"]] = payload
    request = controlled_request().model_copy(
        update={"period_end": date(2027, 1, 1), "source_manifest_id": payload["source_manifest_id"]}
    )
    _, _, result = _run_request(pooled_api_runtime, request)
    observed = Decimal(result["outcome"]["return_value"])
    # Solve 200*x^2 + 100*x - 341 = 0 with x = 1+r; the independent
    # reviewed Decimal oracle is distinct from either member-return average.
    assert abs(observed - Decimal("0.0794735800308331061377877548969028459657461134194723829")) < Decimal("1e-9")
    assert abs(observed - Decimal("0.0826237921249263937432107840559466824042164258640340035")) > Decimal("0.003")
    flows = result["observation"]["investor_cash_flows"]
    assert [flow["economic_date"] for flow in flows] == ["2025-01-01", "2026-01-01", "2027-01-01"]
    assert [Decimal(flow["amount"]) for flow in flows] == [Decimal("-200"), Decimal("-100"), Decimal("341")]
