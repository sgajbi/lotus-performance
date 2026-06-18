from datetime import date

import pytest
from pydantic import ValidationError

from app.models.benchmark_analytics_requests import (
    BenchmarkAnalyticsRequest,
    BenchmarkReturnSource,
    BenchmarkStatefulInput,
    BenchmarkStatelessInput,
    _benchmark_component_observations_payload,
    _benchmark_return_points_payload,
    _has_explicit_benchmark_analysis,
    _validate_stateful_benchmark_payloads,
    _validate_stateless_benchmark_payloads,
)
from app.models.requests import Analysis


def test_benchmark_analytics_request_schema_documents_public_examples():
    schema = BenchmarkAnalyticsRequest.model_json_schema()
    examples = schema["examples"]

    assert examples[0]["input_mode"] == "stateless"
    assert examples[0]["return_source"] == "calculated"
    assert examples[0]["stateless_input"]["component_observations"][0]["perf_date"] == "2026-01-02"
    assert examples[1]["input_mode"] == "stateful"
    assert examples[1]["benchmark_id"] == "BMK_PB_GLOBAL_BALANCED_60_40"
    for field_name in (
        "benchmark_id",
        "benchmark_start_date",
        "report_end_date",
        "input_mode",
        "return_source",
        "rounding_precision",
    ):
        field_schema = schema["properties"][field_name]
        assert field_schema["description"]
        assert field_schema["examples"]


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


def test_benchmark_stateless_validation_helpers_preserve_return_source_contracts():
    calculated_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
        }
    )
    vendor_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "benchmark_return_points": [{"perf_date": "2025-01-01", "benchmark_return": 0.01}],
        }
    )

    _validate_stateless_benchmark_payloads(
        stateless_input=calculated_input,
        stateful_input=None,
        return_source=BenchmarkReturnSource.CALCULATED,
    )
    _validate_stateless_benchmark_payloads(
        stateless_input=vendor_input,
        stateful_input=None,
        return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )
    with pytest.raises(ValueError, match="stateful_input must be null"):
        _validate_stateless_benchmark_payloads(
            stateless_input=calculated_input,
            stateful_input=BenchmarkStatefulInput(),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


def test_benchmark_stateful_validation_helper_rejects_stateless_payload_drift():
    _validate_stateful_benchmark_payloads(
        stateless_input=None,
        stateful_input=BenchmarkStatefulInput(),
    )
    with pytest.raises(ValueError, match="stateless_input must be null"):
        _validate_stateful_benchmark_payloads(
            stateless_input=BenchmarkStatelessInput(benchmark_currency="USD"),
            stateful_input=BenchmarkStatefulInput(),
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


def test_has_explicit_benchmark_analysis_detects_explicit_periods():
    explicit = Analysis(
        period="EXPLICIT",
        frequencies=["daily"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )
    ytd = Analysis(period="YTD", frequencies=["daily"])

    assert _has_explicit_benchmark_analysis([ytd]) is False
    assert _has_explicit_benchmark_analysis([ytd, explicit]) is True


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


def test_benchmark_payload_helpers_prefer_resolved_overrides():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
            "benchmark_return_points": [{"perf_date": "2025-01-01", "benchmark_return": 0.01}],
        }
    )

    component_payload = _benchmark_component_observations_payload(
        stateless_input=stateless_input,
        component_observations=[
            {
                "component_id": "IDX_2",
                "perf_date": date(2025, 1, 1),
                "weight_bop": 1.0,
                "component_return": 0.02,
            }
        ],
    )
    return_payload = _benchmark_return_points_payload(
        stateless_input=stateless_input,
        benchmark_return_points=[{"perf_date": date(2025, 1, 1), "benchmark_return": 0.03}],
    )

    assert component_payload[0]["component_id"] == "IDX_2"
    assert return_payload[0]["benchmark_return"] == 0.03


def test_benchmark_payload_helpers_default_to_empty_without_stateless_input():
    assert _benchmark_component_observations_payload(stateless_input=None, component_observations=None) == []
    assert _benchmark_return_points_payload(stateless_input=None, benchmark_return_points=None) == []


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
