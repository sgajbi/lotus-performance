import math

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _linked_percentage(*returns_pct: float) -> float:
    linked = math.prod(1 + value / 100 for value in returns_pct) - 1
    return linked * 100


def test_twr_response_attributes_tie_to_deterministic_stateless_inputs(client):
    payload = {
        "input_mode": "stateless",
        "portfolio_id": "ATTR_TWR_001",
        "performance_start_date": "2026-01-01",
        "report_start_date": "2026-01-01",
        "report_end_date": "2026-01-03",
        "metric_basis": "NET",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "stateless_input": {
            "valuation_points": [
                {"perf_date": "2026-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                {"perf_date": "2026-01-02", "begin_mv": 1010.0, "bod_cf": 100.0, "end_mv": 1121.0},
                {
                    "perf_date": "2026-01-03",
                    "begin_mv": 1121.0,
                    "eod_cf": -50.0,
                    "mgmt_fees": -10.0,
                    "end_mv": 1071.0,
                },
            ]
        },
        "annualization": {"enabled": False, "basis": "ACT/365"},
    }

    response = client.post("/performance/twr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "calculation_id",
        "portfolio_id",
        "input_mode",
        "results_by_period",
        "calculation_supportability",
        "meta",
        "diagnostics",
        "audit",
    }
    assert body["portfolio_id"] == "ATTR_TWR_001"
    assert body["input_mode"] == "stateless"
    assert body["calculation_id"] == body["meta"]["calculation_id"]
    assert body["meta"]["engine_version"]
    assert body["meta"]["precision_mode"] == "FLOAT64"
    assert body["meta"]["annualization"] == {"enabled": False, "basis": "ACT/365"}
    assert body["meta"]["calendar"] == {"type": "BUSINESS", "trading_calendar": "NYSE"}
    assert body["meta"]["periods"] == {
        "requested": ["EXPLICIT"],
        "master_start": "2026-01-01",
        "master_end": "2026-01-03",
    }
    assert body["meta"]["input_fingerprint"].startswith("sha256:")
    assert body["meta"]["calculation_hash"].startswith("sha256:")
    assert body["audit"]["counts"] == {"input_rows": 3}
    assert body["calculation_supportability"] == {
        "state": "ready",
        "reason": "calculation_complete",
        "freshness_bucket": "current",
        "input_row_count": 3,
        "resolved_period_count": 1,
        "benchmark_row_count": 0,
    }
    assert body["audit"]["residual_applied_bp"] == 0.0
    assert body["diagnostics"]["effective_period_start"] == "2026-01-01"
    assert body["diagnostics"]["nip_days"] == 0
    assert body["diagnostics"]["reset_days"] == 0
    assert body["diagnostics"]["valid_days_since_last_reset"] == 3
    assert body["diagnostics"]["notes"] == []

    explicit = body["results_by_period"]["EXPLICIT"]
    assert set(explicit) == {"portfolio"}
    portfolio = explicit["portfolio"]
    assert set(portfolio) == {"summary", "breakdowns"}
    assert set(portfolio["summary"]) == {"period_return", "cumulative_return"}
    daily = portfolio["breakdowns"]["daily"]
    assert [item["period"] for item in daily] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert [item["period_start"] for item in daily] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert [item["period_end"] for item in daily] == ["2026-01-01", "2026-01-02", "2026-01-03"]

    day1 = 1.0
    day2 = ((1121.0 - 1010.0 - 100.0) / (1010.0 + 100.0)) * 100
    day3 = -10.0 / 1121.0 * 100
    cumulative_day2 = _linked_percentage(day1, day2)
    cumulative_day3 = _linked_percentage(day1, day2, day3)
    expected_daily = [
        (day1, day1),
        (day2, cumulative_day2),
        (day3, cumulative_day3),
    ]
    for item, (period_return, cumulative_return) in zip(daily, expected_daily):
        assert item["period_return"]["base"] == pytest.approx(period_return)
        assert item["period_return"]["local"] == pytest.approx(period_return)
        assert item["period_return"]["fx"] == 0.0
        assert item["cumulative_return"]["base"] == pytest.approx(cumulative_return)
        assert item["cumulative_return"]["local"] == pytest.approx(cumulative_return)
        assert item["cumulative_return"]["fx"] == 0.0
        assert "annualized_return" not in item
        assert "daily_data" not in item

    assert portfolio["summary"]["period_return"]["base"] == pytest.approx(cumulative_day3)
    assert portfolio["summary"]["cumulative_return"]["base"] == pytest.approx(cumulative_day3)


def test_mwr_response_attributes_tie_to_deterministic_stateless_inputs(client):
    payload = {
        "input_mode": "stateless",
        "portfolio_id": "ATTR_MWR_001",
        "as_of": "2026-01-03",
        "mwr_method": "DIETZ",
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "stateless_input": {
            "begin_mv": 1000.0,
            "end_mv": 1120.0,
            "cash_flows": [
                {"amount": 100.0, "date": "2026-01-02"},
                {"amount": -20.0, "date": "2026-01-03"},
            ],
        },
    }

    response = client.post("/performance/mwr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "calculation_id",
        "portfolio_id",
        "input_mode",
        "money_weighted_return",
        "method",
        "cashflows_used",
        "start_date",
        "end_date",
        "notes",
        "meta",
        "diagnostics",
        "audit",
    }
    assert body["portfolio_id"] == "ATTR_MWR_001"
    assert body["input_mode"] == "stateless"
    assert body["method"] == "DIETZ"
    assert body["start_date"] == "2026-01-02"
    assert body["end_date"] == "2026-01-03"
    assert body["notes"] == []
    assert body["cashflows_used"] == [
        {"amount": 100.0, "date": "2026-01-02"},
        {"amount": -20.0, "date": "2026-01-03"},
    ]
    expected_mwr = ((1120.0 - 1000.0 - 80.0) / (1000.0 + 80.0 / 2.0)) * 100
    assert body["money_weighted_return"] == pytest.approx(expected_mwr)
    assert "mwr_annualized" not in body
    assert "convergence" not in body
    assert body["calculation_id"] == body["meta"]["calculation_id"]
    assert body["meta"]["engine_version"]
    assert body["meta"]["precision_mode"] == "FLOAT64"
    assert body["meta"]["annualization"] == {"enabled": False, "basis": "ACT/365"}
    assert body["meta"]["calendar"] == {"type": "BUSINESS", "trading_calendar": "NYSE"}
    assert body["meta"]["periods"] == {"type": "EXPLICIT", "start": "2026-01-02", "end": "2026-01-03"}
    assert body["meta"]["input_fingerprint"].startswith("sha256:")
    assert body["meta"]["calculation_hash"].startswith("sha256:")
    assert body["diagnostics"] == {
        "nip_days": 0,
        "reset_days": 0,
        "effective_period_start": "2026-01-02",
        "notes": [],
    }
    assert body["audit"] == {"counts": {"cashflows": 2}}


def test_mwr_emit_cashflows_used_false_omits_cashflow_echo(client):
    payload = {
        "input_mode": "stateless",
        "portfolio_id": "ATTR_MWR_002",
        "as_of": "2026-01-03",
        "mwr_method": "DIETZ",
        "emit_cashflows_used": False,
        "stateless_input": {
            "begin_mv": 1000.0,
            "end_mv": 1120.0,
            "cash_flows": [{"amount": 100.0, "date": "2026-01-02"}],
        },
    }

    response = client.post("/performance/mwr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "cashflows_used" not in body
    assert body["audit"] == {"counts": {"cashflows": 1}}


def test_workspace_summary_does_not_drift_from_direct_twr_and_mwr_endpoints(client):
    valuation_points = [
        {"perf_date": "2026-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
        {"perf_date": "2026-01-02", "begin_mv": 1010.0, "bod_cf": 100.0, "end_mv": 1121.0},
        {
            "perf_date": "2026-01-03",
            "begin_mv": 1121.0,
            "eod_cf": -50.0,
            "mgmt_fees": -10.0,
            "end_mv": 1071.0,
        },
    ]
    direct_twr_payload = {
        "input_mode": "stateless",
        "portfolio_id": "ATTR_DRIFT_GUARD_001",
        "performance_start_date": "2026-01-01",
        "report_start_date": "2026-01-01",
        "report_end_date": "2026-01-03",
        "metric_basis": "NET",
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "stateless_input": {"valuation_points": valuation_points},
        "annualization": {"enabled": False, "basis": "ACT/365"},
    }
    direct_mwr_payload = {
        "input_mode": "stateless",
        "portfolio_id": "ATTR_DRIFT_GUARD_001",
        "as_of": "2026-01-03",
        "start_date": "2026-01-01",
        "mwr_method": "DIETZ",
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "stateless_input": {
            "begin_mv": 1000.0,
            "end_mv": 1071.0,
            "cash_flows": [
                {"amount": 100.0, "date": "2026-01-02"},
                {"amount": -50.0, "date": "2026-01-03"},
            ],
        },
    }
    workspace_payload = {
        "input_mode": "stateless",
        "portfolio_id": "ATTR_DRIFT_GUARD_001",
        "performance_start_date": "2026-01-01",
        "report_start_date": "2026-01-01",
        "report_end_date": "2026-01-03",
        "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "mwr_method": "DIETZ",
        "annualization": {"enabled": False, "basis": "ACT/365"},
        "stateless_input": {"valuation_points": valuation_points},
    }

    direct_twr = client.post("/performance/twr", json=direct_twr_payload).json()
    direct_mwr = client.post("/performance/mwr", json=direct_mwr_payload).json()
    workspace = client.post("/performance/workspace-summary", json=workspace_payload).json()

    direct_twr_period = direct_twr["results_by_period"]["EXPLICIT"]["portfolio"]
    workspace_period = workspace["results_by_period"]["EXPLICIT"]
    workspace_twr = workspace_period["portfolio_twr"]["net"]
    workspace_mwr = workspace_period["money_weighted_return"]

    assert workspace_twr["summary"]["period_return"]["base"] == pytest.approx(
        direct_twr_period["summary"]["period_return"]["base"]
    )
    assert workspace_twr["summary"]["cumulative_return"]["base"] == pytest.approx(
        direct_twr_period["summary"]["cumulative_return"]["base"]
    )
    assert [item["period"] for item in workspace_twr["breakdowns"]["daily"]] == [
        item["period"] for item in direct_twr_period["breakdowns"]["daily"]
    ]
    for workspace_item, direct_item in zip(
        workspace_twr["breakdowns"]["daily"],
        direct_twr_period["breakdowns"]["daily"],
    ):
        assert workspace_item["period_return"]["base"] == pytest.approx(direct_item["period_return"]["base"])
        assert workspace_item["cumulative_return"]["base"] == pytest.approx(direct_item["cumulative_return"]["base"])

    assert workspace_mwr["method"] == direct_mwr["method"]
    assert workspace_mwr["period_return"] == pytest.approx(direct_mwr["money_weighted_return"])
    assert workspace_mwr["cumulative_return"] == pytest.approx(direct_mwr["money_weighted_return"])
    assert workspace_mwr["start_date"] == direct_mwr["start_date"]
    assert workspace_mwr["end_date"] == direct_mwr["end_date"]

    economics = workspace_mwr["economics"]
    assert economics["begin_market_value"] == 1000.0
    assert economics["end_market_value"] == 1071.0
    assert economics["beginning_cash_flow"] == 100.0
    assert economics["ending_cash_flow"] == -50.0
    assert economics["fees"] == -10.0
    assert economics["net_cash_flow"] == 50.0
    assert economics["flow_adjusted_end_market_value"] == 1021.0
