from datetime import date

import pandas as pd
import pytest

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.requests import PerformanceRequest
from app.services.twr_service import (
    _as_numeric,
    _build_twr_results_by_period,
    _calculate_total_return_from_slice,
    _get_total_cum_ror,
)
from common.enums import Frequency
from core.periods import ResolvedPeriod
from engine.diagnostics import EngineDiagnostics, EngineResetEvent
from engine.schema import PortfolioColumns


def _twr_request(*, emit_resets: bool = False) -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "portfolio_id": "P1",
            "performance_start_date": "2025-01-01",
            "report_end_date": "2025-01-03",
            "metric_basis": "NET",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
                {"perf_date": "2025-01-02", "begin_mv": 1010.0, "end_mv": 1030.2},
            ],
            "reset_policy": {"emit": emit_resets},
        }
    )


def _daily_twr_results_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.BEGIN_MV.value: 1000.0,
                PortfolioColumns.BOD_CF.value: 0.0,
                PortfolioColumns.EOD_CF.value: 0.0,
                PortfolioColumns.MGMT_FEES.value: 0.0,
                PortfolioColumns.END_MV.value: 1010.0,
                PortfolioColumns.DAILY_ROR.value: 1.0,
                PortfolioColumns.FINAL_CUM_ROR.value: 1.0,
                PortfolioColumns.PERF_RESET.value: 0,
                PortfolioColumns.NIP.value: 0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.BEGIN_MV.value: 1010.0,
                PortfolioColumns.BOD_CF.value: 0.0,
                PortfolioColumns.EOD_CF.value: 0.0,
                PortfolioColumns.MGMT_FEES.value: 0.0,
                PortfolioColumns.END_MV.value: 1030.2,
                PortfolioColumns.DAILY_ROR.value: 2.0,
                PortfolioColumns.FINAL_CUM_ROR.value: 3.02,
                PortfolioColumns.PERF_RESET.value: 0,
                PortfolioColumns.NIP.value: 0,
            },
        ]
    )


def test_build_twr_results_by_period_builds_portfolio_summary_and_skips_empty_periods():
    request = _twr_request()
    results = _build_twr_results_by_period(
        performance_request=request,
        resolved_periods=[
            ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
            ResolvedPeriod(name="YTD", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)),
        ],
        freqs_by_period={"ITD": [Frequency.DAILY], "YTD": [Frequency.DAILY]},
        daily_results_df=_daily_twr_results_df(),
        engine_diagnostics=EngineDiagnostics(),
        benchmark_artifacts=None,
        benchmark_request=None,
        benchmark_input_mode=None,
        resolved_benchmark_id=None,
        benchmark_return_source=BenchmarkReturnSource.CALCULATED,
        master_start_date=date(2025, 1, 1),
    )

    assert list(results) == ["ITD"]
    assert results["ITD"].portfolio.summary.period_return.base == pytest.approx(3.02)
    assert len(results["ITD"].portfolio.breakdowns[Frequency.DAILY]) == 2
    assert results["ITD"].benchmark is None


def test_build_twr_results_by_period_filters_reset_events_to_period_window():
    results = _build_twr_results_by_period(
        performance_request=_twr_request(emit_resets=True),
        resolved_periods=[ResolvedPeriod(name="ITD", start_date=date(2025, 1, 1), end_date=date(2025, 1, 2))],
        freqs_by_period={"ITD": [Frequency.DAILY]},
        daily_results_df=_daily_twr_results_df(),
        engine_diagnostics=EngineDiagnostics(
            resets=[
                EngineResetEvent(date=date(2025, 1, 2), reason="in_period", impacted_rows=1),
                EngineResetEvent(date=date(2025, 1, 3), reason="outside_period", impacted_rows=1),
            ]
        ),
        benchmark_artifacts=None,
        benchmark_request=None,
        benchmark_input_mode=None,
        resolved_benchmark_id=None,
        benchmark_return_source=BenchmarkReturnSource.CALCULATED,
        master_start_date=date(2025, 1, 1),
    )

    reset_events = results["ITD"].reset_events
    assert reset_events is not None
    assert [event.reason for event in reset_events] == ["in_period"]


def test_as_numeric_returns_default_for_non_numeric_values():
    assert _as_numeric("not-a-number", default=7) == 7


def test_get_total_cum_ror_returns_zero_for_missing_row():
    assert _get_total_cum_ror(None, "local_ror_") == 0.0


def test_calculate_total_return_from_slice_returns_zero_for_empty_slice():
    empty_df = pd.DataFrame(
        columns=[
            PortfolioColumns.PERF_DATE.value,
            PortfolioColumns.PERF_RESET.value,
            PortfolioColumns.DAILY_ROR.value,
        ]
    )
    result = _calculate_total_return_from_slice(empty_df, empty_df)
    assert result.base == 0.0
    assert result.local == 0.0
    assert result.fx == 0.0


def test_calculate_total_return_from_slice_reset_handles_zero_base_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: -100.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 0.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 12.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 2.0,
                "local_ror_short_cum_ror": 3.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    assert result.base == pytest.approx(12.0)


def test_calculate_total_return_from_slice_reset_handles_zero_fx_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: 0.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 0.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 5.0,
                "local_ror": -100.0,
                "local_ror_long_cum_ror": -100.0,
                "local_ror_short_cum_ror": 0.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    assert result.local == pytest.approx(-100.0)
    assert result.fx == 0.0


def test_calculate_total_return_from_slice_reset_handles_zero_local_start_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: 0.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": -100.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 5.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 2.0,
                "local_ror_short_cum_ror": 3.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    expected_end_local = ((1 + 2.0 / 100) * (1 + 3.0 / 100) - 1) * 100
    assert result.local == pytest.approx(expected_end_local)


def test_calculate_total_return_from_slice_non_reset_handles_zero_fx_denominator():
    non_reset_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.DAILY_ROR.value: -100.0,
                "local_ror": -100.0,
            }
        ]
    )

    result = _calculate_total_return_from_slice(non_reset_df, non_reset_df)
    assert result.local == pytest.approx(-100.0)
    assert result.fx == 0.0
