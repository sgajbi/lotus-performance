from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.services.execution_registry import execution_registry
from main import app


def _twr_payload(*, start: str, end: str) -> dict:
    return {
        "calculation_id": str(uuid4()),
        "portfolio_id": "EXPLICIT_TWR",
        "performance_start_date": "2025-01-01",
        "metric_basis": "NET",
        "report_start_date": start,
        "report_end_date": end,
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000, "end_mv": 1010}],
    }


def _workspace_payload(*, start: str, end: str) -> dict:
    return {
        "calculation_id": str(uuid4()),
        "portfolio_id": "EXPLICIT_WORKSPACE",
        "performance_start_date": "2025-01-01",
        "report_start_date": start,
        "report_end_date": end,
        "periods": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "stateless_input": {"valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000, "end_mv": 1010}]},
    }


def _benchmark_payload(*, start: str, end: str) -> dict:
    return {
        "calculation_id": str(uuid4()),
        "benchmark_id": "EXPLICIT_BENCHMARK",
        "benchmark_start_date": "2025-01-01",
        "report_start_date": start,
        "report_end_date": end,
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "INDEX_A",
                    "perf_date": "2025-01-02",
                    "weight_bop": 1,
                    "component_return": 0.01,
                }
            ],
        },
    }


def _contribution_payload(*, start: str, end: str) -> dict:
    valuation = [{"perf_date": "2025-01-02", "begin_mv": 1000, "end_mv": 1010}]
    return {
        "calculation_id": str(uuid4()),
        "portfolio_id": "EXPLICIT_CONTRIBUTION",
        "report_start_date": start,
        "report_end_date": end,
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "portfolio_data": {"metric_basis": "NET", "valuation_points": valuation},
        "positions_data": [
            {
                "position_id": "POSITION_A",
                "meta": {"sector": "Technology"},
                "valuation_points": deepcopy(valuation),
            }
        ],
    }


def _attribution_payload(*, start: str, end: str) -> dict:
    observation = [{"date": "2025-01-02", "return_base": 0.01, "weight_bop": 1}]
    return {
        "calculation_id": str(uuid4()),
        "portfolio_id": "EXPLICIT_ATTRIBUTION",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": start,
        "report_end_date": end,
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "portfolio_groups_data": [{"key": {"sector": "Technology"}, "observations": observation}],
        "benchmark_groups_data": [{"key": {"sector": "Technology"}, "observations": deepcopy(observation)}],
    }


_EXPLICIT_ENDPOINTS = (
    ("/performance/twr", _twr_payload),
    ("/performance/workspace-summary", _workspace_payload),
    ("/performance/benchmark", _benchmark_payload),
    ("/performance/contribution", _contribution_payload),
    ("/performance/attribution", _attribution_payload),
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"X-Tenant-Id": "tenant-explicit-window"}) as test_client:
        yield test_client


@pytest.mark.parametrize(("endpoint", "payload_factory"), _EXPLICIT_ENDPOINTS)
def test_reversed_explicit_window_is_non_retryable_and_never_registered(client, endpoint, payload_factory):
    payload = payload_factory(start="2025-01-03", end="2025-01-02")

    response = client.post(endpoint, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["retryable"] is False
    assert body["message"] == "Request validation failed."
    assert body["correlation_id"]
    assert body["request_id"]
    assert execution_registry.get_execution(payload["calculation_id"]) is None


@pytest.mark.parametrize(("endpoint", "payload_factory"), _EXPLICIT_ENDPOINTS)
def test_same_day_explicit_window_remains_valid(client, endpoint, payload_factory):
    response = client.post(endpoint, json=payload_factory(start="2025-01-02", end="2025-01-02"))

    assert response.status_code == 200
    explicit = response.json()["results_by_period"]["EXPLICIT"]
    if endpoint == "/performance/twr":
        actual = explicit["portfolio"]["summary"]["period_return"]["base"]
    elif endpoint == "/performance/workspace-summary":
        actual = explicit["portfolio_twr"]["net"]["summary"]["period_return"]["base"]
    elif endpoint == "/performance/benchmark":
        actual = explicit["benchmark"]["summary"]["period_return"]["base"]
    elif endpoint == "/performance/contribution":
        actual = explicit["total_portfolio_return"]
    else:
        actual = explicit["reconciliation"]["total_active_return"]

    expected = 0.0 if endpoint == "/performance/attribution" else 1.0
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    ("endpoint", "payload_factory"),
    _EXPLICIT_ENDPOINTS[:3],
)
def test_explicit_window_before_inception_preserves_existing_resolution(client, endpoint, payload_factory):
    response = client.post(endpoint, json=payload_factory(start="2024-12-31", end="2025-01-02"))

    assert response.status_code == 200
    assert "EXPLICIT" in response.json()["results_by_period"]


@pytest.mark.parametrize(("endpoint", "payload_factory"), _EXPLICIT_ENDPOINTS)
def test_explicit_window_without_start_date_remains_a_client_error(client, endpoint, payload_factory):
    payload = payload_factory(start="2025-01-01", end="2025-01-02")
    del payload["report_start_date"]

    response = client.post(endpoint, json=payload)

    expected_status = 400 if endpoint == "/performance/twr" else 422
    assert response.status_code == expected_status
    assert response.json()["retryable"] is False
    assert execution_registry.get_execution(payload["calculation_id"]) is None
