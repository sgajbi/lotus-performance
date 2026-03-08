# tests/integration/test_mwr_api.py
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.conftest import drain_lineage_queue


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
    assert response_data["method"] == "XIRR"
    assert response_data["money_weighted_return"] == pytest.approx(11.723, abs=1e-3)
    assert response_data["mwr_annualized"] is not None


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
