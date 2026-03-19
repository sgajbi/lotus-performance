import pytest
from pydantic import ValidationError

from app.models.requests import DailyInputData
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
    stateless = request.to_stateless_performance_request()
    assert stateless.valuation_points[0].end_mv == 1010


def test_twr_request_rejects_missing_stateless_payload(base_payload):
    with pytest.raises(ValidationError, match="stateless_input or valuation_points is required"):
        TWRAnalyticsRequest.model_validate(base_payload)


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


def test_twr_request_rejects_stateful_payload_in_stateless_mode(base_payload):
    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "stateful_input": {"consumer_system": "lotus-performance"},
            }
        )


def test_twr_request_rejects_stateless_payloads_in_stateful_mode(base_payload):
    with pytest.raises(ValidationError, match="stateless_input must be null when input_mode=stateful"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateful",
                "stateful_input": {"consumer_system": "lotus-performance"},
                "stateless_input": {
                    "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
            }
        )

    with pytest.raises(ValidationError, match="valuation_points must be null when input_mode=stateful"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateful",
                "stateful_input": {"consumer_system": "lotus-performance"},
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        )


def test_twr_request_to_stateless_prefers_explicit_override(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
        }
    )

    stateless = request.to_stateless_performance_request(
        valuation_points=[
            DailyInputData.model_validate({"day": 2, "perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1})
        ]
    )

    assert len(stateless.valuation_points) == 1
    assert stateless.valuation_points[0].day == 2


def test_twr_request_to_stateless_fails_without_stateless_payload(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
        }
    )

    with pytest.raises(ValueError, match="No stateless valuation_points are available"):
        request.to_stateless_performance_request()


def test_twr_request_accepts_nested_stateless_benchmark_request(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                },
            },
        }
    )

    assert request.benchmark is not None
    assert request.benchmark.input_mode.value == "stateless"
    assert request.to_stateless_performance_request().valuation_points[0].end_mv == 1010


def test_twr_request_requires_stateful_benchmark_payload_when_requested(base_payload):
    with pytest.raises(ValidationError, match="benchmark.stateful_input is required"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "benchmark": {
                    "input_mode": "stateful",
                },
            }
        )
