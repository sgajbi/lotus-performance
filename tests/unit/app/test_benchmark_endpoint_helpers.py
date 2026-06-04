from uuid import uuid4

from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest
from app.services.benchmark_calculation_workflow_service import (
    accepted_benchmark_response,
    benchmark_requested_input_count,
    build_benchmark_execution_window,
    should_offload_benchmark,
    should_offload_resolved_benchmark,
    should_persist_resolved_benchmark_request,
    should_preemptively_offload_stateful_benchmark,
)


def _base_payload():
    return {
        "benchmark_id": "BMK_1",
        "benchmark_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
    }


def test_benchmark_endpoint_helper_counts_requested_inputs_and_persist_rules():
    observations_request = BenchmarkAnalyticsRequest.model_validate(
        {
            **_base_payload(),
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
    price_points_request = BenchmarkAnalyticsRequest.model_validate(
        {
            **_base_payload(),
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_price_points": [
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2024-12-31",
                        "weight_bop": 1.0,
                        "index_price": 100.0,
                    },
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2025-01-01",
                        "weight_bop": 1.0,
                        "index_price": 101.0,
                    },
                ],
            },
        }
    )
    vendor_request = BenchmarkAnalyticsRequest.model_validate(
        {
            **_base_payload(),
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    {"perf_date": "2025-01-02", "benchmark_return": 0.02},
                ],
            },
        }
    )
    stateful_request = BenchmarkAnalyticsRequest.model_validate(
        {
            **_base_payload(),
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    assert benchmark_requested_input_count(observations_request) == 1
    assert benchmark_requested_input_count(price_points_request) == 2
    assert benchmark_requested_input_count(vendor_request) == 2
    assert benchmark_requested_input_count(stateful_request) == 0
    assert should_persist_resolved_benchmark_request(observations_request) is False
    assert should_persist_resolved_benchmark_request(price_points_request) is True
    assert should_persist_resolved_benchmark_request(stateful_request) is True


def test_benchmark_endpoint_helpers_build_execution_window_and_acceptance(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            **_base_payload(),
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
    stateful_request = BenchmarkAnalyticsRequest.model_validate(
        {
            **_base_payload(),
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"BENCHMARK_EXECUTOR_WINDOW_DAYS": 20, "BENCHMARK_EXECUTOR_INPUT_COUNT": 1},
        )(),
    )

    assert should_preemptively_offload_stateful_benchmark(stateful_request) is True
    assert should_offload_benchmark(request) is True
    assert should_offload_resolved_benchmark(1) is True
    assert build_benchmark_execution_window(request)["input_count"] == 1
    assert build_benchmark_execution_window(request, source_request_fingerprint="fp", input_count=5) == {
        "benchmark_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "requested_periods": ["ITD"],
        "return_source": "vendor_series",
        "input_mode": "stateless",
        "input_count": 5,
        "source_request_fingerprint": "fp",
    }

    calculation_id = uuid4()
    accepted = accepted_benchmark_response(calculation_id)
    assert accepted.calculation_id == calculation_id
    assert accepted.poll_path == f"/performance/executions/{calculation_id}"
    assert accepted.result_path == f"/performance/benchmark/results/{calculation_id}"
