# tests/integration/test_mwr_api.py
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS
from core.repro import generate_canonical_hash
from main import app
from tests.conftest import drain_lineage_queue

_EXPECTED_SUPPORTABILITY_METRIC_LABELS = list(PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_calculate_mwr_endpoint_xirr_happy_path(client):
    """Tests the /performance/mwr endpoint with the XIRR method."""
    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "MWR_XIRR_TEST_01",
        "begin_mv": 100000.0,
        "end_mv": 115000.0,
        "as_of": "2025-12-31",
        "cash_flows": [
            {"amount": 10000.0, "date": "2025-03-15"},
            {"amount": -5000.0, "date": "2025-09-20"},
        ],
        "mwr_method": "XIRR",
        "annualization": {"enabled": True, "basis": "ACT/365"},
    }

    response = client.post("/performance/mwr", json=payload)

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["portfolio_id"] == "MWR_XIRR_TEST_01"
    assert response_data["input_mode"] == "stateless"
    assert response_data["method"] == "XIRR"
    assert response_data["status"] == "CALCULATED"
    assert response_data["reason_codes"] == []
    assert response_data["warnings"] == []
    assert response_data["money_weighted_return"] == pytest.approx(11.71492554, abs=1e-6)
    assert response_data["mwr_annualized"] is not None
    assert response_data["holding_period_return"] is not None
    assert response_data["is_annualized_primary"] is True
    assert response_data["convergence"]["root_count_detected"] == 1
    assert response_data["convergence"]["converged"] is True
    assert response_data["convergence"]["day_count_basis"] == "ACT/365"
    assert response_data["convergence"]["residual_npv"] == pytest.approx(0.0, abs=0.01)
    assert response_data["calculation_supportability"] == {
        "state": "ready",
        "reason": "calculation_complete",
        "freshness_bucket": "current",
        "input_row_count": 4,
        "resolved_period_count": 1,
        "benchmark_row_count": 0,
        "metric_labels": _EXPECTED_SUPPORTABILITY_METRIC_LABELS,
    }


def test_calculate_mwr_endpoint_supports_stateful_mode(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "100000",
                        "ending_market_value": "110000",
                        "cash_flows": [{"amount": "10000", "timing": "bod"}],
                    },
                    {
                        "valuation_date": "2025-01-03",
                        "beginning_market_value": "110000",
                        "ending_market_value": "111000",
                        "cash_flows": [],
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "MWR_STATEFUL_01",
        "as_of": "2025-01-03",
        "mwr_method": "DIETZ",
        "input_mode": "stateful",
        "stateful_input": {
            "window_start_date": "2025-01-01",
        },
    }

    response = client.post("/performance/mwr", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "MWR_STATEFUL_01"
    assert body["input_mode"] == "stateful"
    assert body["start_date"] == "2025-01-01"
    assert body["method"] == "DIETZ"
    assert body["audit"]["counts"]["cashflows"] == 1
    assert body["cashflows_used"] == [{"amount": 10000.0, "date": "2025-01-01"}]


def test_mwr_stateful_hashes_follow_resolved_inputs(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "100000",
                        "ending_market_value": "110000",
                        "cash_flows": [{"amount": "10000", "timing": "bod"}],
                    },
                    {
                        "valuation_date": "2025-01-03",
                        "beginning_market_value": "110000",
                        "ending_market_value": "111000",
                        "cash_flows": [],
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "MWR_STATEFUL_HASH",
        "as_of": "2025-01-03",
        "mwr_method": "DIETZ",
        "annualization": {"enabled": False},
        "input_mode": "stateful",
        "stateful_input": {
            "window_start_date": "2025-01-01",
        },
    }

    response = client.post("/performance/mwr", json=payload)

    assert response.status_code == 200
    body = response.json()
    expected_request = MoneyWeightedReturnRequest.model_validate(
        {
            "calculation_id": body["calculation_id"],
            "portfolio_id": "MWR_STATEFUL_HASH",
            "as_of": "2025-01-03",
            "start_date": "2025-01-01",
            "mwr_method": "DIETZ",
            "annualization": {"enabled": False},
            "begin_mv": 100000,
            "end_mv": 111000,
            "cash_flows": [{"amount": 10000, "date": "2025-01-01"}],
        }
    )
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash(
        expected_request,
        get_settings().APP_VERSION,
    )

    assert body["meta"]["input_fingerprint"] == expected_input_fingerprint
    assert body["meta"]["calculation_hash"] == expected_calculation_hash


def test_mwr_lineage_flow(client):
    """Tests that lineage is correctly captured for an MWR request."""
    payload = {
        "portfolio_id": "MWR_LINEAGE_01",
        "begin_mv": 5000.0,
        "end_mv": 5500.0,
        "as_of": "2025-06-30",
        "cash_flows": [{"amount": 100.0, "date": "2025-03-01"}],
        "mwr_method": "XIRR",
    }
    mwr_response = client.post("/performance/mwr", json=payload)
    assert mwr_response.status_code == 200
    calculation_id = mwr_response.json()["calculation_id"]
    assert drain_lineage_queue() >= 1

    lineage_response = client.get(f"/performance/lineage/{calculation_id}")
    assert lineage_response.status_code == 200
    lineage_data = lineage_response.json()

    assert lineage_data["calculation_type"] == "MWR"
    assert "mwr_cashflow_schedule.csv" in lineage_data["artifacts"]


def test_calculate_mwr_endpoint_unexpected_error_returns_500(client, mocker):
    """Tests that unexpected MWR calculation failures map to HTTP 500."""
    mocker.patch("app.api.endpoints.performance.calculate_money_weighted_return", side_effect=Exception("boom"))
    payload = {
        "portfolio_id": "MWR_ERROR_01",
        "begin_mv": 1000.0,
        "end_mv": 1100.0,
        "as_of": "2025-06-30",
        "cash_flows": [],
        "mwr_method": "XIRR",
    }
    response = client.post("/performance/mwr", json=payload)
    assert response.status_code == 500
    assert "unexpected error occurred during MWR calculation" in response.json()["detail"]
