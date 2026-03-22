from datetime import date

import pytest
from pydantic import ValidationError

from app.models.benchmark_requests import BenchmarkPerformanceRequest


@pytest.fixture
def base_payload():
    return {
        "benchmark_id": "BMK-1",
        "benchmark_start_date": "2025-01-01",
        "report_end_date": "2025-01-31",
        "benchmark_currency": "USD",
        "analyses": [{"period": "MTD", "frequencies": ["daily"]}],
    }


def test_benchmark_performance_request_requires_analyses_and_calculated_component_inputs(base_payload):
    with pytest.raises(ValidationError, match="analyses list cannot be empty"):
        BenchmarkPerformanceRequest.model_validate(
            {
                **base_payload,
                "analyses": [],
                "component_observations": [
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2025-01-02",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                ],
            }
        )

    with pytest.raises(ValidationError, match="component_observations are required"):
        BenchmarkPerformanceRequest.model_validate(base_payload)

    with pytest.raises(ValidationError, match="benchmark_return_points must be empty"):
        BenchmarkPerformanceRequest.model_validate(
            {
                **base_payload,
                "component_observations": [
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2025-01-02",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                ],
                "benchmark_return_points": [
                    {"perf_date": "2025-01-02", "benchmark_return": 0.01},
                ],
            }
        )


def test_benchmark_performance_request_requires_vendor_series_without_component_rows(base_payload):
    with pytest.raises(ValidationError, match="benchmark_return_points are required"):
        BenchmarkPerformanceRequest.model_validate(
            {
                **base_payload,
                "return_source": "vendor_series",
            }
        )

    with pytest.raises(ValidationError, match="component_observations must be empty"):
        BenchmarkPerformanceRequest.model_validate(
            {
                **base_payload,
                "return_source": "vendor_series",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-02", "benchmark_return": 0.01},
                ],
                "component_observations": [
                    {
                        "component_id": "IDX_1",
                        "perf_date": "2025-01-02",
                        "weight_bop": 1.0,
                        "component_return": 0.01,
                    }
                ],
            }
        )


def test_benchmark_performance_request_accepts_valid_calculated_and_vendor_payloads(base_payload):
    calculated = BenchmarkPerformanceRequest.model_validate(
        {
            **base_payload,
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": date(2025, 1, 2),
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                    "component_return_local": 0.008,
                    "component_return_fx": 0.002,
                }
            ],
        }
    )
    vendor = BenchmarkPerformanceRequest.model_validate(
        {
            **base_payload,
            "return_source": "vendor_series",
            "benchmark_return_points": [
                {"perf_date": date(2025, 1, 2), "benchmark_return": 0.01},
            ],
        }
    )

    assert calculated.return_source == "calculated"
    assert calculated.component_observations[0].component_return_fx == 0.002
    assert vendor.return_source == "vendor_series"
    assert vendor.benchmark_return_points[0].benchmark_return == 0.01


def test_benchmark_performance_request_requires_report_start_date_for_explicit_period(base_payload):
    explicit_payload = {
        **base_payload,
        "analyses": [{"period": "EXPLICIT", "frequencies": ["daily"]}],
        "component_observations": [
            {
                "component_id": "IDX_1",
                "perf_date": "2025-01-02",
                "weight_bop": 1.0,
                "component_return": 0.01,
            }
        ],
    }

    with pytest.raises(ValidationError, match="report_start_date is required when analyses include EXPLICIT"):
        BenchmarkPerformanceRequest.model_validate(explicit_payload)

    request = BenchmarkPerformanceRequest.model_validate(
        {
            **explicit_payload,
            "report_start_date": "2025-01-02",
        }
    )

    assert request.report_start_date == date(2025, 1, 2)
