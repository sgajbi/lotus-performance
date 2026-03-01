# tests/integration/test_performance_api.py
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from engine.exceptions import EngineCalculationError, InvalidEngineInputError
from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_twr_reports_reset_events_when_requested(client):
    """
    Tests that when a reset occurs and the policy is enabled,
    the reset_events list is correctly populated in the response.
    """
    # This payload is based on the 'long_flip_scenario' which triggers an NCTRL_1 reset
    payload = {
        "portfolio_id": "RESET_SCENARIO_TEST",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "metric_basis": "GROSS",
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
            {"day": 2, "perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
            {"day": 3, "perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
            {"day": 4, "perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
        ],
        "reset_policy": {"emit": True},
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_results = data["results_by_period"]["ITD"]

    assert "reset_events" in itd_results
    assert itd_results["reset_events"] is not None
    assert len(itd_results["reset_events"]) == 1

    reset_event = itd_results["reset_events"][0]
    assert reset_event["date"] == "2025-01-02"
    assert "NCTRL_1" in reset_event["reason"]


def test_calculate_twr_endpoint_with_annualization(client):
    """Tests that a request with annualization enabled correctly returns annualized figures."""
    payload = {
        "portfolio_id": "ANNUALIZATION_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-03-31",
        "analyses": [{"period": "QTD", "frequencies": ["quarterly"]}],
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"day": 60, "perf_date": "2025-03-31", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "annualization": {"enabled": True, "basis": "ACT/365"},
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    summary = data["results_by_period"]["QTD"]["breakdowns"]["quarterly"][0]["summary"]

    assert "annualized_return_pct" in summary
    assert summary["period_return_pct"] == pytest.approx(2.01)
    # 90 days in Q1 2025. Expected: (1.0201 ** (365 / 90)) - 1 = 8.40545...%
    assert summary["annualized_return_pct"] == pytest.approx(8.40545, abs=1e-5)


def test_calculate_twr_endpoint_legacy_path_and_diagnostics(client):
    """Tests the /performance/twr endpoint using the new 'analyses' structure and verifies the shared response footer."""
    payload = {
        "portfolio_id": "PORT_STANDARD_GROWTH",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily", "monthly"]}],
        "calculation_id": str(uuid4()),
        "rounding_precision": 6,
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 100000.0, "end_mv": 101000.0},
            {"day": 2, "perf_date": "2025-01-02", "begin_mv": 101000.0, "end_mv": 102010.0},
            {"day": 3, "perf_date": "2025-01-03", "begin_mv": 102010.0, "end_mv": 100989.9},
            {"day": 4, "perf_date": "2025-01-04", "begin_mv": 100989.9, "bod_cf": 25000.0, "end_mv": 127249.29},
            {"day": 5, "perf_date": "2025-01-05", "begin_mv": 127249.29, "end_mv": 125976.7971},
        ],
    }

    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200

    response_data = response.json()
    assert "calculation_id" in response_data
    assert "results_by_period" in response_data
    assert "YTD" in response_data["results_by_period"]
    ytd_results = response_data["results_by_period"]["YTD"]
    assert "breakdowns" in ytd_results

    assert "meta" in response_data
    assert response_data["meta"]["engine_version"] is not None
    assert "diagnostics" in response_data
    assert response_data["diagnostics"]["nip_days"] == 0
    assert "audit" in response_data
    assert response_data["audit"]["counts"]["input_rows"] == 5


def test_calculate_twr_endpoint_multi_period(client):
    """Tests a multi-period request for MTD and YTD."""
    payload = {
        "portfolio_id": "MULTI_PERIOD_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-02-15",
        "analyses": [
            {"period": "MTD", "frequencies": ["monthly"]},
            {"period": "YTD", "frequencies": ["monthly"]},
        ],
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-15", "begin_mv": 1000.0, "end_mv": 1010.0},  # +1.0%
            {"day": 2, "perf_date": "2025-02-10", "begin_mv": 1010.0, "end_mv": 1030.2},  # +2.0%
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "results_by_period" in data
    results = data["results_by_period"]
    assert "MTD" in results
    assert "YTD" in results

    mtd_monthly_breakdown = results["MTD"]["breakdowns"]["monthly"]
    assert len(mtd_monthly_breakdown) == 1
    mtd_return = mtd_monthly_breakdown[0]["summary"]["period_return_pct"]
    assert mtd_return == pytest.approx(2.0)

    ytd_monthly_breakdown = results["YTD"]["breakdowns"]["monthly"]
    assert len(ytd_monthly_breakdown) == 2
    jan_return = ytd_monthly_breakdown[0]["summary"]["period_return_pct"]
    feb_return = ytd_monthly_breakdown[1]["summary"]["period_return_pct"]

    assert jan_return == pytest.approx(1.0)
    assert feb_return == pytest.approx(2.0)

    compounded_ytd_return = ((1 + jan_return / 100) * (1 + feb_return / 100) - 1) * 100
    assert compounded_ytd_return == pytest.approx(3.02)


def test_calculate_twr_endpoint_multi_currency(client):
    """Tests an end-to-end multi-currency TWR request."""
    payload = {
        "portfolio_id": "MULTI_CCY_API_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "GROSS",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0},
            {"day": 2, "perf_date": "2025-01-02", "begin_mv": 102.0, "end_mv": 103.02},
        ],
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.05},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.08},
                {"date": "2025-01-02", "ccy": "EUR", "rate": 1.07},
            ]
        },
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_result = data["results_by_period"]["ITD"]

    assert "portfolio_return" in itd_result
    assert itd_result["portfolio_return"]["local"] == pytest.approx(3.02)
    assert itd_result["portfolio_return"]["fx"] == pytest.approx(1.90476, abs=1e-5)
    assert itd_result["portfolio_return"]["base"] == pytest.approx(4.98228, abs=1e-5)
    assert data["meta"]["report_ccy"] == "USD"


def test_calculate_twr_endpoint_with_data_policy(client):
    """Tests that a request with data_policy overrides and flagging works end-to-end."""
    payload = {
        "portfolio_id": "POLICY_TEST",
        "performance_start_date": "2024-12-27",
        "metric_basis": "NET",
        "report_end_date": "2025-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"day": 1, "perf_date": "2024-12-28", "begin_mv": 1000.0, "end_mv": 1001.0},
            {"day": 2, "perf_date": "2024-12-29", "begin_mv": 1001.0, "end_mv": 1002.0},
            {"day": 3, "perf_date": "2024-12-30", "begin_mv": 1002.0, "end_mv": 1003.0},
            {"day": 4, "perf_date": "2024-12-31", "begin_mv": 1003.0, "end_mv": 1004.0},
            {"day": 5, "perf_date": "2025-01-01", "begin_mv": 1004.0, "end_mv": 1010.0},
            {"day": 6, "perf_date": "2025-01-02", "begin_mv": 1005.0, "end_mv": 2000.0},
            {"day": 7, "perf_date": "2025-01-03", "begin_mv": 2000.0, "end_mv": 2020.0},
        ],
        "data_policy": {
            "overrides": {"market_values": [{"perf_date": "2025-01-01", "end_mv": 1005.0}]},
            "ignore_days": [{"entity_type": "PORTFOLIO", "entity_id": "POLICY_TEST", "dates": ["2025-01-03"]}],
            "outliers": {"enabled": True, "action": "FLAG", "params": {"mad_k": 3.0}},
        },
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_result = data["results_by_period"]["ITD"]

    daily_breakdown = itd_result["breakdowns"]["daily"]
    assert daily_breakdown[4]["summary"]["period_return_pct"] == pytest.approx(0.099602, abs=1e-6)
    assert daily_breakdown[6]["summary"]["period_return_pct"] == 0.0

    diags = data["diagnostics"]
    assert diags["policy"]["overrides"]["applied_mv_count"] == 1
    assert diags["policy"]["ignored_days_count"] == 1
    assert diags["policy"]["outliers"]["flagged_rows"] == 1


def test_twr_respects_include_timeseries_flag(client):
    """Tests that the include_timeseries flag correctly includes or excludes the daily_data block."""
    base_payload = {
        "portfolio_id": "TIMESERIES_FLAG_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }

    # Case 1: Flag is true
    payload_with = base_payload.copy()
    payload_with["output"] = {"include_timeseries": True}
    response_with = client.post("/performance/twr", json=payload_with)
    assert response_with.status_code == 200
    daily_breakdown_with = response_with.json()["results_by_period"]["YTD"]["breakdowns"]["daily"][0]
    assert "daily_data" in daily_breakdown_with
    assert daily_breakdown_with["daily_data"] is not None

    # Case 2: Flag is false
    payload_without = base_payload.copy()
    payload_without["output"] = {"include_timeseries": False}
    response_without = client.post("/performance/twr", json=payload_without)
    assert response_without.status_code == 200
    daily_breakdown_without = response_without.json()["results_by_period"]["YTD"]["breakdowns"]["daily"][0]
    assert "daily_data" not in daily_breakdown_without


def test_twr_response_includes_portfolio_return_summary(client):
    """Tests that the top-level portfolio_return object is present for single-currency requests."""
    payload = {
        "portfolio_id": "PORTFOLIO_RETURN_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"day": 2, "perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    ytd_result = data["results_by_period"]["YTD"]

    assert "portfolio_return" in ytd_result
    assert ytd_result["portfolio_return"]["base"] == pytest.approx(2.01)
    assert ytd_result["portfolio_return"]["fx"] == 0.0


def test_twr_reset_scenario_has_correct_summary(client):
    """
    Tests that for a period that includes a performance reset, the top-level
    portfolio_return summary uses the correct final cumulative return from the engine.
    """
    payload = {
        "portfolio_id": "TWR_STRESS_TEST_03",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-04",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "metric_basis": "GROSS",
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 500.0},
            {"day": 2, "perf_date": "2025-01-02", "begin_mv": 500.0, "end_mv": -50.0},
            {"day": 3, "perf_date": "2025-01-03", "begin_mv": -50.0, "bod_cf": 1000.0, "end_mv": 1050.0},
            {"day": 4, "perf_date": "2025-01-04", "begin_mv": 1050.0, "end_mv": 1155.0},
        ],
        "reset_policy": {"emit": True},
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    itd_result = data["results_by_period"]["ITD"]

    assert "portfolio_return" in itd_result
    assert itd_result["portfolio_return"]["base"] == pytest.approx(21.578947, abs=1e-6)


@pytest.mark.parametrize(
    "error_class, expected_status",
    [(InvalidEngineInputError, 400), (EngineCalculationError, 500), (Exception, 500)],
)
def test_calculate_twr_endpoint_error_handling(client, mocker, error_class, expected_status):
    """Tests that the TWR endpoint correctly handles engine exceptions."""
    mocker.patch("app.api.endpoints.performance.run_calculations", side_effect=error_class("Test Error"))
    payload = {
        "portfolio_id": "ERROR_TEST",
        "performance_start_date": "2023-12-31",
        "metric_basis": "NET",
        "report_end_date": "2024-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"day": 1, "perf_date": "2024-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_twr_returns_400_when_no_periods_resolve(client, mocker):
    mocker.patch("app.api.endpoints.performance.resolve_periods", return_value=[])
    payload = {
        "portfolio_id": "NO_PERIODS",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 400
    assert "No valid periods could be resolved" in response.json()["detail"]


def test_twr_returns_empty_results_when_resolved_period_has_no_data(client):
    payload = {
        "portfolio_id": "NO_PERIOD_DATA",
        "performance_start_date": "2024-01-01",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"day": 1, "perf_date": "2024-12-30", "begin_mv": 1000.0, "end_mv": 1005.0},
            {"day": 2, "perf_date": "2024-12-31", "begin_mv": 1005.0, "end_mv": 1010.0},
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    assert response.json()["results_by_period"] == {}


def test_twr_http_exception_passthrough_branch(client, mocker):
    mocker.patch(
        "app.api.endpoints.performance.resolve_periods",
        side_effect=HTTPException(status_code=418, detail="teapot"),
    )
    payload = {
        "portfolio_id": "HTTP_EXCEPTION",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 418
    assert response.json()["detail"] == "teapot"


def test_mwr_http_exception_passthrough_branch(client, mocker):
    mocker.patch(
        "app.api.endpoints.performance.calculate_money_weighted_return",
        side_effect=HTTPException(status_code=409, detail="conflict"),
    )
    payload = {
        "portfolio_id": "MWR_HTTP",
        "begin_mv": 1000.0,
        "end_mv": 1001.0,
        "cash_flows": [],
        "as_of": "2026-01-15",
    }
    response = client.post("/performance/mwr", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "conflict"
