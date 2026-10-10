"""Registered Composite BF analysis through actual retained originals and worker."""

import json
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters import composite_attribution_deployment as deployment
from app.core.config import get_settings
from app.services.async_result_store import get_async_result_store
from app.services.compute_job_store import ComputeJobStatus, get_compute_job_store
from app.workers.compute_executor_worker import process_pending_jobs
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.benchmarks.postgres_runtime_helpers import RUNTIME_STORE_MODULES
from tests.composite_attribution_helpers import seal
from tests.composite_attribution_runtime_helpers import (
    ControlledAttributionReader,
    SignedSyntheticBFVerifier,
    capture_or17,
)
from tests.composite_principal_helpers import install_principal_deployment
from tests.composite_result_authority_helpers import AuthorityFixture

PATH = "/performance/composites/analytics"


@pytest.fixture
def attribution_database_url(tmp_path):
    return "sqlite:///" + (tmp_path / "registered-bf.db").as_posix()


@pytest.fixture
def attribution_runtime(monkeypatch, tmp_path, attribution_database_url):
    settings = get_settings()
    monkeypatch.setattr(settings, "LINEAGE_METADATA_DATABASE_URL", attribution_database_url)
    monkeypatch.setattr(settings, "LINEAGE_STORAGE_PATH", tmp_path / "lineage")
    assert apply_durable_schema(database_url=attribution_database_url).status == "passed"
    fixture = AuthorityFixture(attribution_database_url, monkeypatch)
    request, bundle, candidate = capture_or17(fixture, monkeypatch)
    source, authority = ControlledAttributionReader(bundle), SignedSyntheticBFVerifier(bundle)
    monkeypatch.setattr(deployment, "_deployment", deployment.CompositeAttributionDeployment(source, authority))
    grants, mint = install_principal_deployment(
        monkeypatch, app, tenant="tenant-a", portfolios=list(bundle.expected_portfolio_ids)
    )
    headers = {"Authorization": "Bearer " + mint(), "X-Tenant-Id": "tenant-a"}
    try:
        with TestClient(app) as client:
            yield client, request, source, authority, headers, fixture, grants, mint
    finally:
        fixture.close()
        for name in (*RUNTIME_STORE_MODULES, "app.adapters.composite_pooled_mwr_repository"):
            module = import_module(name)
            owned = module._store_cache.pop(attribution_database_url, None)
            if owned is not None:
                owned._engine.dispose()


def run_request(runtime, request=None):
    client, original, _, _, headers, *_ = runtime
    request = request or original
    submitted = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert submitted.status_code == 202, submitted.text
    path = submitted.json()["result_path"]
    assert client.get(path, headers=headers).status_code == 202
    assert process_pending_jobs(limit=1) == 1
    job = get_compute_job_store().get_job(request.calculation_id)
    assert job.job_status == ComputeJobStatus.COMPLETE, (job.error_type, job.error_message)
    result = client.get(path, headers=headers)
    assert result.status_code == 200, result.text
    return path, result.json()


def test_registered_or17_all_effect_cells_original_replay(attribution_runtime):
    client, request, source, _, headers, *_ = attribution_runtime
    path, result = run_request(attribution_runtime)
    outcome = result["outcome"]
    example = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/examples/composite_attribution_or17.json").read_text()
    )
    assert example["evidence_class"] == "CONTROLLED_SYNTHETIC_ONLY"
    documented_request = request.model_validate(example["request"])
    for field in (
        "metric_id",
        "method",
        "period_start",
        "period_end",
        "reporting_currency",
        "return_view",
        "precision_mode",
    ):
        assert getattr(documented_request, field) == getattr(request, field)
    expected = example["expected_outcome"]
    for key in ("units", "precision_mode", "active_return_convention"):
        assert outcome[key] == expected[key]
    for key in ("portfolio_return", "benchmark_return", "active_return", "allocation", "selection", "interaction"):
        assert outcome[key] == pytest.approx(expected[key], abs=1e-12)
    for row, expected_row in zip(outcome["groups"], expected["groups"], strict=True):
        assert row["group_id"] == expected_row["group_id"]
        for key in ("allocation", "selection", "interaction", "total"):
            assert row[key] == pytest.approx(expected_row[key], abs=1e-12)
    assert result["observation"]["approval"]["qualification"] == "SYNTHETIC_NON_CERTIFYING"
    job = get_compute_job_store().get_job(request.calculation_id)
    assert job.job_status == ComputeJobStatus.COMPLETE and job.attempt_count == 1
    assert get_async_result_store().get_result(request.calculation_id).response_payload == result
    reads = (source.metadata_reads, source.financial_reads)
    source.available = False
    assert client.post(PATH, json=request.model_dump(mode="json"), headers=headers).status_code == 202
    assert client.get(path, headers=headers).json() == result
    assert (source.metadata_reads, source.financial_reads) == reads


def test_registered_replay_does_not_recalculate_or_reapprove(attribution_runtime, monkeypatch):
    from app.services.composite_attribution import application

    client, request, source, verifier, headers, *_ = attribution_runtime
    path, original = run_request(attribution_runtime)
    source.available = False
    verifier.evidence.clear()

    def refuse_recalculation(*args, **kwargs):
        raise AssertionError("An original result must replay without a new BF calculation")

    monkeypatch.setattr(application, "calculate_attribution", refuse_recalculation)
    assert client.get(path, headers=headers).json() == original
    assert client.post(PATH, json=request.model_dump(mode="json"), headers=headers).status_code == 202
    assert client.get(path, headers=headers).json() == original


def test_registered_financial_purpose_is_rechecked_before_publication(attribution_runtime, monkeypatch):
    from app.services.composite_attribution import application

    client, request, _, verifier, headers, *_ = attribution_runtime
    calculate = application.calculate_attribution

    def calculate_then_revoke(*args, **kwargs):
        result = calculate(*args, **kwargs)
        verifier.evidence.clear()
        return result

    monkeypatch.setattr(application, "calculate_attribution", calculate_then_revoke)
    submitted = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert submitted.status_code == 202, submitted.text
    assert process_pending_jobs(limit=1) == 1
    result = client.get(submitted.json()["result_path"], headers=headers)
    assert result.status_code == 503, result.text
    assert result.json()["error_code"] == "ATTRIBUTION_PURPOSE_AUTHORITY_UNAVAILABLE"
    assert get_async_result_store().get_result(request.calculation_id) is None


def test_registered_strict_precision_refuses_before_source_or_job(attribution_runtime):
    client, request, source, _, headers, *_ = attribution_runtime
    request = request.model_copy(update={"precision_mode": "DECIMAL_STRICT"})
    response = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "ATTRIBUTION_PRECISION_UNSUPPORTED"
    assert (source.metadata_reads, source.financial_reads) == (0, 0)
    assert get_compute_job_store().get_job(request.calculation_id) is None


def test_registered_benchmark_classification_correction_preserves_both_originals(attribution_runtime):
    client, request, source, authority, headers, *_ = attribution_runtime
    path, original = run_request(attribution_runtime)
    bundle = source.bundles[request.source_manifest_id]
    groups = (bundle.groups[0].model_copy(update={"benchmark_return": 0.09}), bundle.groups[1])
    bundle, _ = seal(
        bundle.model_copy(
            update={
                "source_manifest_id": "corrected-2",
                "benchmark_revision": "benchmark-2",
                "classification_revision": "classification-2",
                "groups": groups,
            }
        )
    )
    source.bundles[bundle.source_manifest_id] = bundle
    authority.authorize(bundle)
    correction = request.model_copy(
        update={
            "calculation_id": uuid4(),
            "source_manifest_id": bundle.source_manifest_id,
            "correction_of_calculation_id": request.calculation_id,
        }
    )
    corrected_path, corrected = run_request(attribution_runtime, correction)
    assert corrected["outcome"]["benchmark_return"] == pytest.approx(0.06)
    assert corrected["input_manifest_digest"] != original["input_manifest_digest"]
    source.available = False
    assert client.get(path, headers=headers).json() == original
    assert client.get(corrected_path, headers=headers).json() == corrected


@pytest.mark.parametrize("denial", ["missing", "wrong-audience", "scope", "capability", "tenant"])
def test_registered_authorization_refuses_before_financial_reads(attribution_runtime, denial):
    client, request, source, _, headers, _, grants, mint = attribution_runtime
    headers = dict(headers)
    if denial == "missing":
        headers.pop("Authorization")
    elif denial == "wrong-audience":
        headers["Authorization"] = "Bearer " + mint(aud="wrong-audience")
    elif denial == "tenant":
        headers["Authorization"] = "Bearer " + mint(tenant="tenant-b")
    elif denial == "scope":
        grants.portfolios = frozenset()
    else:
        grants.capabilities = frozenset()
    response = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert response.status_code == (401 if denial in {"missing", "wrong-audience"} else 403), response.text
    assert source.financial_reads == 0
    assert get_compute_job_store().get_job(request.calculation_id) is None


def test_registered_unavailable_source_is_typed_and_does_not_submit(attribution_runtime):
    client, request, source, _, headers, *_ = attribution_runtime
    source.available = False
    response = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert response.status_code == 503, response.text
    assert response.json()["error_code"] == "SOURCE_AUTHORITY_UNAVAILABLE"
    assert source.financial_reads == 0
    assert get_compute_job_store().get_job(request.calculation_id) is None


@pytest.mark.parametrize("evidence", ["absent", "twr-purpose"])
def test_registered_unavailable_or_wrong_financial_purpose_cannot_publish(attribution_runtime, evidence):
    client, request, source, verifier, headers, *_ = attribution_runtime
    bundle = source.bundles[request.source_manifest_id]
    if evidence == "absent":
        verifier.evidence.clear()
    else:
        verifier.authorize(bundle, purpose="COMPOSITE_FINANCIAL_RESULT_ACTION")
    response = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert response.status_code == 202, response.text
    assert process_pending_jobs(limit=1) == 1
    result = client.get(response.json()["result_path"], headers=headers)
    assert result.status_code in {409, 503}, result.text
    assert result.json()["error_code"] == (
        "ATTRIBUTION_PURPOSE_AUTHORITY_UNAVAILABLE" if evidence == "absent" else "ATTRIBUTION_PURPOSE_APPROVAL_CONFLICT"
    )
    assert get_async_result_store().get_result(request.calculation_id) is None


@pytest.mark.parametrize("stage", ["admission", "binding", "publication"])
def test_registered_current_selection_rechecked_at_each_boundary(attribution_runtime, monkeypatch, stage):
    from app.services.composite_attribution import application

    client, request, source, _, headers, fixture, *_ = attribution_runtime
    original = fixture.store.get_result_candidate(
        candidate_id=request.candidate_id,
        tenant_id="tenant-a",
        result_store=fixture.results,
        principal=fixture.principal("maker"),
    )
    decision = fixture.decide(fixture.proposal(original))
    selection = decision.selections[0]
    request = request.model_copy(
        update={"official_scope_id": selection.scope.scope_id, "official_revision": selection.revision}
    )
    withdrawn = False

    def withdraw():
        nonlocal withdrawn
        if not withdrawn:
            fixture.decide(fixture.proposal(original, action="WITHDRAW_CURRENT_USE", revision=selection.revision))
            withdrawn = True

    if stage == "admission":
        withdraw()
    elif stage == "binding":
        read = source.read_pinned

        def read_then_withdraw(*args, **kwargs):
            bundle = read(*args, **kwargs)
            withdraw()
            return bundle

        monkeypatch.setattr(source, "read_pinned", read_then_withdraw)
    else:
        calculate = application.calculate_attribution

        def calculate_then_withdraw(*args, **kwargs):
            result = calculate(*args, **kwargs)
            withdraw()
            return result

        monkeypatch.setattr(application, "calculate_attribution", calculate_then_withdraw)
    response = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    if stage == "admission":
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == "OFFICIAL_SELECTION_STALE"
        assert source.financial_reads == 0
        assert get_compute_job_store().get_job(request.calculation_id) is None
    else:
        assert response.status_code == 202, response.text
        assert process_pending_jobs(limit=1) == 1
        result = client.get(response.json()["result_path"], headers=headers)
        assert result.status_code == 409, result.text
        assert result.json()["error_code"] == "OFFICIAL_SELECTION_STALE"
        assert get_async_result_store().get_result(request.calculation_id) is None


@pytest.mark.parametrize("target", ["input", "result"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_registered_original_input_and_output_are_database_immutable(attribution_runtime, target, operation):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    _, request, _, _, _, fixture, *_ = attribution_runtime
    run_request(attribution_runtime)
    table = "composite_attribution_inputs" if target == "input" else "analytics_async_result"
    sql = (
        f"DELETE FROM {table} WHERE calculation_id=:id"
        if operation == "DELETE"
        else f"UPDATE {table} SET tenant_id='changed' WHERE calculation_id=:id"
    )
    with pytest.raises(IntegrityError):
        with fixture.store._engine.begin() as connection:
            connection.execute(text(sql), {"id": str(request.calculation_id)})
    fixture.store.verify_schema()


def test_registered_original_replays_in_fresh_process_without_source(
    attribution_runtime, attribution_database_url, tmp_path
):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    _, request, _, _, _, fixture, *_ = attribution_runtime
    _, response = run_request(attribution_runtime)
    authority_packet = tmp_path / "retained-source-authorities.json"
    authority_packet.write_text(json.dumps(fixture.source_packets, sort_keys=True), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.composite_attribution_replay_probe",
            str(request.calculation_id),
            str(authority_packet),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "LOTUS_BF_REPLAY_DATABASE_URL": attribution_database_url},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    retained = json.loads(completed.stdout)
    assert retained["response"] == response
    assert retained["request"] == request.model_dump(mode="json")
    assert retained["source_deployment"] == "UNAVAILABLE"


def test_registered_missing_input_guard_refuses_without_repair(attribution_runtime):
    from sqlalchemy import text

    from app.adapters.durable_schema.errors import DurableSchemaMigrationRequiredError

    _, _, _, _, _, fixture, *_ = attribution_runtime
    run_request(attribution_runtime)
    with fixture.store._engine.begin() as connection:
        statement = "DROP TRIGGER composite_attribution_inputs_update" + (
            " ON composite_attribution_inputs" if connection.dialect.name == "postgresql" else ""
        )
        connection.execute(text(statement))
    with pytest.raises(DurableSchemaMigrationRequiredError):
        fixture.store.verify_schema()
    with fixture.store._engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            found = connection.execute(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='composite_attribution_inputs_update'"
                )
            ).scalar_one()
        else:
            found = connection.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname='composite_attribution_inputs_update' AND tgrelid='composite_attribution_inputs'::regclass"
                )
            ).scalar_one()
    assert found == 0


def test_registered_corrected_member_original_identity_never_aliases(attribution_runtime, monkeypatch):
    client, request, source, verifier, headers, fixture, *_ = attribution_runtime
    original_path, original = run_request(attribution_runtime)
    correction, bundle, _ = capture_or17(fixture, monkeypatch, corrected=True)
    bundle, _ = seal(bundle.model_copy(update={"source_manifest_id": "corrected-member-vector-2"}))
    correction = correction.model_copy(
        update={"source_manifest_id": bundle.source_manifest_id, "correction_of_calculation_id": request.calculation_id}
    )
    source.bundles[bundle.source_manifest_id] = bundle
    verifier.authorize(bundle)
    corrected_path, corrected = run_request(attribution_runtime, correction)
    assert corrected["outcome"] == original["outcome"]
    assert corrected["input_manifest_digest"] != original["input_manifest_digest"]
    assert (
        corrected["observation"]["source_bundle"]["candidate_id"]
        != original["observation"]["source_bundle"]["candidate_id"]
    )
    assert (
        corrected["observation"]["source_bundle"]["vector_digest"]
        != original["observation"]["source_bundle"]["vector_digest"]
    )
    source.available = False
    assert client.get(original_path, headers=headers).json() == original
    assert client.get(corrected_path, headers=headers).json() == corrected


def test_registered_changed_source_reference_cannot_reuse_identity(attribution_runtime):
    client, request, source, _, headers, *_ = attribution_runtime
    path, original = run_request(attribution_runtime)
    changed = request.model_copy(update={"source_manifest_id": "changed-source-revision"})
    reads = (source.metadata_reads, source.financial_reads)
    response = client.post(PATH, json=changed.model_dump(mode="json"), headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "INPUT_CUSTODY_CONFLICT"
    assert (source.metadata_reads, source.financial_reads) == reads
    assert client.get(path, headers=headers).json() == original


def test_registered_two_populated_tenants_keep_originals_separate(attribution_runtime, monkeypatch):
    client, _, source, verifier, headers_a, fixture, grants, mint = attribution_runtime
    path_a, original_a = run_request(attribution_runtime)
    request_b, bundle_b, _ = capture_or17(fixture, monkeypatch, tenant="tenant-b")
    bundle_b, _ = seal(bundle_b.model_copy(update={"source_manifest_id": "tenant-b-manifest"}))
    request_b = request_b.model_copy(update={"source_manifest_id": bundle_b.source_manifest_id})
    source.bundles[bundle_b.source_manifest_id] = bundle_b
    verifier.authorize(bundle_b)
    grants.tenant = "tenant-b"
    headers_b = {"Authorization": "Bearer " + mint(tenant="tenant-b"), "X-Tenant-Id": "tenant-b"}
    runtime_b = (client, request_b, source, verifier, headers_b, fixture, grants, mint)
    path_b, original_b = run_request(runtime_b)
    assert original_a["composite_id"] == original_b["composite_id"] == "COMPOSITE"
    assert original_a["outcome"] == original_b["outcome"]
    assert original_a["input_manifest_digest"] != original_b["input_manifest_digest"]
    assert original_a["observation"]["source_bundle"]["tenant_id"] == "tenant-a"
    assert original_b["observation"]["source_bundle"]["tenant_id"] == "tenant-b"
    assert client.get(path_a, headers=headers_b).status_code == 404
    assert client.get(path_b, headers=headers_b).json() == original_b
    grants.tenant = "tenant-a"
    assert client.get(path_b, headers=headers_a).status_code == 404
    assert client.get(path_a, headers=headers_a).json() == original_a


def test_registered_withdrawal_preserves_published_original_replay(attribution_runtime):
    client, request, source, verifier, headers, fixture, *_ = attribution_runtime
    candidate = fixture.store.get_result_candidate(
        candidate_id=request.candidate_id,
        tenant_id="tenant-a",
        result_store=fixture.results,
        principal=fixture.principal("maker"),
    )
    selection = fixture.decide(fixture.proposal(candidate)).selections[0]
    request = request.model_copy(
        update={"official_scope_id": selection.scope.scope_id, "official_revision": selection.revision}
    )
    path, original = run_request(attribution_runtime, request)
    fixture.decide(fixture.proposal(candidate, action="WITHDRAW_CURRENT_USE", revision=selection.revision))
    source.available = False
    verifier.evidence.clear()
    assert client.get(path, headers=headers).json() == original
    assert client.post(PATH, json=request.model_dump(mode="json"), headers=headers).status_code == 202
    assert client.get(path, headers=headers).json() == original


@pytest.mark.parametrize(
    "change", [{"worker_id": "stale-worker"}, {"tenant_id": "foreign"}, {"expected_attempt_count": 2}]
)
def test_registered_input_binding_refuses_stale_or_foreign_lease(attribution_runtime, change):
    from app.adapters.composite_attribution_repository import bind_attribution_input
    from app.services.compute_job_store import ComputeJobLeaseOwnershipError

    jobs, request, observation, principal, claim = _binding_case(attribution_runtime)
    with pytest.raises(ComputeJobLeaseOwnershipError):
        jobs.run_with_active_lease_transaction(
            **{**claim, **change},
            operation=lambda connection: bind_attribution_input(connection, request, observation, principal=principal),
        )
    assert _input_count(attribution_runtime) == 0


def test_registered_input_binding_rolls_back_interrupted_transaction(attribution_runtime):
    from app.adapters.composite_attribution_repository import bind_attribution_input

    jobs, request, observation, principal, claim = _binding_case(attribution_runtime)

    def interrupted(connection):
        bind_attribution_input(connection, request, observation, principal=principal)
        raise RuntimeError("interrupted before custody commit")

    with pytest.raises(RuntimeError, match="interrupted before custody commit"):
        jobs.run_with_active_lease_transaction(**claim, operation=interrupted)
    assert _input_count(attribution_runtime) == 0
    snapshot = jobs.run_with_active_lease_transaction(
        **claim,
        operation=lambda connection: bind_attribution_input(connection, request, observation, principal=principal),
    )
    assert snapshot.observation == observation
    assert _input_count(attribution_runtime) == 1


def _binding_case(runtime):
    from app.adapters.composite_attribution_dependencies import retained_dependencies
    from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION
    from app.services.composite_attribution.admission import admit_attribution
    from app.services.composite_attribution.application import job_principal

    client, request, source, verifier, headers, fixture, *_ = runtime
    response = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
    assert response.status_code == 202, response.text
    jobs = get_compute_job_store()
    jobs.lease_pending_jobs(worker_id="bf-queue", limit=1, lease_seconds=60)
    jobs.mark_running_acquired(
        request.calculation_id, current_worker_id="bf-queue", acquisition_worker_id="bf-owner", lease_seconds=60
    )
    principal = job_principal(jobs.get_job(request.calculation_id))
    with fixture.store._session() as session:
        original, vector = retained_dependencies(session.connection(), request, principal)
    bundle = source.read_pinned(request, tenant_id=principal.tenant_id)
    observation = admit_attribution(
        request,
        bundle,
        verifier.verify(request, bundle),
        tenant_id=principal.tenant_id,
        original=original,
        vector=vector,
    )
    claim = dict(
        calculation_id=request.calculation_id,
        tenant_id=principal.tenant_id,
        analytics_type=ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION,
        worker_id="bf-owner",
        expected_attempt_count=1,
    )
    return jobs, request, observation, principal, claim


def _input_count(runtime):
    from sqlalchemy import text

    fixture = runtime[5]
    with fixture.store._engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM composite_attribution_inputs")).scalar_one()


def test_registered_repeated_schema_apply_preserves_both_original_owners(attribution_runtime, attribution_database_url):
    client, _, _, _, headers, *_ = attribution_runtime
    path, original = run_request(attribution_runtime)
    result = apply_durable_schema(database_url=attribution_database_url)
    assert result.status == "passed"
    assert "composite_attribution_inputs" in result.owned_tables_present
    assert _input_count(attribution_runtime) == 1
    assert client.get(path, headers=headers).json() == original


def test_registered_original_survives_ordinary_retention_and_generic_writers(attribution_runtime):
    from datetime import UTC, datetime, timedelta

    from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION
    from app.services.async_result_store import AsyncResultCaptureAdmissionRequiredError

    client, request, _, _, headers, *_ = attribution_runtime
    path, original = run_request(attribution_runtime)
    results = get_async_result_store()
    ordinary = uuid4()
    results.record_success(
        calculation_id=ordinary, analytics_type="TWR", tenant_id="tenant-a", response_payload={"ordinary": True}
    )
    cutoff = datetime.now(UTC) + timedelta(days=1)
    assert str(request.calculation_id) not in results.list_result_ids_older_than(cutoff)
    assert str(ordinary) in results.list_result_ids_older_than(cutoff)
    assert results.prune_results_older_than(cutoff) == 1
    for identity in (request.calculation_id, uuid4()):
        with pytest.raises(AsyncResultCaptureAdmissionRequiredError):
            results.record_success(
                calculation_id=identity,
                analytics_type=ANALYTICS_WORKFLOW_COMPOSITE_ATTRIBUTION,
                tenant_id="tenant-a",
                response_payload={"forged": True},
            )
    assert client.get(path, headers=headers).json() == original


def test_registered_bf_audit_names_metric_and_verified_actor(attribution_runtime, caplog):
    client, request, _, _, headers, *_ = attribution_runtime
    headers = {**headers, "X-Actor-Id": "forged-actor", "X-Role": "admin", "X-Capabilities": "*"}
    with caplog.at_level("INFO", logger="enterprise_readiness"):
        submitted = client.post(PATH, json=request.model_dump(mode="json"), headers=headers)
        assert submitted.status_code == 202, submitted.text
        assert process_pending_jobs(limit=1) == 1
        read = client.get(submitted.json()["result_path"], headers=headers)
        assert read.status_code == 200, read.text
    audits = [
        record.audit
        for record in caplog.records
        if hasattr(record, "audit")
        and record.audit["action"] in {"POST " + PATH, "GET " + submitted.json()["result_path"]}
    ]
    assert len(audits) >= 2
    assert {audit["metadata"]["governed_surface"] for audit in audits} == {"composite_attribution"}
    assert {(audit["actor_id"], audit["tenant_id"], audit["role"]) for audit in audits} == {
        ("verified-test-maker", "tenant-a", "user")
    }


@pytest.mark.parametrize("metric", [[], {"unexpected": "metric"}])
def test_registered_malformed_metric_refuses_without_financial_dispatch(attribution_runtime, metric):
    client, request, source, _, headers, *_ = attribution_runtime
    payload = request.model_dump(mode="json")
    payload["metric_id"] = metric
    response = client.post(PATH, json=payload, headers=headers)
    assert response.status_code == 422, response.text
    assert (source.metadata_reads, source.financial_reads) == (0, 0)
    assert get_compute_job_store().get_job(request.calculation_id) is None
