# tests/integration/test_rounding_api.py
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_twr_endpoint_respects_rounding_precision(client):
    """Tests that aggregated summary values in the response are rounded correctly."""
    payload = {
        "portfolio_id": "ROUNDING_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "MTD", "frequencies": ["monthly"]}],
        "rounding_precision": 2,  # Request 2 decimal places
        "valuation_points": [
            {"day": 1, "perf_date": "2025-01-15", "begin_mv": 1000.0, "end_mv": 1011.23456},
        ],
    }
    response = client.post("/performance/twr", json=payload)
    assert response.status_code == 200
    data = response.json()
    summary = data["results_by_period"]["MTD"]["portfolio"]["breakdowns"]["monthly"][0]["period_return"]

    # The raw return is 1.123456%. It should be rounded to 1.12.
    assert summary["base"] == pytest.approx(1.12)
