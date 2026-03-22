from datetime import date

import pytest
from pydantic import ValidationError

from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest


@pytest.fixture
def base_payload():
    return {
        "benchmark_id": "BMK_1",
        "benchmark_start_date": "2024-12-31",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
    }


def test_benchmark_request_rejects_ambiguous_calculated_stateless_inputs(base_payload):
    with pytest.raises(ValidationError, match="exactly one of stateless_input.component_observations"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                    "component_price_points": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2024-12-31",
                            "weight_bop": 1.0,
                            "index_price": 100.0,
                        }
                    ],
                },
            }
        )


def test_benchmark_request_requires_analyses_and_stateless_payload_shape(base_payload):
    with pytest.raises(ValidationError, match="analyses list cannot be empty"):
        BenchmarkAnalyticsRequest.model_validate({**base_payload, "analyses": []})

    with pytest.raises(ValidationError, match="stateless_input is required when input_mode=stateless"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
            }
        )

    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateful_input": {},
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                },
            }
        )

    with pytest.raises(ValidationError, match="benchmark_return_points must be empty"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    ],
                },
            }
        )


def test_benchmark_request_requires_vendor_return_points_without_component_inputs(base_payload):
    with pytest.raises(ValidationError, match="benchmark_return_points are required"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                },
            }
        )

    with pytest.raises(ValidationError, match="component_observations must be empty"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    ],
                    "component_observations": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                },
            }
        )

    with pytest.raises(ValidationError, match="component_price_points must be empty"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    ],
                    "component_price_points": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2024-12-31",
                            "weight_bop": 1.0,
                            "index_price": 100.0,
                        }
                    ],
                },
            }
        )


def test_benchmark_request_uses_stateless_payload_when_no_resolved_overrides_are_supplied(base_payload):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                ],
            },
        }
    )

    benchmark_request = request.to_benchmark_performance_request(benchmark_currency="USD")

    assert benchmark_request.component_observations == []
    assert benchmark_request.benchmark_return_points[0].benchmark_return == 0.01


def test_benchmark_request_builds_empty_lists_from_stateful_mode(base_payload):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateful",
            "return_source": "vendor_series",
            "stateful_input": {},
        }
    )

    benchmark_request = request.to_benchmark_performance_request(
        benchmark_currency="USD",
        benchmark_return_points=[{"perf_date": date(2025, 1, 1), "benchmark_return": 0.01}],
    )

    assert benchmark_request.component_observations == []
    assert benchmark_request.benchmark_return_points[0].benchmark_return == 0.01


def test_benchmark_request_requires_stateful_payload_in_stateful_mode(base_payload):
    with pytest.raises(ValidationError, match="stateful_input is required"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateful",
            }
        )

    with pytest.raises(ValidationError, match="stateless_input must be null when input_mode=stateful"):
        BenchmarkAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateful",
                "stateful_input": {},
                "stateless_input": {"benchmark_currency": "USD"},
            }
        )


def test_benchmark_request_to_performance_request_prefers_resolved_overrides(base_payload):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_observations": [
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2025-01-01",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                ],
            },
        }
    )

    benchmark_request = request.to_benchmark_performance_request(
        benchmark_currency="EUR",
        component_observations=[
            {
                "component_id": "IDX_2",
                "perf_date": date(2025, 1, 1),
                "weight_bop": 1.0,
                "component_return": 0.02,
            }
        ],
        benchmark_return_points=[],
    )

    assert benchmark_request.benchmark_currency == "EUR"
    assert benchmark_request.component_observations[0].component_id == "IDX_2"
    assert benchmark_request.benchmark_return_points == []


def test_benchmark_request_to_performance_request_rejects_unresolved_stateful_calculated_payload(base_payload):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateful",
            "return_source": "calculated",
            "stateful_input": {},
        }
    )

    with pytest.raises(ValidationError, match="component_observations are required"):
        request.to_benchmark_performance_request(benchmark_currency="USD")
