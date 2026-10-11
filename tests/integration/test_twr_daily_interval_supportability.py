"""Native daily-interval sufficiency; controlled Core transport is not live QA."""

from copy import deepcopy
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource
from app.core.config import get_settings
from app.services.execution_registry import execution_registry
from main import app
from scripts.durable_schema_apply import apply_durable_schema
from tests.composite_materialization_helpers import command_for
from tests.conftest import drain_lineage_queue


@pytest.fixture
def daily_source():
    return {
        "portfolio_id": "A",
        "portfolio_open_date": "2026-01-05",
        "portfolio_currency": "USD",
        "reporting_currency": "USD",
        "observations": [
            {
                "valuation_date": "2026-01-05",
                "beginning_market_value": "100",
                "ending_market_value": "110",
                "cash_flows": [],
            }
        ],
    }


@pytest.fixture
def daily_client(monkeypatch, tmp_path, daily_source):
    database_url = "sqlite:///" + (tmp_path / "daily-interval.db").as_posix()
    monkeypatch.setattr(get_settings(), "LINEAGE_METADATA_DATABASE_URL", database_url)
    monkeypatch.setattr(get_settings(), "LINEAGE_STORAGE_PATH", str(tmp_path / "lineage"))
    assert apply_durable_schema(database_url=database_url).status == "passed"

    async def source(self, **kwargs):  # noqa: ARG001
        payload = deepcopy(daily_source)
        if "page" in payload:
            page = 1 if kwargs.get("page_token") else 0
            payload["observations"] = [payload["observations"][page]]
            if page:
                payload.pop("page")
        return 200, payload

    async def reference(self, **kwargs):  # noqa: ARG001
        return 200, {"portfolio_open_date": "2026-01-05", "portfolio_currency": "USD"}

    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_portfolio_analytics_timeseries", source
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_portfolio_analytics_reference", reference
    )
    with TestClient(app, headers={"X-Tenant-Id": "tenant-a"}) as client:
        yield client


def request_for(endpoint):
    payload = {
        "portfolio_id": "A",
        "report_start_date": "2026-01-05",
        "report_end_date": "2026-01-05",
        "input_mode": "stateful",
        "stateful_input": {},
        "metric_basis": "NET",
        "report_ccy": "USD",
        "precision_mode": "DECIMAL_STRICT",
        "rounding_precision": 12,
        "annualization": {"enabled": False},
    }
    payload["analyses" if endpoint.endswith("/twr") else "periods"] = [{"period": "EXPLICIT", "frequencies": ["daily"]}]
    if not endpoint.endswith("/twr"):
        payload.pop("metric_basis")
    return payload


@pytest.mark.parametrize("endpoint", ["/performance/twr", "/performance/workspace-summary"])
@pytest.mark.parametrize("page_overlap", [False, True])
def test_complete_single_daily_interval_is_ready(daily_client, daily_source, endpoint, page_overlap):
    if page_overlap:
        daily_source["observations"] *= 2
        daily_source["page"] = {"next_page_token": "page-2"}
    response = daily_client.post(endpoint, json=request_for(endpoint))
    assert response.status_code == 200, response.text
    body = response.json()
    support = body["calculation_supportability"]
    assert support["history_coverage"]["status"] == "complete"
    assert support["input_row_count"] == 1
    assert support["source_quality_evidence"]["quality_state"] == "clean"
    assert support["state"] == "ready"
    # Independent economic oracle: one complete BOD/EOD interval, no flows/fees.
    expected_percent = (Decimal("110") - Decimal("100")) / Decimal("100") * 100
    block = body["results_by_period"]["EXPLICIT"]
    portfolio = block["portfolio"] if endpoint.endswith("/twr") else block["portfolio_twr"]["net"]
    assert abs(Decimal(str(portfolio["summary"]["period_return"]["base"])) - expected_percent) < Decimal("1e-12")


def test_native_single_day_result_is_admitted_by_retained_member_source(daily_client):
    response = daily_client.post("/performance/twr", json=request_for("/performance/twr"))
    assert response.status_code == 200, response.text
    body = response.json()
    drain_lineage_queue()
    retained = daily_client.get(f"/performance/twr/results/{body['calculation_id']}")
    assert retained.status_code == 200, retained.text
    outcome = retained_outcome(body)
    assert outcome.state == "READY", outcome.reason_code
    assert retained.json()["calculation_supportability"]["state"] == "ready"
    assert abs(outcome.fact.return_value - Decimal("0.10")) < Decimal("1e-12")
    assert outcome.fact.beginning_market_value == Decimal("100")
    assert outcome.fact.ending_market_value == Decimal("110")
    assert outcome.source_evidence.core_snapshots[0].response_fingerprint


def retained_outcome(body):
    reference = {
        "portfolio_id": "A",
        "calculation_id": body["calculation_id"],
        "input_fingerprint": body["meta"]["input_fingerprint"],
        "calculation_hash": body["meta"]["calculation_hash"],
    }
    command = command_for(member_calculations=[reference])
    execution = execution_registry.get_execution_for_tenant(UUID(body["calculation_id"]), tenant_id="tenant-a")
    assert execution is not None and execution.upstream_snapshots
    return RetainedCompositeMemberResultSource().read_member(
        command,
        command.member_calculations[0],
        tenant_id="tenant-a",
        membership_snapshot_id=command.membership_content_hash,
        request_headers={"x-tenant-id": "tenant-a"},
    )


@pytest.mark.parametrize(
    "fault",
    ["empty", "unvalued", "nonfinite", "conflict", "page-conflict", "unsupported-flow", "zero-capital", "missing-day"],
)
def test_single_daily_interval_does_not_admit_adverse_source(daily_client, daily_source, fault):
    observation = daily_source["observations"][0]
    payload = request_for("/performance/twr")
    if fault == "empty":
        daily_source["observations"] = []
    elif fault == "unvalued":
        observation.pop("beginning_market_value")
    elif fault == "nonfinite":
        observation["ending_market_value"] = "Infinity"
    elif fault in {"conflict", "page-conflict"}:
        daily_source["observations"].append({**observation, "ending_market_value": "111"})
        if fault == "page-conflict":
            daily_source["page"] = {"next_page_token": "page-2"}
    elif fault == "unsupported-flow":
        observation["cash_flows"] = [{"amount": "1", "timing": "eod", "cash_flow_type": "UNSUPPORTED"}]
    elif fault == "zero-capital":
        observation["beginning_market_value"] = "0"
    else:
        payload["report_end_date"] = "2026-01-06"
    response = daily_client.post("/performance/twr", json=payload)
    if fault in {"empty", "unvalued", "nonfinite", "conflict", "page-conflict"}:
        assert response.status_code == 422, response.text
        return
    assert response.status_code == 200, response.text
    body = response.json()
    drain_lineage_queue()
    outcome = retained_outcome(body)
    assert outcome.state == "BLOCKED", (fault, outcome)
    assert outcome.fact is None and outcome.source_evidence is None
