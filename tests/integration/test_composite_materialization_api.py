from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import composite_materialization_store
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.services.compute_job_store import ComputeJobStore, compute_job_store
from app.services.execution_registry import ExecutionRegistry, ExecutionStatus, execution_registry
from app.workers.compute_executor_worker import process_pending_jobs
from app.workers.lineage_worker import process_pending_jobs as process_lineage
from core.errors import APINotFoundError
from main import app
from tests.composite_materialization_helpers import command_for, source_products


@pytest.fixture(autouse=True)
def isolated_materialization_api_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(
        get_settings(), "LINEAGE_METADATA_DATABASE_URL", "sqlite:///" + (tmp_path / "metadata.db").as_posix()
    )


STANDARD_ASSETS = {"A": ("100", "110"), "B": ("200", "210"), "C": ("300", "294")}
LARGE_EXACT_ASSETS = {
    "A": ("9007199254740993.001", "9907919180215092.3011"),
    "B": ("200.002", "210.0021"),
    "C": ("300.003", "294.00294"),
}


def install_source_wire_controls(monkeypatch, products, *, figures=None, flows=None):
    """Controlled upstream wires, not live Manage/Core acceptance."""
    definition, membership, attestation = products
    reads = []

    async def manage_read(**kwargs):
        reads.append(kwargs)
        assert kwargs["headers"]["X-Tenant-Id"] == "tenant-a"
        if "universe-attestations" in kwargs["url"]:
            return 200, attestation
        if "/membership/" in kwargs["url"]:
            return 200, membership
        return 200, definition

    async def core_reference(**kwargs):
        return 200, {"portfolio_open_date": "2026-01-01", "portfolio_currency": "USD"}

    async def core_timeseries(**kwargs):
        assert kwargs["headers"]["X-Tenant-Id"] == "tenant-a"
        member = kwargs["url"].split("/portfolios/")[1].split("/")[0]
        beginning, ending = (figures or STANDARD_ASSETS)[member]
        return 200, {
            "portfolio_open_date": "2026-01-01",
            "portfolio_currency": "USD",
            "reporting_currency": "USD",
            "observations": [
                {
                    "valuation_date": "2026-01-02",
                    "beginning_market_value": beginning,
                    "ending_market_value": beginning,
                    "source_classification": "official",
                },
                {
                    "valuation_date": "2026-01-05",
                    "beginning_market_value": beginning,
                    "ending_market_value": ending,
                    "source_classification": "official",
                    "cash_flows": (flows or {}).get(member, []),
                },
            ],
        }

    monkeypatch.setattr(get_settings(), "MANAGE_BASE_URL", "http://manage-fixture")
    monkeypatch.setattr("app.adapters.composite_membership_source.get_with_retry", manage_read)
    monkeypatch.setattr("app.services.core_integration_service.get_with_retry", core_reference)
    monkeypatch.setattr("app.services.core_integration_service.post_with_retry", core_timeseries)
    return reads


def create_stateful_member(client, member, *, calculation_id=None, basis="NET", precision="FLOAT64", rounding=6):
    response = client.post(
        "/performance/twr",
        json={
            "calculation_id": str(calculation_id or uuid4()),
            "portfolio_id": member,
            "input_mode": "stateful",
            "stateful_input": {},
            "report_start_date": "2026-01-05",
            "report_end_date": "2026-01-05",
            "metric_basis": basis,
            "precision_mode": precision,
            "rounding_precision": rounding,
            "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    return {
        "portfolio_id": member,
        "calculation_id": result["calculation_id"],
        "input_fingerprint": result["meta"]["input_fingerprint"],
        "calculation_hash": result["meta"]["calculation_hash"],
    }


def composite_request(command, *, sequence=None):
    return {
        "composite_id": command.composite_id,
        "period_start": "2026-01-05",
        "period_end": "2026-01-05",
        "return_view": command.return_view.value,
        "reporting_currency": "USD",
        "restatement_sequence": sequence,
    }


def test_retained_member_adapter_refuses_conflicting_execution_and_financial_evidence(monkeypatch):
    """Adversarial retained reads start from an actual registered STATEFUL result."""
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    install_source_wire_controls(monkeypatch, products)
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        reference = create_stateful_member(client, "A", precision="DECIMAL_STRICT")
        process_lineage(limit=100)
        command = command_for(products, member_calculations=[reference])
        pinned = command.member_calculations[0]
        retained = execution_registry.get_execution_for_tenant(pinned.calculation_id, tenant_id="tenant-a")
        source = RetainedCompositeMemberResultSource()

        def read():
            return source.read_member(
                command,
                pinned,
                tenant_id="tenant-a",
                membership_snapshot_id=command.membership_content_hash,
                request_headers=headers,
            )

        # Public percentage projection can retain binary-linking noise even in
        # strict mode; the composite keeps that published value, not an asset proxy.
        assert read().fact.return_value.quantize(Decimal("1e-12")) == Decimal("0.10")
        assert (read().fact.beginning_market_value, read().fact.ending_market_value) == (Decimal(100), Decimal(110))
        wrong_membership = source.read_member(
            command,
            pinned,
            tenant_id="tenant-a",
            membership_snapshot_id="sha256:" + "c" * 64,
            request_headers=headers,
        )
        assert wrong_membership.reason_code == "MEMBER_FINANCIAL_EVIDENCE_REFUSED"
        assert wrong_membership.fact is None and wrong_membership.source_evidence is None
        foreign = source.read_member(
            command,
            pinned,
            tenant_id="tenant-a",
            membership_snapshot_id=command.membership_content_hash,
            request_headers={**headers, "X-Tenant-Id": "tenant-b", "X-Portfolio-Id": "A"},
        )
        assert foreign.reason_code == "MEMBER_RESULT_AUTHORITY_REFUSED"
        assert foreign.fact is None and foreign.source_evidence is None
        wrong_fee_request = deepcopy(retained.request_payload)
        wrong_fee_request["resolved_request"]["portfolio"]["metric_basis"] = "GROSS"
        variants = [
            (None, "PINNED_MEMBER_RESULT_PENDING"),
            (replace(retained, response_payload=None), "PINNED_MEMBER_RESULT_PENDING"),
            (replace(retained, analytics_type="CONTRIBUTION"), "MEMBER_RESULT_IDENTITY_MISMATCH"),
            (replace(retained, portfolio_id="OTHER"), "MEMBER_RESULT_IDENTITY_MISMATCH"),
            (replace(retained, status=ExecutionStatus.FAILED), "MEMBER_RESULT_NOT_COMPLETE"),
            (replace(retained, calculation_hash="sha256:" + "c" * 64), "MEMBER_RESULT_FINGERPRINT_MISMATCH"),
            (replace(retained, request_payload=wrong_fee_request), "MEMBER_RETURN_VIEW_NOT_SUPPORTED"),
            (replace(retained, upstream_snapshots=[]), "MEMBER_FINANCIAL_EVIDENCE_REFUSED"),
            (
                replace(retained, upstream_snapshots=[replace(retained.upstream_snapshots[0], retrieval_status="503")]),
                "MEMBER_FINANCIAL_EVIDENCE_REFUSED",
            ),
        ]
        for changed, code in variants:
            with monkeypatch.context() as context:
                context.setattr(
                    "app.adapters.composite_member_result_source.execution_registry",
                    SimpleNamespace(get_execution_for_tenant=lambda *args, **kwargs: changed),
                )
                outcome = read()
                assert outcome.reason_code == code
                assert outcome.fact is None and outcome.source_evidence is None
        period_key = next(iter(retained.response_payload["results_by_period"]))
        daily = ("results_by_period", period_key, "portfolio", "breakdowns", "daily", 0)
        evidence = (*daily, "calculation_evidence")
        cases = [
            ("response", ("calculation_id",), str(uuid4())),
            ("response", ("portfolio_id",), "OTHER"),
            ("response", ("meta", "calculation_hash"), "sha256:" + "c" * 64),
            ("response", ("input_mode",), "stateless"),
            ("response", ("calculation_supportability", "state"), "unavailable"),
            ("response", ("calculation_supportability", "source_quality_evidence"), None),
            ("response", ("calculation_supportability", "source_quality_evidence", "source_owner"), "other"),
            ("response", ("calculation_supportability", "source_quality_evidence", "quality_state"), "degraded"),
            ("response", ("calculation_supportability", "history_coverage"), None),
            ("response", ("calculation_supportability", "history_coverage", "status"), "partial"),
            ("response", ("calculation_supportability", "history_coverage", "requested_start_date"), "2026-01-04"),
            ("response", ("currency_evidence", "applied_report_ccy"), "EUR"),
            ("response", ("results_by_period",), {}),
            ("response", (*daily, "period_end"), "2026-01-06"),
            ("response", evidence, None),
            ("response", (*evidence, "status"), "unavailable"),
            ("response", (*evidence, "portfolio_currency"), "EUR"),
            ("response", (*evidence, "daily_return"), 99),
            ("response", (*evidence, "daily_return"), "Infinity"),
            (
                "response",
                daily[:-1],
                [
                    deepcopy(
                        retained.response_payload["results_by_period"][period_key]["portfolio"]["breakdowns"]["daily"][
                            0
                        ]
                    ),
                    deepcopy(
                        retained.response_payload["results_by_period"][period_key]["portfolio"]["breakdowns"]["daily"][
                            0
                        ]
                    ),
                ],
            ),
            ("response", (*evidence, "begin_mv"), 99),
            ("response", (*evidence, "end_mv"), 111),
            ("request", ("source_asset_evidence",), None),
            ("request", ("source_asset_evidence", "portfolio_currency"), "EUR"),
            ("request", ("source_asset_evidence", "observations", -1, "valuation_date"), "2026-01-06"),
            ("request", ("source_asset_evidence", "observations", -1, "beginning_market_value"), "-1"),
            ("request", ("resolved_request", "portfolio", "rounding_precision"), 12),
        ]
        for family, path, value in cases:
            request, response = deepcopy(retained.request_payload), deepcopy(retained.response_payload)
            target = response if family == "response" else request
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            changed = replace(retained, request_payload=request, response_payload=response)
            with monkeypatch.context() as context:
                context.setattr(
                    "app.adapters.composite_member_result_source.execution_registry",
                    SimpleNamespace(get_execution_for_tenant=lambda *args, **kwargs: changed),
                )
                outcome = read()
                assert outcome.reason_code == "MEMBER_FINANCIAL_EVIDENCE_REFUSED", (family, path, outcome)
                assert outcome.fact is None and outcome.source_evidence is None
        assert execution_registry.get_execution_for_tenant(pinned.calculation_id, tenant_id="tenant-a") == retained


@pytest.mark.parametrize("basis,view", [("NET", "NET_ACTUAL"), ("GROSS", "GROSS")])
@pytest.mark.parametrize("precision", ["FLOAT64", "DECIMAL_STRICT"])
@pytest.mark.parametrize("rounding", [6, 12])
def test_http_materialization_preserves_cashflow_fee_and_precision_inputs(
    monkeypatch, basis, view, precision, rounding
):
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    figures = {**STANDARD_ASSETS, "A": ("100", "122")}
    # Existing TWR convention: valuation122 excludes the separately supplied
    # fee2. BOD capital120 grows10%, then EOD withdrawal10 leaves122.
    flows = {
        "A": [
            {"amount": "20", "timing": "bod", "cash_flow_type": "external_flow"},
            {"amount": "-10", "timing": "eod", "cash_flow_type": "external_flow"},
            {"amount": "-2", "timing": "eod", "cash_flow_type": "fee"},
        ]
    }
    install_source_wire_controls(monkeypatch, products, figures=figures, flows=flows)
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        references = [
            create_stateful_member(client, member, basis=basis, precision=precision, rounding=rounding)
            for member in ("A", "B", "C")
        ]
        process_lineage(limit=100)
        command = command_for(products, return_view=view, member_calculations=references)
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        receipt = client.get(accepted.json()["result_path"]).json()
        assert receipt["state"] == "COMPLETE", receipt
        member = receipt["members"][0]
        request = member["source_evidence"]["calculation_request"]["portfolio"]
        assert request["metric_basis"] == basis and request["precision_mode"] == precision
        assert request["rounding_precision"] == rounding
        last = request["valuation_points"][-1]
        assert (Decimal(str(last["bod_cf"])), Decimal(str(last["eod_cf"])), Decimal(str(last["mgmt_fees"]))) == (
            Decimal(20),
            Decimal(-10),
            Decimal(-2),
        )
        # Derive the constituent and asset-weighted return independently from
        # explicit flows; changing fee view must not change retained source money.
        net_fee = Decimal(-2) if basis == "NET" else Decimal(0)
        a_return = (Decimal(122) - Decimal(100) - Decimal(20) - Decimal(-10) + net_fee) / Decimal(120)
        # FLOAT64 rounds public percentages; DECIMAL_STRICT retains the decimal
        # result. Preserve the reported policy, not reconstructed asset returns.
        a_reported = (
            a_return
            if precision == "DECIMAL_STRICT"
            else ((a_return * Decimal(100)).quantize(Decimal(1).scaleb(-rounding)) / Decimal(100))
        )
        expected = (
            Decimal(100) * a_reported + Decimal(200) * Decimal("0.05") + Decimal(300) * Decimal("-0.02")
        ) / Decimal(600)
        assert abs(Decimal(member["fact"]["return_value"]) - a_reported) < Decimal("1e-12")
        result = client.post("/performance/composites/twr", json=composite_request(command))
        assert result.status_code == 200, result.text
        period = result.json()["periods"][0]
        assert abs(Decimal(str(period["return_value"])) - expected) <= Decimal("1e-12")
        assert Decimal(str(period["beginning_market_value"])) == Decimal(600)
        assert Decimal(str(period["ending_market_value"])) == Decimal(626)


def test_http_missing_member_recovery_and_correction_preserve_reported_version(monkeypatch):
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    figures = dict(STANDARD_ASSETS)
    reads = install_source_wire_controls(monkeypatch, products, figures=figures)
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        references = [create_stateful_member(client, member) for member in ("A", "B")]
        process_lineage(limit=100)
        references.append(create_stateful_member(client, "C"))
        process_lineage(limit=100)
        # Expire only C's owned execution, then recover its pinned inputs through
        # the supported TWR API. No member-return facts are seeded directly.
        assert execution_registry.delete_executions([references[-1]["calculation_id"]]) == 1
        command = command_for(products, member_calculations=references)
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert process_pending_jobs(limit=10) == 1
        partial = client.get(accepted.json()["result_path"]).json()
        assert (partial["state"], partial["ready_count"], partial["waiting_count"]) == ("WAITING", 2, 1)
        assert partial["members"][-1]["portfolio_id"] == "C"
        assert partial["members"][-1]["fact"] is None
        refused = client.post("/performance/composites/twr", json=composite_request(command))
        assert refused.status_code != 200 or refused.json()["status"] != "READY", refused.text
        pending_job = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a")
        for _ in range(pending_job.max_attempts - pending_job.attempt_count):
            assert process_pending_jobs(limit=10) == 1
        exhausted_job = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a")
        assert exhausted_job.job_status == "failed" and exhausted_job.attempt_count == exhausted_job.max_attempts
        exhausted_replay = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert exhausted_replay.status_code == 202
        assert compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a") == exhausted_job
        assert create_stateful_member(client, "C", calculation_id=references[-1]["calculation_id"]) == references[-1]
        process_lineage(limit=100)
        resumed = command.model_copy(update={"calculation_id": uuid4()})
        resumed_acceptance = client.post(
            "/performance/composites/materializations", json=resumed.model_dump(mode="json")
        )
        assert resumed_acceptance.status_code == 202, resumed_acceptance.text
        assert process_pending_jobs(limit=10) == 1
        process_lineage(limit=100)
        assert client.get(accepted.json()["result_path"]).json()["state"] == "COMPLETE"
        assert compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a").job_status == "failed"
        original = client.post("/performance/composites/twr", json=composite_request(command, sequence=1))
        assert original.status_code == 200, original.text
        original_result = original.json()
        assert Decimal(str(original_result["periods"][0]["return_value"])) == (Decimal(14) / Decimal(600)).quantize(
            Decimal("0.000000000001")
        )
        assert len(reads) == 3  # Retry used retained membership and ready A/B receipts.

        figures["A"] = ("100", "120")
        corrected_references = [create_stateful_member(client, "A"), *references[1:]]
        process_lineage(limit=100)
        assert execution_registry.delete_executions([corrected_references[0]["calculation_id"]]) == 1
        corrected = command_for(products, member_calculations=corrected_references, restatement_sequence=2)
        corrected_acceptance = client.post(
            "/performance/composites/materializations", json=corrected.model_dump(mode="json")
        )
        assert corrected_acceptance.status_code == 202, corrected_acceptance.text
        assert process_pending_jobs(limit=10) == 1
        pending_latest = client.post("/performance/composites/twr", json=composite_request(command))
        assert pending_latest.status_code != 200 or pending_latest.json()["status"] != "READY", pending_latest.text
        retained_original = client.post("/performance/composites/twr", json=composite_request(command, sequence=1))
        assert retained_original.status_code == 200
        assert retained_original.json()["periods"] == original_result["periods"]
        assert (
            create_stateful_member(client, "A", calculation_id=corrected_references[0]["calculation_id"])
            == corrected_references[0]
        )
        process_lineage(limit=100)
        assert process_pending_jobs(limit=10) == 1
        process_lineage(limit=100)
        revised = client.post("/performance/composites/twr", json=composite_request(command))
        assert revised.status_code == 200, revised.text
        assert revised.json()["status"] == "READY"
        assert Decimal(str(revised.json()["periods"][0]["return_value"])) == Decimal("0.04")
        assert (
            client.post("/performance/composites/twr", json=composite_request(command, sequence=1)).json()["periods"]
            == original_result["periods"]
        )


@pytest.mark.parametrize("figures", [STANDARD_ASSETS, LARGE_EXACT_ASSETS], ids=["three-members", "exact-large-assets"])
def test_registered_stateful_twr_to_materialization_to_composite_with_independent_figures(monkeypatch, figures):
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    reads = install_source_wire_controls(monkeypatch, products, figures=figures)
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        references = []
        for member, expected in (("A", 10), ("B", 5), ("C", -2)):
            response = client.post(
                "/performance/twr",
                json={
                    "calculation_id": str(uuid4()),
                    "portfolio_id": member,
                    "input_mode": "stateful",
                    "stateful_input": {},
                    "report_start_date": "2026-01-05",
                    "report_end_date": "2026-01-05",
                    "metric_basis": "NET",
                    "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
                },
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["calculation_supportability"]["state"] == "ready", result["calculation_supportability"]
            assert (
                abs(result["results_by_period"]["EXPLICIT"]["portfolio"]["summary"]["period_return"]["base"] - expected)
                < 1e-10
            )
            references.append(
                {
                    "portfolio_id": member,
                    "calculation_id": result["calculation_id"],
                    "input_fingerprint": result["meta"]["input_fingerprint"],
                    "calculation_hash": result["meta"]["calculation_hash"],
                }
            )
        process_lineage(limit=100)
        command = command_for(products, member_calculations=references)
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert reads == []  # Member source resolution is not request-time fan-out.
        assert client.get(accepted.json()["result_path"]).json()["state"] == "WAITING"
        assert process_pending_jobs(limit=10) == 1
        job = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a")
        assert job.job_status == "complete", job
        process_lineage(limit=100)
        assert execution_registry.get_execution(command.calculation_id).status == "complete"
        inspected = client.get(accepted.json()["result_path"], params={"limit": 2})
        assert inspected.status_code == 200, inspected.text
        progress = inspected.json()
        assert all(member["state"] == "READY" for member in progress["members"]), {
            member["portfolio_id"]: member["reason_code"] for member in progress["members"]
        }
        assert (progress["state"], progress["expected_count"], progress["ready_count"], progress["next_offset"]) == (
            "COMPLETE",
            3,
            3,
            2,
        ), progress
        for parameters in (
            {"offset": 2, "limit": 2},
            {"offset": 2, "limit": 2, "expected_revision": progress["revision"] - 1},
        ):
            changed_page = client.get(accepted.json()["result_path"], params=parameters)
            assert changed_page.status_code == 409
            assert changed_page.json()["error_code"] == "COMPOSITE_MATERIALIZATION_PAGE_EVIDENCE_CHANGED"
        exhausted = client.get(
            accepted.json()["result_path"], params={"offset": 2, "limit": 2, "expected_revision": progress["revision"]}
        ).json()
        assert exhausted["returned_count"] == 1 and exhausted["next_offset"] is None
        all_members = progress["members"] + exhausted["members"]
        for member in all_members:
            beginning, ending = map(Decimal, figures[member["portfolio_id"]])
            assert Decimal(member["fact"]["beginning_market_value"]) == beginning
            assert Decimal(member["fact"]["ending_market_value"]) == ending
            receipt = member["source_evidence"]
            assert receipt["membership_snapshot_id"] == command.membership_content_hash
            assert receipt["core_snapshots"][0]["source_identifier"] == member["portfolio_id"]
            assert member["fact"]["source_snapshot_id"] != command.membership_content_hash
            observation = receipt["source_assets"]["observations"][0]
            assert Decimal(observation["beginning_market_value"]) == beginning
            assert Decimal(observation["ending_market_value"]) == ending

        # Expire only these test-owned member executions; composite receipts must
        # remain sufficient after the upstream execution/snapshot retention ends.
        assert execution_registry.delete_executions([item["calculation_id"] for item in references]) == 3
        assert all(execution_registry.get_execution(item["calculation_id"]) is None for item in references)
        retained = composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")
        assert len(retained.outcomes) == 3 and all(item.source_evidence is not None for item in retained.outcomes)
        calculated = client.post(
            "/performance/composites/twr",
            json={
                "composite_id": command.composite_id,
                "period_start": "2026-01-05",
                "period_end": "2026-01-05",
                "return_view": "NET_ACTUAL",
                "reporting_currency": "USD",
            },
        )
        assert calculated.status_code == 200, calculated.text
        result = calculated.json()
        assert result["status"] == "READY"
        period = result["periods"][0]
        beginning_total = sum(Decimal(pair[0]) for pair in figures.values())
        ending_total = sum(Decimal(pair[1]) for pair in figures.values())
        independent_return = (ending_total - beginning_total) / beginning_total
        assert abs(Decimal(str(period["return_value"])) - independent_return) <= Decimal("0.000000000001")
        assert Decimal(str(period["beginning_market_value"])) == beginning_total.quantize(Decimal("0.000001"))
        assert Decimal(str(period["ending_market_value"])) == ending_total.quantize(Decimal("0.000001"))
        replay = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert replay.status_code == 202
        assert len(reads) == 3
        denied = client.get(accepted.json()["result_path"], headers={"X-Tenant-Id": "tenant-b"})
        assert denied.status_code == 404


def test_materialization_refuses_missing_or_duplicated_authority_before_durable_acceptance():
    command = command_for(source_products(composite_id="COMPOSITE_" + uuid4().hex))
    with TestClient(app) as client:
        missing = client.post(
            "/performance/composites/materializations",
            json=command.model_dump(mode="json"),
            headers={"X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"},
        )
        assert missing.status_code == 401
        duplicated = client.post(
            "/performance/composites/materializations",
            json=command.model_dump(mode="json"),
            headers=[
                ("X-Tenant-Id", "tenant-a"),
                ("X-Tenant-Id", "tenant-b"),
                ("X-Actor-Id", "operator"),
                ("X-Role", "DPM_COMPOSITE_CONSUMER"),
            ],
        )
        assert duplicated.status_code == 400
    assert execution_registry.get_execution(command.calculation_id) is None
    assert compute_job_store.get_job(command.calculation_id) is None
    with pytest.raises(APINotFoundError):
        composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")


@pytest.mark.parametrize("header", ["X-Actor-Id", "X-Role"])
@pytest.mark.parametrize("values", [[" "], ["a" * 129], ["operator", "foreign"]])
def test_materialization_refuses_malformed_caller_identity_without_accepting_work(header, values):
    command = command_for(source_products(composite_id="COMPOSITE_" + uuid4().hex))
    valid = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    malformed = [(key, value) for key, value in valid.items() if key != header]
    malformed.extend((header, value) for value in values)
    with TestClient(app) as client:
        refused = client.post(
            "/performance/composites/materializations", json=command.model_dump(mode="json"), headers=malformed
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["error_code"] == "COMPOSITE_CALLER_IDENTITY_MALFORMED"
        assert execution_registry.get_execution(command.calculation_id) is None
        assert compute_job_store.get_job(command.calculation_id) is None
        with pytest.raises(APINotFoundError):
            composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")
        accepted = client.post(
            "/performance/composites/materializations", json=command.model_dump(mode="json"), headers=valid
        )
        assert accepted.status_code == 202, accepted.text
        assert compute_job_store.get_job(command.calculation_id).request_payload["actor_id"] == "operator"


def test_model_fee_view_is_refused_before_accepting_a_doomed_job():
    command = command_for(source_products(composite_id="COMPOSITE_" + uuid4().hex))
    payload = command.model_dump(mode="json")
    payload["return_view"] = "NET_MODEL_FEE"
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        response = client.post("/performance/composites/materializations", json=payload)
    assert response.status_code == 422, response.text
    assert execution_registry.get_execution(command.calculation_id) is None
    assert compute_job_store.get_job(command.calculation_id) is None
    with pytest.raises(APINotFoundError):
        composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")


@pytest.mark.parametrize("collision", ["execution", "job"])
@pytest.mark.parametrize("stored_tenant", ["tenant-a", "tenant-b"])
def test_calculation_collision_rolls_back_reservation_without_foreign_effects(collision, stored_tenant):
    command = command_for(source_products(composite_id="COMPOSITE_" + uuid4().hex))
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        if collision == "execution":
            execution_registry.register_execution(
                calculation_id=command.calculation_id,
                tenant_id=stored_tenant,
                analytics_type="TWR",
                portfolio_id="unrelated-owner",
                execution_mode="async",
                request_payload={"owned": "do-not-rewrite"},
            )
        else:
            compute_job_store.register_job(
                calculation_id=command.calculation_id,
                tenant_id=stored_tenant,
                analytics_type="TWR",
                request_payload={"owned": "do-not-rewrite"},
            )
        original_execution = execution_registry.get_execution(command.calculation_id)
        original_job = compute_job_store.get_job(command.calculation_id)
        refused = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert refused.status_code == 409, refused.text
        assert execution_registry.get_execution(command.calculation_id) == original_execution
        assert compute_job_store.get_job(command.calculation_id) == original_job
        with pytest.raises(APINotFoundError):
            composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")
        retry = command.model_copy(update={"calculation_id": uuid4()})
        accepted = client.post("/performance/composites/materializations", json=retry.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        assert client.get(accepted.json()["result_path"]).json()["state"] == "WAITING"


@pytest.mark.parametrize("fault_location", ["queue", "submission-stage"])
def test_failure_after_row_write_rolls_back_entire_admission(monkeypatch, fault_location):
    command = command_for(source_products(composite_id="COMPOSITE_" + uuid4().hex))
    owner, method = (
        (ComputeJobStore, "register_job") if fault_location == "queue" else (ExecutionRegistry, "complete_stage")
    )
    original = getattr(owner, method)

    def fail_after_write(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("Controlled failure after durable adapter write")

    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers, raise_server_exceptions=False) as client:
        with monkeypatch.context() as fault:
            fault.setattr(owner, method, fail_after_write)
            refused = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert refused.status_code == 500, refused.text
        assert execution_registry.get_execution(command.calculation_id) is None
        assert compute_job_store.get_job(command.calculation_id) is None
        with pytest.raises(APINotFoundError):
            composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text


@pytest.mark.parametrize(
    "service_identity,capabilities,expected_status",
    [
        ("composite-operator", "operations.runtime.manage", 403),
        (None, "operations.runtime.manage,operations.runtime.read", 403),
        ("composite-operator", "operations.runtime.manage,operations.runtime.read", 202),
    ],
)
def test_command_requires_replayable_member_read_authority_before_acceptance(
    monkeypatch, service_identity, capabilities, expected_status
):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    command = command_for(source_products(composite_id="COMPOSITE_" + uuid4().hex))
    headers = {
        "X-Tenant-Id": "tenant-a",
        "X-Actor-Id": "operator",
        "X-Role": "DPM_COMPOSITE_CONSUMER",
        "X-Correlation-Id": "composite-command-control",
        "X-Capabilities": capabilities,
        "Authorization": "Bearer transient-test-identity",
    }
    if service_identity:
        headers["X-Service-Identity"] = service_identity
    with TestClient(app) as client:
        response = client.post(
            "/performance/composites/materializations", json=command.model_dump(mode="json"), headers=headers
        )
    assert response.status_code == expected_status, response.text
    if expected_status == 403:
        assert execution_registry.get_execution(command.calculation_id) is None
        assert compute_job_store.get_job(command.calculation_id) is None
        with pytest.raises(APINotFoundError):
            composite_materialization_store.get(command.materialization_id, tenant_id="tenant-a")
    else:
        job = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id="tenant-a")
        assert "authorization" not in {header.lower() for header in job.request_payload["authority"]}
        assert "transient-test-identity" not in str(job.request_payload)
