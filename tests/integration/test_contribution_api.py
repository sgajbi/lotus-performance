# tests/integration/test_contribution_api.py
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine.exceptions import EngineCalculationError
from main import app
from tests.conftest import drain_lineage_queue


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_contribution_endpoint_happy_path_and_envelope(client, happy_path_payload):
    """Tests the /performance/contribution endpoint and verifies the shared response envelope."""
    response = client.post("/performance/contribution", json=happy_path_payload)

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["portfolio_id"] == "CONTRIB_TEST_01"
    assert "results_by_period" in response_data
    assert "ITD" in response_data["results_by_period"]


def test_contribution_endpoint_multi_period(client):
    """Tests a multi-period request for MTD and YTD contribution."""
    payload = {
        "portfolio_id": "MULTI_PERIOD_CONTRIB",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-02-15",
        "analyses": [{"period": "MTD", "frequencies": ["monthly"]}, {"period": "YTD", "frequencies": ["monthly"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [
                {"day": 1, "perf_date": "2025-01-10", "begin_mv": 1000, "end_mv": 1010},
                {"day": 2, "perf_date": "2025-02-10", "begin_mv": 1010, "end_mv": 1030.2},
            ],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "valuation_points": [
                    {"day": 1, "perf_date": "2025-01-10", "begin_mv": 1000, "end_mv": 1010},
                    {"day": 2, "perf_date": "2025-02-10", "begin_mv": 1010, "end_mv": 1030.2},
                ],
            }
        ],
    }
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "results_by_period" in data
    results = data["results_by_period"]
    assert "MTD" in results
    assert "YTD" in results


def test_contribution_endpoint_multi_currency(client):
    """Tests an end-to-end multi-currency contribution request."""
    payload = {
        "portfolio_id": "MULTI_CCY_CONTRIB_01",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "GROSS",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 105.0, "end_mv": 110.16}],
        },
        "positions_data": [
            {
                "position_id": "EUR_STOCK",
                "meta": {"currency": "EUR"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 102.0}],
            }
        ],
        "currency_mode": "BOTH",
        "report_ccy": "USD",
        "fx": {
            "rates": [
                {"date": "2024-12-31", "ccy": "EUR", "rate": 1.05},
                {"date": "2025-01-01", "ccy": "EUR", "rate": 1.08},
            ]
        },
    }
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["ITD"]
    assert data["total_contribution"] == pytest.approx(4.91429, abs=1e-5)


def test_contribution_lineage_flow(client, happy_path_payload):
    """Tests that lineage is correctly captured for a single-level contribution request."""
    payload = happy_path_payload.copy()
    payload["emit"] = {"timeseries": True}

    contrib_response = client.post("/performance/contribution", json=payload)
    assert contrib_response.status_code == 200
    calculation_id = contrib_response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200


def test_contribution_endpoint_no_smoothing(client, happy_path_payload):
    """Tests that the endpoint correctly processes a request with smoothing disabled."""
    payload = happy_path_payload.copy()
    payload["smoothing"] = {"method": "NONE"}
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200


def test_contribution_endpoint_with_timeseries(client, happy_path_payload):
    """Tests that the endpoint correctly returns time-series data when requested."""
    payload = happy_path_payload.copy()
    payload["emit"] = {"timeseries": True, "by_position_timeseries": True}
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200


def test_contribution_endpoint_hierarchy_happy_path(client, happy_path_payload):
    """Tests a hierarchical contribution request aggregates correctly."""
    payload = happy_path_payload.copy()
    payload["hierarchy"] = ["sector", "position_id"]
    payload["positions_data"].append(
        {
            "position_id": "Stock_B",
            "meta": {"sector": "Technology"},
            "valuation_points": [
                {"day": 1, "perf_date": "2025-01-01", "begin_mv": 400, "end_mv": 408},
                {"day": 2, "perf_date": "2025-01-02", "begin_mv": 408, "end_mv": 410},
            ],
        }
    )
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 200
    data = response.json()["results_by_period"]["ITD"]
    assert "summary" in data
    assert data["summary"]["portfolio_contribution"] == pytest.approx(2.95327, abs=1e-5)


def test_contribution_endpoint_error_handling(client, mocker):
    """Tests that a generic server error is raised for calculation failures."""
    mocker.patch(
        "app.api.endpoints.contribution._prepare_hierarchical_data", side_effect=EngineCalculationError("Test Error")
    )
    payload = {
        "portfolio_id": "ERROR",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1025}],
        },
        "positions_data": [],
    }
    response = client.post("/performance/contribution", json=payload)
    assert response.status_code == 500


def test_contribution_endpoint_no_resolved_periods_returns_400(client):
    payload = {
        "portfolio_id": "NO_PERIODS",
        "report_start_date": "2025-01-10",
        "report_end_date": "2025-01-05",
        "analyses": [{"period": "MTD", "frequencies": ["monthly"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-10", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [],
    }
    from app.api.endpoints import contribution as contribution_endpoint

    original_resolve_periods = contribution_endpoint.resolve_periods
    contribution_endpoint.resolve_periods = lambda periods, end_date, inception_date: []  # type: ignore[assignment]
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_endpoint.resolve_periods = original_resolve_periods  # type: ignore[assignment]

    assert response.status_code == 400
    assert "No valid periods could be resolved." in response.json()["detail"]


def test_contribution_endpoint_skips_empty_period_slice(client):
    payload = {
        "portfolio_id": "EMPTY_SLICE",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["monthly"]}],
        "portfolio_data": {
            "metric_basis": "NET",
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
        },
        "positions_data": [
            {
                "position_id": "Stock_A",
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        ],
    }
    from app.api.endpoints import contribution as contribution_endpoint

    original_prepare = contribution_endpoint._prepare_hierarchical_data
    original_daily = contribution_endpoint._calculate_daily_instrument_contributions

    def _mock_prepare(_request):
        portfolio_df = pd.DataFrame(
            [{"perf_date": "2025-01-01", "daily_ror": 0.1}],
        )
        return pd.DataFrame(), portfolio_df

    def _mock_daily(_instruments_df, _portfolio_df, _weighting_scheme, _smoothing):
        return pd.DataFrame(
            [
                {
                    "perf_date": "2024-01-01",
                    "position_id": "Stock_A",
                    "smoothed_contribution": 0.0,
                    "smoothed_local_contribution": 0.0,
                    "daily_weight": 1.0,
                }
            ]
        )

    contribution_endpoint._prepare_hierarchical_data = _mock_prepare  # type: ignore[assignment]
    contribution_endpoint._calculate_daily_instrument_contributions = _mock_daily  # type: ignore[assignment]
    try:
        response = client.post("/performance/contribution", json=payload)
    finally:
        contribution_endpoint._prepare_hierarchical_data = original_prepare  # type: ignore[assignment]
        contribution_endpoint._calculate_daily_instrument_contributions = original_daily  # type: ignore[assignment]

    assert response.status_code == 200
    assert response.json()["results_by_period"] == {}
