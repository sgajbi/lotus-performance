from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.requests import DailyInputData
from app.models.twr_requests import (
    TWRAnalyticsRequest,
    TWRBenchmarkRequest,
    TWRInputMode,
    _has_exactly_one_stateless_twr_payload,
    _has_legacy_twr_valuation_points,
    _has_nested_twr_stateless_input,
    _stateless_twr_envelope_issue,
    _validate_calculated_stateless_twr_benchmark_payload,
    _validate_stateless_twr_payloads,
    _validate_twr_benchmark_inclusion,
)


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
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
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
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
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
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "stateless_input": {
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
            }
        )


def test_twr_stateless_payload_helper_rejects_ambiguous_payloads():
    request = TWRAnalyticsRequest.model_construct(
        performance_start_date=date(2024, 12, 31),
        stateless_input=object(),
        stateful_input=None,
        valuation_points=[DailyInputData.model_validate({"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010})],
    )

    with pytest.raises(ValueError, match="Provide either stateless_input or valuation_points"):
        _validate_stateless_twr_payloads(request)


@pytest.mark.parametrize(
    ("stateless_input", "valuation_points", "has_nested", "has_legacy", "has_exactly_one"),
    [
        (object(), [], True, False, True),
        (
            None,
            [DailyInputData.model_validate({"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010})],
            False,
            True,
            True,
        ),
        (None, [], False, False, False),
        (
            object(),
            [DailyInputData.model_validate({"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010})],
            True,
            True,
            False,
        ),
    ],
)
def test_twr_stateless_payload_shape_predicates(
    stateless_input,
    valuation_points,
    has_nested,
    has_legacy,
    has_exactly_one,
):
    request = TWRAnalyticsRequest.model_construct(
        performance_start_date=date(2024, 12, 31),
        stateless_input=stateless_input,
        stateful_input=None,
        valuation_points=valuation_points,
    )

    assert _has_nested_twr_stateless_input(request) is has_nested
    assert _has_legacy_twr_valuation_points(request) is has_legacy
    assert _has_exactly_one_stateless_twr_payload(request) is has_exactly_one


def test_stateless_twr_envelope_issue_requires_exactly_one_payload_shape():
    assert _stateless_twr_envelope_issue(has_nested=True, has_legacy=False) is None
    assert _stateless_twr_envelope_issue(has_nested=False, has_legacy=True) is None
    assert _stateless_twr_envelope_issue(has_nested=True, has_legacy=True) == (
        "Provide either stateless_input or valuation_points, not both, for stateless mode"
    )
    assert _stateless_twr_envelope_issue(has_nested=False, has_legacy=False) == (
        "stateless_input or valuation_points is required when input_mode=stateless"
    )


def test_twr_request_rejects_stateful_payload_in_stateless_mode(base_payload):
    with pytest.raises(ValidationError, match="stateful_input must be null when input_mode=stateless"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "stateful_input": {},
            }
        )


def test_twr_request_rejects_stateless_payloads_in_stateful_mode(base_payload):
    with pytest.raises(ValidationError, match="stateless_input must be null when input_mode=stateful"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateful",
                "stateful_input": {},
                "stateless_input": {
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
            }
        )

    with pytest.raises(ValidationError, match="valuation_points must be null when input_mode=stateful"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "input_mode": "stateful",
                "stateful_input": {},
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        )


def test_twr_request_to_stateless_prefers_explicit_override(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
        }
    )

    stateless = request.to_stateless_performance_request(
        valuation_points=[
            DailyInputData.model_validate({"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1})
        ]
    )

    assert len(stateless.valuation_points) == 1
    assert stateless.valuation_points[0].perf_date.isoformat() == "2025-01-02"


def test_twr_request_to_stateless_fails_without_stateless_payload(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    with pytest.raises(ValueError, match="No stateless valuation_points are available"):
        request.to_stateless_performance_request()


def test_twr_request_accepts_nested_stateless_benchmark_request(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "include_benchmark": True,
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                },
            },
        }
    )

    assert request.benchmark is not None
    assert request.include_benchmark is True
    assert request.benchmark.input_mode.value == "stateless"
    assert request.to_stateless_performance_request().valuation_points[0].end_mv == 1010


def test_twr_benchmark_inclusion_helper_promotes_nested_benchmark(base_payload):
    request = TWRAnalyticsRequest.model_construct(
        input_mode=TWRInputMode.STATEFUL,
        include_benchmark=False,
        benchmark=TWRBenchmarkRequest.model_construct(),
    )

    _validate_twr_benchmark_inclusion(request)

    assert request.include_benchmark is True


def test_twr_request_accepts_stateless_benchmark_price_points(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "include_benchmark": True,
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_price_points": [
                        {"component_id": "IDX_A", "perf_date": "2024-12-31", "weight_bop": 1.0, "index_price": 100.0},
                        {"component_id": "IDX_A", "perf_date": "2025-01-01", "weight_bop": 1.0, "index_price": 101.0},
                    ],
                },
            },
        }
    )

    assert request.benchmark is not None
    assert len(request.benchmark.stateless_input.component_price_points) == 2


def test_twr_request_supports_stateful_include_benchmark_without_nested_config(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "input_mode": "stateful",
            "stateful_input": {},
            "include_benchmark": True,
        }
    )

    assert request.include_benchmark is True
    assert request.benchmark is None


def test_twr_request_allows_missing_start_date_in_stateful_mode(base_payload):
    payload = {key: value for key, value in base_payload.items() if key != "performance_start_date"}
    request = TWRAnalyticsRequest.model_validate(
        {
            **payload,
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    assert request.performance_start_date is None


def test_twr_request_requires_benchmark_config_for_stateless_include_benchmark(base_payload):
    with pytest.raises(ValidationError, match="benchmark configuration is required when include_benchmark=true"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "include_benchmark": True,
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        )


def test_twr_request_requires_stateful_benchmark_payload_when_requested(base_payload):
    with pytest.raises(ValidationError, match="benchmark.stateful_input is required"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "benchmark": {
                    "input_mode": "stateful",
                },
            }
        )


def test_twr_request_rejects_ambiguous_stateless_benchmark_inputs(base_payload):
    with pytest.raises(ValidationError, match="exactly one of benchmark.stateless_input.component_observations"):
        TWRAnalyticsRequest.model_validate(
            {
                **base_payload,
                "include_benchmark": True,
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                "benchmark": {
                    "benchmark_id": "BMK_1",
                    "input_mode": "stateless",
                    "return_source": "calculated",
                    "stateless_input": {
                        "benchmark_currency": "USD",
                        "component_observations": [
                            {
                                "component_id": "IDX_A",
                                "perf_date": "2025-01-01",
                                "weight_bop": 1.0,
                                "component_return": 0.01,
                            }
                        ],
                        "component_price_points": [
                            {
                                "component_id": "IDX_A",
                                "perf_date": "2024-12-31",
                                "weight_bop": 1.0,
                                "index_price": 100.0,
                            },
                            {
                                "component_id": "IDX_A",
                                "perf_date": "2025-01-01",
                                "weight_bop": 1.0,
                                "index_price": 101.0,
                            },
                        ],
                    },
                },
            }
        )


def test_twr_benchmark_request_requires_benchmark_id_for_stateless_mode():
    with pytest.raises(ValidationError, match="benchmark.stateless_input is required"):
        TWRBenchmarkRequest.model_validate(
            {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
            }
        )

    with pytest.raises(ValidationError, match="benchmark.stateful_input must be null"):
        TWRBenchmarkRequest.model_validate(
            {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "stateful_input": {},
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                },
            }
        )

    with pytest.raises(ValidationError, match="benchmark.benchmark_id is required"):
        TWRBenchmarkRequest.model_validate(
            {
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        }
                    ],
                },
            }
        )


def test_twr_benchmark_request_enforces_vendor_series_payload_shape():
    with pytest.raises(ValidationError, match="benchmark_return_points must be empty"):
        TWRBenchmarkRequest.model_validate(
            {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
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

    with pytest.raises(ValidationError, match="benchmark_return_points are required"):
        TWRBenchmarkRequest.model_validate(
            {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {"benchmark_currency": "USD"},
            }
        )

    with pytest.raises(ValidationError, match="component_price_points must be empty"):
        TWRBenchmarkRequest.model_validate(
            {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    ],
                    "component_price_points": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "index_price": 101.0,
                        }
                    ],
                },
            }
        )


def test_validate_calculated_stateless_twr_benchmark_payload_requires_one_component_source():
    request = SimpleNamespace(
        stateless_input=SimpleNamespace(
            component_observations=[],
            component_price_points=[],
            benchmark_return_points=[],
        )
    )

    with pytest.raises(ValueError, match="exactly one of benchmark.stateless_input.component_observations"):
        _validate_calculated_stateless_twr_benchmark_payload(request)  # type: ignore[arg-type]


def test_twr_request_auto_enables_benchmark_when_config_present(base_payload):
    request = TWRAnalyticsRequest.model_validate(
        {
            **base_payload,
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    ],
                },
            },
        }
    )

    assert request.include_benchmark is True


def test_twr_request_requires_stateless_start_date(base_payload):
    payload = {key: value for key, value in base_payload.items() if key != "performance_start_date"}

    with pytest.raises(ValidationError, match="performance_start_date is required when input_mode=stateless"):
        TWRAnalyticsRequest.model_validate(
            {
                **payload,
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            }
        )


def test_twr_request_to_stateless_requires_performance_start_date():
    request = TWRAnalyticsRequest.model_construct(
        portfolio_id="TWR_MODE_TEST",
        performance_start_date=None,
        metric_basis="NET",
        report_end_date=date(2025, 1, 31),
        analyses=[],
        input_mode=TWRInputMode.STATELESS,
        stateless_input=None,
        stateful_input=None,
        benchmark=None,
        include_benchmark=False,
        valuation_points=[],
    )

    with pytest.raises(ValueError, match="performance_start_date is required"):
        request.to_stateless_performance_request()


def test_daily_input_data_rejects_client_supplied_day_sequence():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DailyInputData.model_validate({"perf_date": "2025-01-01", "day": 1, "begin_mv": 1000, "end_mv": 1010})
