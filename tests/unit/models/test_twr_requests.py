import pytest
from pydantic import ValidationError

from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode


@pytest.fixture
def base_payload():
    return {
        "portfolio_id": "TWR_MODE_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
    }


def test_twr_request_accepts_legacy_stateless_payload(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
        }
    )

    assert request.input_mode == TWRInputMode.STATELESS
    assert request.valuation_points is not None
    assert request.stateless_input is None


def test_twr_request_accepts_nested_stateless_payload(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
        }
    )

    assert request.input_mode == TWRInputMode.STATELESS
    assert request.stateless_input is not None
    assert request.stateless_input.valuation_points[0].end_mv == 1010


def test_twr_request_requires_stateful_input_for_stateful_mode(base_payload):
    with pytest.raises(ValidationError, match="stateful_input is required"):
        TWRAnalyticsRequest.model_validate({**base_payload, "input_mode": "stateful"})


def test_twr_request_rejects_ambiguous_stateless_payload(base_payload):
    with pytest.raises(ValidationError, match="Provide either stateless_input or valuation_points"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "stateless_input": {
                    "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
            }
        )
