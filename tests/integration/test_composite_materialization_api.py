from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_materialization_repository import composite_materialization_store
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.models.composite_authority import EvidenceBinding, authority_digest
from app.services.composite_materialization.source_contract import source_digest
from app.services.compute_job_store import ComputeJobStore, compute_job_store
from app.services.execution_registry import ExecutionRegistry, ExecutionStatus, execution_registry
from app.services.stateful_input_service import StatefulInputService
from app.workers.compute_executor_worker import process_pending_jobs
from app.workers.lineage_worker import process_pending_jobs as process_lineage
from core.errors import APINotFoundError
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_currency_normalization_helpers import normalization_wire, synthetic_fx_verification
from tests.composite_materialization_helpers import command_for, source_products


@pytest.fixture(autouse=True)
def isolated_materialization_api_metadata(monkeypatch, tmp_path):
    database_url = "sqlite:///" + (tmp_path / "metadata.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", database_url)
    assert apply_durable_schema(database_url=database_url).status == "passed"


STANDARD_ASSETS = {"A": ("100", "110"), "B": ("200", "210"), "C": ("300", "294")}
LARGE_EXACT_ASSETS = {
    "A": ("9007199254740993.001", "9907919180215092.3011"),
    "B": ("200.002", "210.0021"),
    "C": ("300.003", "294.00294"),
}


def install_source_wire_controls(
    monkeypatch, products, *, figures=None, flows=None, currencies=None, performance_day="2026-01-05"
):
    """Controlled upstream wires, not live Manage/Core acceptance."""
    definition, membership, attestation = products
    tenant_id = definition["tenant_id"]
    reads = []

    async def manage_read(**kwargs):
        reads.append(kwargs)
        assert kwargs["headers"]["X-Tenant-Id"] == tenant_id
        if "universe-attestations" in kwargs["url"]:
            return 200, attestation
        if "/membership/" in kwargs["url"]:
            return 200, membership
        return 200, definition

    async def core_reference(**kwargs):
        member = kwargs["url"].split("/portfolios/")[1].split("/")[0]
        return 200, {"portfolio_open_date": "2026-01-01", "portfolio_currency": (currencies or {}).get(member, "USD")}

    async def core_timeseries(**kwargs):
        assert kwargs["headers"]["X-Tenant-Id"] == tenant_id
        member = kwargs["url"].split("/portfolios/")[1].split("/")[0]
        beginning, ending = (figures or STANDARD_ASSETS)[member]
        currency = (currencies or {}).get(member, "USD")
        return 200, {
            "portfolio_open_date": "2026-01-01",
            "portfolio_currency": currency,
            "reporting_currency": currency,
            "observations": [
                {
                    "valuation_date": "2026-01-02",
                    "beginning_market_value": beginning,
                    "ending_market_value": beginning,
                    "source_classification": "official",
                },
                {
                    "valuation_date": performance_day,
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


def create_stateful_member(
    client, member, *, calculation_id=None, basis="NET", precision="FLOAT64", rounding=6, performance_day="2026-01-05"
):
    response = client.post(
        "/performance/twr",
        json={
            "calculation_id": str(calculation_id or uuid4()),
            "portfolio_id": member,
            "input_mode": "stateful",
            "stateful_input": {},
            "report_start_date": performance_day,
            "report_end_date": performance_day,
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
        "period_start": str(command.period_start),
        "period_end": str(command.period_end),
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


def test_registered_fx_normalization_refuses_legacy_retained_identity_member_after_child_expiry(monkeypatch):
    import json

    from sqlalchemy import text

    from app.adapters.composite_materialization_repository import CompositeMaterializationStore
    from app.models.composite_materialization import CompositeMemberSourceEvidence
    from app.services.reproducibility_service import generate_value_fingerprint
    from core.errors import APIError

    captured = {}

    def capture(command, wire, receipt, periods):
        captured.update(command=command, receipt=receipt, periods=periods)

    run_registered_fx_money_control(monkeypatch, normalize=True, eod_flow="0", capture=capture)
    command = captured["command"]

    def refuse_refetch(*args, **kwargs):
        raise AssertionError("Retained custody validation cannot consult expired child executions")

    monkeypatch.setattr(execution_registry, "get_execution_for_tenant", refuse_refetch)
    ledger = CompositeMaterializationStore(get_settings().LINEAGE_METADATA_DATABASE_URL)
    identity = {"identity": str(command.materialization_id), "tenant": "tenant-a"}
    update = text(
        "UPDATE composite_materializations SET outcomes_json=:wire "
        "WHERE materialization_id=:identity AND tenant_id=:tenant"
    )
    try:
        with ledger._engine.connect() as connection:
            original = connection.execute(
                text(
                    "SELECT outcomes_json FROM composite_materializations "
                    "WHERE materialization_id=:identity AND tenant_id=:tenant"
                ),
                identity,
            ).scalar_one()
        outcomes = json.loads(original)
        member = next(row for row in outcomes if row["portfolio_id"] == "B")
        legacy = CompositeMemberSourceEvidence.model_validate(member["source_evidence"]["native_evidence"])
        assert legacy.source_assets.portfolio_currency == member["fact"]["reporting_currency"] == "USD"
        member["source_evidence"] = legacy.model_dump(mode="json")
        member["fact"]["source_snapshot_id"] = generate_value_fingerprint(legacy, "composite-member-source.v1")[0]
        with ledger._engine.begin() as connection:
            assert connection.execute(update, {**identity, "wire": json.dumps(outcomes)}).rowcount == 1
        try:
            with pytest.raises(APIError) as refused:
                ledger.get(command.materialization_id, tenant_id="tenant-a")
            assert refused.value.error_code == "COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED"
            assert refused.value.__cause__.error_code == "COMPOSITE_MATERIALIZATION_MEMBER_EVIDENCE_REFUSED"
            headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
            with TestClient(app, headers=headers) as client:
                inspected = client.get(f"/performance/composites/materializations/{command.materialization_id}")
                assert inspected.status_code == 503, inspected.text
                assert inspected.json()["error_code"] == "COMPOSITE_MATERIALIZATION_RETAINED_EVIDENCE_REFUSED"
                report = client.post(
                    "/performance/composites/twr",
                    json={**composite_request(command), "materialization_ids": [str(command.materialization_id)]},
                )
                assert report.status_code == 503 and "cumulative_return" not in report.json(), report.text
        finally:
            with ledger._engine.begin() as connection:
                assert connection.execute(update, {**identity, "wire": original}).rowcount == 1
        with TestClient(app, headers=headers) as client:
            assert (
                client.get(f"/performance/composites/materializations/{command.materialization_id}").json()
                == captured["receipt"]
            )
            report = client.post("/performance/composites/twr", json=composite_request(command))
            assert report.status_code == 200 and report.json()["periods"] == captured["periods"], report.text
    finally:
        ledger.close()


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


@pytest.mark.parametrize("normalize", [False, True], ids=["unconverted-refused", "admitted-synthetic-normalization"])
@pytest.mark.parametrize("eod_flow", ["0", "10"], ids=["no-flow", "economic-date-flow"])
def test_registered_materialization_refuses_translated_return_without_converted_source_money(
    monkeypatch, normalize, eod_flow
):
    run_registered_fx_money_control(monkeypatch, normalize=normalize, eod_flow=eod_flow)


def run_registered_fx_money_control(
    monkeypatch,
    *,
    normalize,
    eod_flow,
    capture=None,
    products=None,
    ending_rate="1.4",
    restatement_sequence=1,
    materialization_id=None,
    performance_day="2026-01-05",
    beginning_rate="1.3",
    native_figures=None,
    normalization_fault=None,
    expected_fx_refusal=None,
    management_fee="0",
    return_view="NET_ACTUAL",
    normalization_method_revision="method1",
    temporary_fx_outage=False,
    precision="DECIMAL_STRICT",
    rounding=12,
    source_money_currency="EUR",
):
    """Reusable registered consumer control; captures immutable evidence for process proof."""
    products = products or source_products(composite_id="COMPOSITE_" + uuid4().hex)
    tenant_id = products[0]["tenant_id"]
    native_figures = native_figures or {**STANDARD_ASSETS, "A": ("100", "102")}
    a_begin, a_end = map(Decimal, native_figures["A"])
    figures_with_flow = {**native_figures, "A": (str(a_begin), str(a_end + Decimal(eod_flow)))}
    prior_day = (date.fromisoformat(performance_day) - timedelta(days=1)).isoformat()
    install_source_wire_controls(
        monkeypatch,
        products,
        figures=figures_with_flow,
        performance_day=performance_day,
        currencies={"A": source_money_currency},
        flows={
            "A": [
                {"amount": eod_flow, "timing": "eod", "cash_flow_type": "external_flow"},
                {"amount": management_fee, "timing": "eod", "cash_flow_type": "fee"},
            ]
        },
    )
    headers = {"X-Tenant-Id": tenant_id, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        translated = client.post(
            "/performance/twr",
            json={
                "calculation_id": str(uuid4()),
                "portfolio_id": "A",
                "input_mode": "stateful",
                "stateful_input": {},
                "report_start_date": performance_day,
                "report_end_date": performance_day,
                "metric_basis": "GROSS" if return_view == "GROSS" else "NET",
                "precision_mode": precision,
                "rounding_precision": rounding,
                "currency_mode": "BOTH",
                "report_ccy": "USD",
                "fx": {
                    "rates": [
                        {"date": "2026-01-01", "ccy": source_money_currency, "rate": beginning_rate},
                        {"date": "2026-01-02", "ccy": source_money_currency, "rate": beginning_rate},
                        {"date": prior_day, "ccy": source_money_currency, "rate": beginning_rate},
                        {"date": performance_day, "ccy": source_money_currency, "rate": ending_rate},
                    ]
                },
                "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
            },
        )
        assert translated.status_code == 200, translated.text
        result = translated.json()
        period = next(iter(result["results_by_period"].values()))["portfolio"]
        a_reporting_begin = a_begin * Decimal(beginning_rate)
        applied_fee = Decimal(management_fee) * Decimal(ending_rate) if return_view == "NET_ACTUAL" else Decimal(0)
        expected_member_return = (a_end * Decimal(ending_rate) - a_reporting_begin + applied_fee) / a_reporting_begin
        if precision == "FLOAT64":
            expected_member_return = Decimal(str(round(float(expected_member_return * 100), rounding))) / 100
        assert abs(Decimal(str(period["summary"]["period_return"]["base"])) / 100 - expected_member_return) < Decimal(
            "1e-12"
        )
        assert result["currency_evidence"]["fx_source"] == "caller_supplied"
        references = [
            {
                "portfolio_id": "A",
                "calculation_id": result["calculation_id"],
                "input_fingerprint": result["meta"]["input_fingerprint"],
                "calculation_hash": result["meta"]["calculation_hash"],
            },
            *[
                create_stateful_member(
                    client,
                    member,
                    performance_day=performance_day,
                    precision=precision,
                    rounding=rounding,
                    basis="GROSS" if return_view == "GROSS" else "NET",
                )
                for member in ("B", "C")
            ],
        ]
        process_lineage(limit=100)
        identity = {} if materialization_id is None else {"materialization_id": materialization_id}
        command = command_for(
            products,
            member_calculations=references,
            restatement_sequence=restatement_sequence,
            period_start=performance_day,
            period_end=performance_day,
            return_view=return_view,
            policy_version=products[0]["eligibility_policy_version"],
            **identity,
        )
        if normalize:
            command = install_normalization_source_controls(
                monkeypatch,
                command,
                references,
                beginning_rate=beginning_rate,
                ending_rate=ending_rate,
                tenant_id=tenant_id,
                normalization_fault=normalization_fault,
                normalization_method_revision=normalization_method_revision,
                composite_native_currency=products[0]["reporting_currency"],
                source_money_currency=source_money_currency,
            )
        accepted = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
        assert accepted.status_code == 202, accepted.text
        if temporary_fx_outage:
            from core.errors import APIServiceUnavailableError

            def unavailable(request):
                raise APIServiceUnavailableError("Controlled FX outage", error_code="COMPOSITE_FX_SOURCE_UNAVAILABLE")

            with monkeypatch.context() as outage:
                outage.setattr(
                    "app.ports.composite_currency_normalization.composite_fx_source_resolver",
                    lambda: SimpleNamespace(resolve=unavailable),
                )
                assert process_pending_jobs(limit=10) == 1
            pending = client.get(accepted.json()["result_path"]).json()
            assert (pending["state"], pending["expected_count"], pending["waiting_count"], pending["ready_count"]) == (
                "WAITING",
                3,
                3,
                0,
            )
            assert all(
                row["reason_code"] == "COMPOSITE_FX_SOURCE_UNAVAILABLE" and row["retryable"]
                for row in pending["members"]
            )
            assert all(row["fact"] is None and row["source_evidence"] is None for row in pending["members"])
            retained = composite_materialization_store.get(command.materialization_id, tenant_id=tenant_id)
            assert retained.source.currency_normalization_wire is None
            job = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id=tenant_id)
            assert job.job_status == "pending" and job.attempt_count == 1

            def refuse_membership_refetch(*args, **kwargs):
                raise AssertionError("Recovery must use the already admitted Manage source")

            monkeypatch.setattr(
                "app.services.composite_materialization.application._read_membership_source", refuse_membership_refetch
            )
        assert process_pending_jobs(limit=10) == 1
        receipt = client.get(accepted.json()["result_path"]).json()
        if expected_fx_refusal is not None:
            assert (receipt["state"], receipt["expected_count"], receipt["blocked_count"], receipt["ready_count"]) == (
                "BLOCKED",
                3,
                3,
                0,
            ), receipt
            assert [row["portfolio_id"] for row in receipt["members"]] == ["A", "B", "C"]
            assert all(row["reason_code"] == expected_fx_refusal for row in receipt["members"])
            assert all(row["fact"] is None and row["source_evidence"] is None for row in receipt["members"])
            assert client.post("/performance/composites/twr", json=composite_request(command)).status_code != 200
            retained = composite_materialization_store.get(command.materialization_id, tenant_id=tenant_id)
            assert retained.source.attestation.expected_portfolio_ids == ["A", "B", "C"]
            assert retained.source.currency_normalization_wire is None
            assert client.get(accepted.json()["result_path"]).json() == receipt
            return
        if normalize:
            assert (receipt["state"], receipt["expected_count"], receipt["ready_count"], receipt["blocked_count"]) == (
                "COMPLETE",
                3,
                3,
                0,
            ), receipt
            evidence = receipt["members"][0]["source_evidence"]
            assert evidence["contract_version"] == "composite-member-source.v3"
            assert evidence["native_evidence"]["source_assets"]["portfolio_currency"] == source_money_currency
            assert Decimal(receipt["members"][0]["fact"]["beginning_market_value"]) == a_reporting_begin
            assert Decimal(receipt["members"][0]["fact"]["ending_market_value"]) == (
                a_end + Decimal(eod_flow)
            ) * Decimal(ending_rate)
            converted_flow = evidence["normalized_cash_flows"][0]
            assert Decimal(converted_flow["native_amount"]) == Decimal(eod_flow)
            assert Decimal(converted_flow["reporting_amount"]) == Decimal(eod_flow) * Decimal(ending_rate)
            assert converted_flow["fixing_date"] == converted_flow["business_date"] == performance_day
            converted_fee = evidence["normalized_management_fees"][0]
            assert Decimal(converted_fee["native_amount"]) == Decimal(management_fee)
            assert Decimal(converted_fee["reporting_amount"]) == Decimal(management_fee) * Decimal(ending_rate)
            assert converted_fee["fixing_date"] == converted_fee["business_date"] == performance_day
            normalized = client.post(
                "/performance/composites/twr", json=composite_request(command, sequence=restatement_sequence)
            )
            assert normalized.status_code == 200, normalized.text
            period = normalized.json()["periods"][0]
            other_begin = sum(Decimal(native_figures[member][0]) for member in ("B", "C"))
            other_end = sum(Decimal(native_figures[member][1]) for member in ("B", "C"))
            total_begin = a_reporting_begin + other_begin
            expected_return = (a_end * Decimal(ending_rate) + other_end - total_begin + applied_fee) / total_begin
            if precision == "FLOAT64":
                expected_return = (a_reporting_begin * expected_member_return + other_end - other_begin) / total_begin
            assert abs(Decimal(str(period["return_value"])) - expected_return) <= Decimal("1e-12")
            assert Decimal(str(period["beginning_market_value"])) == total_begin
            assert (
                Decimal(str(period["ending_market_value"]))
                == (a_end + Decimal(eod_flow)) * Decimal(ending_rate) + other_end
            )
            assert evidence["verification_receipt"]["official_activation"] == "UNAVAILABLE"
            before_replay = compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id=tenant_id)
            replay = client.post("/performance/composites/materializations", json=command.model_dump(mode="json"))
            assert replay.status_code == 202 and replay.json()["materialization_id"] == str(command.materialization_id)
            assert compute_job_store.get_job_for_tenant(command.calculation_id, tenant_id=tenant_id) == before_replay
            assert (
                execution_registry.delete_executions([str(ref.calculation_id) for ref in command.member_calculations])
                == 3
            )
            from app.adapters.composite_materialization_repository import CompositeMaterializationStore
            from app.models.composite_materialization import CompositeNormalizedMemberSourceEvidence

            reopened_store = CompositeMaterializationStore(get_settings().LINEAGE_METADATA_DATABASE_URL)
            try:
                reloaded = reopened_store.get(command.materialization_id, tenant_id=tenant_id)
            finally:
                reopened_store.close()
            assert isinstance(reloaded.outcomes[0].source_evidence, CompositeNormalizedMemberSourceEvidence)
            assert reloaded.source.currency_normalization_wire is not None
            for member in reloaded.outcomes:
                retained_member = member.source_evidence.model_dump(mode="json")
                assert "normalization_source" not in retained_member
                assert "normalization_source_wire" not in retained_member
                assert retained_member["normalization_binding"] == command.currency_normalization_binding.model_dump(
                    mode="json"
                )
            from app.services.composite_materialization.progress_policy import require_retained_progress
            from core.errors import APIError

            for corrupted_wire in (None, {**reloaded.source.currency_normalization_wire, "revision": "changed"}):
                with pytest.raises(APIError):
                    require_retained_progress(
                        command=command,
                        tenant_id=tenant_id,
                        source=reloaded.source.model_copy(update={"currency_normalization_wire": corrupted_wire}),
                        outcomes=reloaded.outcomes,
                        state=reloaded.state,
                    )
            assert client.get(accepted.json()["result_path"]).json()["state"] == "COMPLETE"
            reported_again = client.post(
                "/performance/composites/twr", json=composite_request(command, sequence=restatement_sequence)
            )
            assert (
                reported_again.status_code == 200 and reported_again.json()["periods"] == normalized.json()["periods"]
            )
            if capture is not None:
                capture(command, reloaded.source.currency_normalization_wire, receipt, normalized.json()["periods"])
            return
        assert (receipt["state"], receipt["expected_count"], receipt["ready_count"], receipt["blocked_count"]) == (
            "BLOCKED",
            3,
            2,
            1,
        ), receipt
        assert [member["portfolio_id"] for member in receipt["members"]] == ["A", "B", "C"]
        refused_member = receipt["members"][0]
        assert refused_member["reason_code"] == "MEMBER_FINANCIAL_EVIDENCE_REFUSED"
        assert refused_member["fact"] is None and refused_member["source_evidence"] is None
        refused_result = client.post("/performance/composites/twr", json=composite_request(command))
        assert refused_result.status_code != 200 or refused_result.json()["status"] != "READY", refused_result.text


@pytest.mark.parametrize("rounding", [6, 12])
def test_registered_fx_normalization_preserves_float_return_projection_and_exact_money(monkeypatch, rounding):
    from app.models.composite_materialization import CompositeNormalizedMemberSourceEvidence
    from app.services.composite_materialization.currency_normalization import normalize_member_money
    from app.services.composite_materialization.currency_source_admission import (
        admit_composite_fx_source,
        fx_resolution_for_command,
    )

    captured = {}

    def capture(command, wire, receipt, periods):
        captured.update(command=command, wire=wire, receipt=receipt)

    run_registered_fx_money_control(
        monkeypatch, normalize=True, eod_flow="0", precision="FLOAT64", rounding=rounding, capture=capture
    )
    command = captured["command"]
    evidence = CompositeNormalizedMemberSourceEvidence.model_validate(
        captured["receipt"]["members"][0]["source_evidence"]
    )
    admitted = admit_composite_fx_source(
        fx_resolution_for_command(command, tenant_id="tenant-a"), retained_wire=captured["wire"]
    )
    if rounding == 6:
        assert abs(evidence.native_evidence.period_return - Decimal("0.09846154")) <= Decimal("1e-16")
    changed = evidence.native_evidence.model_copy(
        update={"period_return": evidence.native_evidence.period_return + Decimal("0.00000001")}
    )
    with pytest.raises(ValueError, match="Retained period return does not reconcile"):
        normalize_member_money(command, changed, admitted, member_id="A", fx_snapshots=evidence.fx_snapshots)


@pytest.mark.parametrize("native_currency", ["EUR", "GBP"])
def test_registered_fx_normalization_reports_independently_admitted_native_composite_in_usd(
    monkeypatch, native_currency
):
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    products[0]["reporting_currency"] = native_currency
    products[0]["content_hash"] = source_digest(products[0])

    def capture(command, wire, receipt, periods):
        assert command.reporting_currency == "USD" and wire["composite_native_currency"] == native_currency
        assert products[0]["inception_date"] == "2026-01-01"
        native = receipt["members"][0]["source_evidence"]["native_evidence"]
        assert native["calculation_request"]["portfolio"]["performance_start_date"] == "2026-01-01"
        assert native["source_assets"]["portfolio_currency"] == "EUR"

    run_registered_fx_money_control(monkeypatch, normalize=True, eod_flow="10", products=products, capture=capture)


def test_registered_fx_normalization_refuses_wrong_native_source_without_losing_manage_population(monkeypatch):
    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    products[0]["reporting_currency"] = "EUR"
    products[0]["content_hash"] = source_digest(products[0])
    run_registered_fx_money_control(
        monkeypatch,
        normalize=True,
        eod_flow="0",
        products=products,
        normalization_fault="wrong-native",
        expected_fx_refusal="COMPOSITE_FX_NATIVE_CURRENCY_MISMATCH",
    )


def test_registered_fx_normalization_recovers_exact_pending_source_after_temporary_outage(monkeypatch):
    run_registered_fx_money_control(monkeypatch, normalize=True, eod_flow="10", temporary_fx_outage=True)


def test_registered_fx_normalization_converts_actual_fee_without_changing_money_between_views(monkeypatch):
    from fractions import Fraction

    captured = {}
    for view in ("GROSS", "NET_ACTUAL"):

        def capture(command, wire, receipt, periods):
            captured[view] = {"receipt": receipt, "periods": periods}

        with monkeypatch.context() as scope:
            run_registered_fx_money_control(
                scope, normalize=True, eod_flow="0", management_fee="-2", return_view=view, capture=capture
            )
    expected = {"GROSS": (Fraction(32, 325), Fraction(2, 75)), "NET_ACTUAL": (Fraction(1, 13), Fraction(1, 45))}
    money = []
    for view, result in captured.items():
        member = result["receipt"]["members"][0]
        member_return, composite_return = expected[view]
        assert abs(
            Decimal(member["fact"]["return_value"]) - Decimal(member_return.numerator) / member_return.denominator
        ) <= Decimal("1e-12")
        assert abs(
            Decimal(str(result["periods"][0]["return_value"]))
            - Decimal(composite_return.numerator) / composite_return.denominator
        ) <= Decimal("1e-12")
        evidence = member["source_evidence"]
        money.append(
            (evidence["normalized_assets"], evidence["normalized_cash_flows"], evidence["normalized_management_fees"])
        )
        assert Decimal(evidence["normalized_management_fees"][0]["reporting_amount"]) == Decimal("-2.8")
    assert money[0] == money[1]


def install_normalization_source_controls(
    monkeypatch,
    command,
    references,
    *,
    beginning_rate="1.3",
    ending_rate="1.4",
    tenant_id="tenant-a",
    normalization_fault=None,
    normalization_method_revision="method1",
    composite_native_currency="USD",
    source_money_currency="EUR",
):
    """Actual snapshot helper + configured synthetic issuer; no institutional source admission."""
    prior_day = command.period_start - timedelta(days=1)
    source_cut_day = (command.period_end + timedelta(days=1)).isoformat()
    response = {
        "from_currency": source_money_currency,
        "to_currency": "USD",
        "rates": [
            {"rate_date": prior_day.isoformat(), "rate": beginning_rate},
            {"rate_date": command.period_end.isoformat(), "rate": ending_rate},
        ],
    }

    async def source_fx(**kwargs):
        return 200, response

    service = StatefulInputService(core_service=SimpleNamespace(get_fx_rates=source_fx))
    asyncio.run(
        service.get_fx_rates(
            from_currency=source_money_currency,
            to_currency="USD",
            start_date=prior_day,
            end_date=command.period_end,
            calculation_id=command.member_calculations[0].calculation_id,
        )
    )
    execution = execution_registry.get_execution_for_tenant(
        command.member_calculations[0].calculation_id, tenant_id=tenant_id
    )
    snapshot = next(row for row in execution.upstream_snapshots if row.upstream_endpoint == "fx_rates")
    wire = normalization_wire()
    wire.update(
        {
            "tenant_id": tenant_id,
            "composite_id": command.composite_id,
            "definition_content_hash": command.definition_content_hash,
            "membership_content_hash": command.membership_content_hash,
            "attestation_content_hash": command.attestation_content_hash,
            "return_view": str(command.return_view),
            "period_start": str(command.period_start),
            "period_end": str(command.period_end),
            "source_as_of_cut": source_cut_day + "T01:00:00Z",
            "composite_native_currency": composite_native_currency,
        }
    )
    original = wire["members"][0]
    original["source_money_currency"] = source_money_currency
    for fixing, source_rate in zip(original["fixings"], response["rates"], strict=True):
        day = source_rate["rate_date"]
        fixing.update(
            fixing_date=day,
            rate=source_rate["rate"],
            observed_at=day + "T21:00:00Z",
            revision_available_at=day + "T21:01:00Z",
            source_currency=source_money_currency,
        )
        fixing["retrieval_response_fingerprint"] = snapshot.response_fingerprint
        if fixing["fixing_date"] == str(command.period_end):
            fixing["rate"] = ending_rate
            if command.restatement_sequence > 1:
                fixing.update(source_revision="rates2", revision_available_at=source_cut_day + "T01:30:00Z")
                fixing["source_content_hash"] = authority_digest(
                    {"synthetic_fixing_revision": "rates2", "rate": ending_rate}
                )
    if command.restatement_sequence > 1:
        wire.update(revision="normalization2", source_as_of_cut=source_cut_day + "T02:00:00Z")
    original["retrieval_wires"] = [{"request_wire": snapshot.paging_metadata, "response_wire": response}]
    members = []
    for ref in references:
        row = deepcopy(original)
        row.update(
            {
                "member_id": ref["portfolio_id"],
                "input_fingerprint": ref["input_fingerprint"],
                "calculation_hash": ref["calculation_hash"],
                "portfolio_reference_currency": source_money_currency if ref["portfolio_id"] == "A" else "USD",
            }
        )
        if ref["portfolio_id"] != "A":
            row.update(
                {"source_money_currency": "USD", "conversion_kind": "IDENTITY", "fixings": [], "retrieval_wires": []}
            )
        members.append(row)
    wire["members"] = members
    wire["method"]["revision"] = normalization_method_revision
    wire["method_binding"].update(revision=normalization_method_revision, digest=authority_digest(wire["method"]))
    if normalization_fault == "missing-member":
        wire["members"].pop()
    elif normalization_fault == "zero-rate":
        wire["members"][0]["fixings"][-1]["rate"] = "0"
    elif normalization_fault == "reversed-direction":
        wire["members"][0]["fixings"][-1]["quote_direction"] = "SOURCE_UNITS_PER_REPORTING_UNIT"
    elif normalization_fault == "wrong-native":
        wire["composite_native_currency"] = "GBP" if composite_native_currency != "GBP" else "EUR"
    digest = authority_digest(wire)
    binding = EvidenceBinding(
        product_name=wire["product_name"], product_version="v1", revision=wire["revision"], digest=digest
    )

    def verify(request):
        assert request.source_digest == digest and request.resolution.tenant_id == tenant_id
        return synthetic_fx_verification(request)

    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_source_resolver",
        lambda: SimpleNamespace(resolve=lambda request: wire),
    )
    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=verify),
    )
    return command.model_copy(update={"currency_normalization_binding": binding})


@pytest.mark.parametrize(
    "fault, code",
    [
        ("missing-member", "COMPOSITE_FX_SOURCE_SCOPE_MISMATCH"),
        ("zero-rate", "COMPOSITE_FX_SOURCE_WIRE_REFUSED"),
        ("reversed-direction", "COMPOSITE_FX_SOURCE_WIRE_REFUSED"),
    ],
)
def test_registered_fx_source_refusal_retains_admitted_eligible_population(monkeypatch, fault, code):
    run_registered_fx_money_control(
        monkeypatch, normalize=True, eod_flow="0", normalization_fault=fault, expected_fx_refusal=code
    )


def test_registered_fx_normalization_links_adjacent_periods_without_resetting_inception(
    monkeypatch, mismatch=None, native_currency="USD"
):
    from fractions import Fraction

    products = source_products(composite_id="COMPOSITE_" + uuid4().hex)
    captured = {}
    for sequence, day, rates, figures in [
        (1, "2026-01-05", ("1.3", "1.4"), {"A": ("100", "102"), "B": ("200", "210"), "C": ("300", "294")}),
        (2, "2026-01-06", ("1.4", "1.42"), {"A": ("102", "103"), "B": ("210", "211"), "C": ("294", "295")}),
    ]:

        def capture(command, wire, receipt, periods):
            captured[day] = {"command": command, "wire": wire, "receipt": receipt, "periods": periods}

        with monkeypatch.context() as scope:
            period_products = deepcopy(products)
            if native_currency != "USD":
                period_products[0]["reporting_currency"] = native_currency
                period_products[0]["content_hash"] = source_digest(period_products[0])
            if mismatch == "native-regime":
                period_products[0]["reporting_currency"] = "EUR" if sequence == 1 else "GBP"
                period_products[0]["content_hash"] = source_digest(period_products[0])
            if mismatch == "policy" and sequence == 2:
                period_products[0]["eligibility_policy_version"] = "policy.v2"
                period_products[1]["policy_version"] = "policy.v2"
                period_products[1]["content_hash"] = source_digest(period_products[1])
                period_products[2]["policy_version"] = "policy.v2"
                period_products[2]["membership_content_hash"] = period_products[1]["content_hash"]
                for product in (period_products[0], period_products[2]):
                    product["content_hash"] = source_digest(product)
            run_registered_fx_money_control(
                scope,
                normalize=True,
                eod_flow="0",
                capture=capture,
                products=period_products,
                beginning_rate=rates[0],
                ending_rate=rates[1],
                performance_day=day,
                native_figures=figures,
                restatement_sequence=sequence,
                normalization_method_revision="method2" if mismatch == "fx-method" and sequence == 2 else "method1",
                source_money_currency="GBP" if mismatch == "member-regime" and sequence == 2 else "EUR",
            )
    for value in captured.values():
        native = value["receipt"]["members"][0]["source_evidence"]["native_evidence"]
        assert native["calculation_request"]["portfolio"]["performance_start_date"] == "2026-01-01"
        assert native["source_assets"]["portfolio_currency"] == value["wire"]["members"][0]["source_money_currency"]

    def verify(request):
        assert any(request.source_digest == authority_digest(row["wire"]) for row in captured.values())
        return synthetic_fx_verification(request)

    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=verify),
    )
    headers = {"X-Tenant-Id": "tenant-a", "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
    with TestClient(app, headers=headers) as client:
        identities = [str(row["command"].materialization_id) for row in captured.values()]
        payload = {
            **composite_request(captured["2026-01-05"]["command"]),
            "period_end": "2026-01-06",
            "materialization_ids": identities,
        }
        response = client.post("/performance/composites/twr", json=payload)
        if mismatch is not None:
            assert response.status_code == 422, response.text
            assert response.json()["error_code"] == (
                "COMPOSITE_VECTOR_CURRENCY_REGIME_UNAVAILABLE"
                if mismatch in ("native-regime", "member-regime")
                else "COMPOSITE_VECTOR_METHOD_MISMATCH"
            )
            assert "cumulative_return" not in response.json()
            for value in captured.values():
                retained = client.get(f"/performance/composites/materializations/{value['command'].materialization_id}")
                assert retained.status_code == 200 and retained.json() == value["receipt"], retained.text
            return
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["periods"]) == 2
        independent = [Fraction(2, 75), Fraction(91, 10780)]
        for period, expected in zip(result["periods"], independent, strict=True):
            assert abs(
                Decimal(str(period["return_value"])) - Decimal(expected.numerator) / expected.denominator
            ) <= Decimal("1e-12")
        linked = (1 + independent[0]) * (1 + independent[1]) - 1
        assert linked == Fraction(53, 1500)
        assert abs(Decimal(str(result["cumulative_return"])) - Decimal(53) / 1500) <= Decimal("1e-12")
        assert Decimal(str(result["periods"][0]["beginning_market_value"])) == Decimal("630")
        assert Decimal(str(result["periods"][0]["ending_market_value"])) == Decimal("646.8")
        assert Decimal(str(result["periods"][1]["beginning_market_value"])) == Decimal("646.8")
        assert Decimal(str(result["periods"][1]["ending_market_value"])) == Decimal("652.26")
        assert [window["materialization_id"] for window in result["selection_manifest"]["windows"]] == identities
        missing = client.post("/performance/composites/twr", json={**payload, "materialization_ids": identities[:1]})
        assert missing.status_code == 409 and "REQUIRED_PERIOD_UNAVAILABLE" in missing.text, missing.text
        assert "cumulative_return" not in missing.json()
        reversed_windows = client.post(
            "/performance/composites/twr", json={**payload, "materialization_ids": list(reversed(identities))}
        )
        assert reversed_windows.status_code == 422 and "COMPOSITE_VECTOR_WINDOW_MISMATCH" in reversed_windows.text
        assert "cumulative_return" not in reversed_windows.json()
        for value in captured.values():
            retained = client.get(f"/performance/composites/materializations/{value['command'].materialization_id}")
            assert retained.status_code == 200 and retained.json() == value["receipt"], retained.text


def test_registered_fx_normalization_links_native_eur_windows_in_usd_without_resetting_history(monkeypatch):
    test_registered_fx_normalization_links_adjacent_periods_without_resetting_inception(
        monkeypatch, native_currency="EUR"
    )


@pytest.mark.parametrize("mismatch", ["fx-method", "policy", "native-regime", "member-regime"])
def test_registered_fx_normalization_refuses_independently_admitted_incompatible_windows(monkeypatch, mismatch):
    test_registered_fx_normalization_links_adjacent_periods_without_resetting_inception(monkeypatch, mismatch)


def test_registered_fx_normalization_keeps_positive_tenant_populations_separate(monkeypatch):
    composite_id, shared_id = "COMPOSITE_" + uuid4().hex, uuid4()
    captured = {}
    for tenant_id, rate in [("tenant-a", "1.4"), ("tenant-b", "1.42")]:

        def capture(command, wire, receipt, periods):
            captured[tenant_id] = {"command": command, "wire": wire, "receipt": receipt, "periods": periods}

        with monkeypatch.context() as scope:
            run_registered_fx_money_control(
                scope,
                normalize=True,
                eod_flow="10",
                capture=capture,
                products=source_products(tenant_id=tenant_id, composite_id=composite_id),
                ending_rate=rate,
                materialization_id=shared_id,
            )
    assert captured["tenant-a"]["command"].materialization_id == captured["tenant-b"]["command"].materialization_id
    assert captured["tenant-a"]["wire"] != captured["tenant-b"]["wire"]
    assert captured["tenant-a"]["periods"] != captured["tenant-b"]["periods"]

    def verify(request):
        expected = captured[request.resolution.tenant_id]
        assert request.source_digest == authority_digest(expected["wire"])
        return synthetic_fx_verification(request)

    def no_refetch(request):
        raise AssertionError("Each tenant must reconstruct its own retained normalization custody")

    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_source_resolver",
        lambda: SimpleNamespace(resolve=no_refetch),
    )
    monkeypatch.setattr(
        "app.ports.composite_currency_normalization.composite_fx_receipt_verifier",
        lambda: SimpleNamespace(verify=verify),
    )
    with TestClient(app) as client:
        for tenant_id, expected in captured.items():
            headers = {"X-Tenant-Id": tenant_id, "X-Actor-Id": "operator", "X-Role": "DPM_COMPOSITE_CONSUMER"}
            receipt = client.get(f"/performance/composites/materializations/{shared_id}", headers=headers)
            assert receipt.status_code == 200 and receipt.json() == expected["receipt"], receipt.text
            assert receipt.json()["ready_count"] == receipt.json()["expected_count"] == 3
            reported = client.post(
                "/performance/composites/twr",
                headers=headers,
                json=composite_request(expected["command"], sequence=1),
            )
            assert reported.status_code == 200 and reported.json()["periods"] == expected["periods"], reported.text


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
