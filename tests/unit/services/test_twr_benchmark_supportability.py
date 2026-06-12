from datetime import date

import pandas as pd

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.services.twr_benchmark_supportability import (
    _has_benchmark_fx_decomposition,
    build_twr_benchmark_supportability_evidence,
)


def _performance_request() -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "portfolio_id": "PB_TEST",
            "performance_start_date": "2025-01-01",
            "metric_basis": "NET",
            "report_end_date": "2025-01-03",
            "report_ccy": "USD",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
                {"perf_date": "2025-01-03", "begin_mv": 1020.1, "end_mv": 1030.301},
            ],
        }
    )


def test_twr_benchmark_supportability_reports_aligned_fx_decomposed_evidence():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_GLOBAL",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "benchmark_currency": "USD",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_EUR",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_currency": "EUR",
                    "component_return": 0.012,
                    "component_return_local": 0.01,
                    "component_return_fx": 0.00198,
                }
            ],
        }
    )

    evidence = build_twr_benchmark_supportability_evidence(
        performance_request=_performance_request(),
        benchmark_request=benchmark_request,
        portfolio_daily_results_df=pd.DataFrame({"perf_date": [date(2025, 1, 1), date(2025, 1, 2)]}),
        benchmark_daily_returns_df=pd.DataFrame(
            {
                "date": [date(2025, 1, 1), date(2025, 1, 2)],
                "benchmark_return": [0.012, 0.013],
                "benchmark_return_local": [0.01, 0.011],
                "benchmark_return_fx": [0.00198, 0.00197],
            }
        ),
        benchmark_input_mode="stateless",
        benchmark_return_source="calculated",
    )

    assert evidence.currency_state == "fx_decomposed"
    assert evidence.calendar_alignment_state == "aligned"
    assert evidence.overlapping_observation_count == 2
    assert evidence.warning_codes == []


def test_has_benchmark_fx_decomposition_requires_local_and_fx_columns_with_values():
    assert _has_benchmark_fx_decomposition(
        pd.DataFrame(
            {
                "benchmark_return_local": [None, 0.01],
                "benchmark_return_fx": [0.001, None],
            }
        )
    )
    assert not _has_benchmark_fx_decomposition(pd.DataFrame({"benchmark_return_local": [0.01]}))
    assert not _has_benchmark_fx_decomposition(
        pd.DataFrame({"benchmark_return_local": [None], "benchmark_return_fx": [None]})
    )


def test_twr_benchmark_supportability_reports_calendar_and_vendor_series_warnings():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "benchmark_currency": "EUR",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "return_source": "vendor_series",
            "benchmark_return_points": [{"perf_date": "2025-01-02", "benchmark_return": 0.012}],
        }
    )

    evidence = build_twr_benchmark_supportability_evidence(
        performance_request=_performance_request(),
        benchmark_request=benchmark_request,
        portfolio_daily_results_df=pd.DataFrame({"perf_date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]}),
        benchmark_daily_returns_df=pd.DataFrame({"date": [date(2025, 1, 2)], "benchmark_return": [0.012]}),
        benchmark_input_mode="stateless",
        benchmark_return_source="vendor_series",
    )

    assert evidence.currency_state == "vendor_series_base_only"
    assert evidence.calendar_alignment_state == "partial_overlap"
    assert evidence.missing_benchmark_date_count == 2
    assert evidence.missing_benchmark_dates_sample == [date(2025, 1, 1), date(2025, 1, 3)]
    assert evidence.warning_codes == [
        "BENCHMARK_CALENDAR_GAP",
        "BENCHMARK_VENDOR_SERIES_BASE_ONLY",
        "BENCHMARK_CURRENCY_DIFFERS_FROM_REPORTING_CURRENCY",
    ]


def test_twr_benchmark_supportability_reports_no_overlap_and_empty_benchmark_dates():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_EMPTY",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "benchmark_currency": "USD",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_USD",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_currency": "USD",
                    "component_return": 0.012,
                }
            ],
        }
    )

    evidence = build_twr_benchmark_supportability_evidence(
        performance_request=_performance_request(),
        benchmark_request=benchmark_request,
        portfolio_daily_results_df=pd.DataFrame({"perf_date": [date(2025, 1, 1), date(2025, 1, 2)]}),
        benchmark_daily_returns_df=pd.DataFrame({"benchmark_return": []}),
        benchmark_input_mode="stateful",
        benchmark_return_source="calculated",
    )

    assert evidence.currency_state == "single_currency"
    assert evidence.calendar_alignment_state == "no_overlap"
    assert evidence.benchmark_observation_count == 0
    assert evidence.missing_benchmark_date_count == 2
    assert evidence.warning_codes == ["BENCHMARK_CALENDAR_NO_OVERLAP"]


def test_twr_benchmark_supportability_reports_base_only_cross_currency_evidence():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_BASE_ONLY",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "benchmark_currency": "USD",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_EUR",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_currency": "EUR",
                    "component_return": 0.012,
                }
            ],
        }
    )

    evidence = build_twr_benchmark_supportability_evidence(
        performance_request=_performance_request(),
        benchmark_request=benchmark_request,
        portfolio_daily_results_df=pd.DataFrame({"perf_date": [date(2025, 1, 1)]}),
        benchmark_daily_returns_df=pd.DataFrame({"date": [date(2025, 1, 1)], "benchmark_return": [0.012]}),
        benchmark_input_mode="stateless",
        benchmark_return_source="calculated",
    )

    assert evidence.currency_state == "base_only"
    assert evidence.calendar_alignment_state == "aligned"
    assert evidence.warning_codes == ["BENCHMARK_FX_DECOMPOSITION_UNAVAILABLE"]
