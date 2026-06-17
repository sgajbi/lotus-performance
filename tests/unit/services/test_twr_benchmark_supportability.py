from datetime import date

import pandas as pd

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.services.twr_benchmark_supportability import (
    _benchmark_calendar_alignment,
    _benchmark_calendar_alignment_state,
    _benchmark_component_currencies,
    _has_benchmark_calendar_no_overlap,
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


def test_benchmark_component_currencies_ignores_missing_component_currency():
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "benchmark_id": "BMK_MIXED",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "benchmark_currency": "USD",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_USD",
                    "perf_date": "2025-01-01",
                    "weight_bop": 0.5,
                    "component_return": 0.01,
                },
                {
                    "component_id": "IDX_EUR",
                    "perf_date": "2025-01-01",
                    "weight_bop": 0.5,
                    "component_currency": "EUR",
                    "component_return": 0.012,
                },
            ],
        }
    )

    assert _benchmark_component_currencies(benchmark_request) == {"EUR"}


def test_benchmark_calendar_alignment_projects_counts_and_warning_codes():
    aligned = _benchmark_calendar_alignment(
        portfolio_dates={date(2025, 1, 1), date(2025, 1, 2)},
        benchmark_dates={date(2025, 1, 1), date(2025, 1, 2)},
    )
    assert aligned.state == "aligned"
    assert aligned.warning_codes == []
    assert aligned.missing_benchmark_dates == []
    assert aligned.extra_benchmark_dates == []

    partial = _benchmark_calendar_alignment(
        portfolio_dates={date(2025, 1, 1), date(2025, 1, 2)},
        benchmark_dates={date(2025, 1, 2), date(2025, 1, 3)},
    )
    assert partial.state == "partial_overlap"
    assert partial.warning_codes == ["BENCHMARK_CALENDAR_GAP"]
    assert partial.missing_benchmark_dates == [date(2025, 1, 1)]
    assert partial.extra_benchmark_dates == [date(2025, 1, 3)]
    assert partial.overlapping_dates == {date(2025, 1, 2)}

    no_overlap = _benchmark_calendar_alignment(
        portfolio_dates={date(2025, 1, 1)},
        benchmark_dates={date(2025, 1, 2)},
    )
    assert no_overlap.state == "no_overlap"
    assert no_overlap.warning_codes == ["BENCHMARK_CALENDAR_NO_OVERLAP"]
    assert no_overlap.overlapping_dates == set()


def test_benchmark_calendar_alignment_state_projects_warnings():
    assert _benchmark_calendar_alignment_state(
        portfolio_dates=set(),
        benchmark_dates=set(),
        overlapping_dates=set(),
        missing_benchmark_dates=[],
        extra_benchmark_dates=[],
    ) == ("aligned", [])

    assert _benchmark_calendar_alignment_state(
        portfolio_dates={date(2025, 1, 1)},
        benchmark_dates={date(2025, 1, 1)},
        overlapping_dates={date(2025, 1, 1)},
        missing_benchmark_dates=[],
        extra_benchmark_dates=[],
    ) == ("aligned", [])

    assert _benchmark_calendar_alignment_state(
        portfolio_dates={date(2025, 1, 1), date(2025, 1, 2)},
        benchmark_dates={date(2025, 1, 2), date(2025, 1, 3)},
        overlapping_dates={date(2025, 1, 2)},
        missing_benchmark_dates=[date(2025, 1, 1)],
        extra_benchmark_dates=[date(2025, 1, 3)],
    ) == ("partial_overlap", ["BENCHMARK_CALENDAR_GAP"])

    assert _benchmark_calendar_alignment_state(
        portfolio_dates={date(2025, 1, 1)},
        benchmark_dates={date(2025, 1, 2)},
        overlapping_dates=set(),
        missing_benchmark_dates=[date(2025, 1, 1)],
        extra_benchmark_dates=[date(2025, 1, 2)],
    ) == ("no_overlap", ["BENCHMARK_CALENDAR_NO_OVERLAP"])


def test_has_benchmark_calendar_no_overlap_requires_dates_without_intersection():
    assert not _has_benchmark_calendar_no_overlap(
        portfolio_dates=set(),
        benchmark_dates=set(),
        overlapping_dates=set(),
    )
    assert _has_benchmark_calendar_no_overlap(
        portfolio_dates={date(2025, 1, 1)},
        benchmark_dates={date(2025, 1, 2)},
        overlapping_dates=set(),
    )
    assert not _has_benchmark_calendar_no_overlap(
        portfolio_dates={date(2025, 1, 1)},
        benchmark_dates={date(2025, 1, 1)},
        overlapping_dates={date(2025, 1, 1)},
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
