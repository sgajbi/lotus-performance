from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import islice
from typing import Literal

import pandas as pd

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.models.responses import TWRBenchmarkSupportabilityEvidence
from app.services.analytics_observation_dates import observation_date_set
from engine.schema import PortfolioColumns

_DATE_SAMPLE_LIMIT = 5
_CalendarAlignmentState = Literal["aligned", "partial_overlap", "no_overlap"]


@dataclass(frozen=True)
class _BenchmarkCalendarAlignment:
    state: _CalendarAlignmentState
    portfolio_dates: set[date]
    benchmark_dates: set[date]
    overlapping_dates: set[date]
    missing_benchmark_dates: list[date]
    extra_benchmark_dates: list[date]
    warning_codes: list[str]


def build_twr_benchmark_supportability_evidence(
    *,
    performance_request: PerformanceRequest,
    benchmark_request: BenchmarkPerformanceRequest,
    portfolio_daily_results_df: pd.DataFrame,
    benchmark_daily_returns_df: pd.DataFrame,
    benchmark_input_mode: str,
    benchmark_return_source: str,
) -> TWRBenchmarkSupportabilityEvidence:
    portfolio_dates = _date_set(portfolio_daily_results_df, PortfolioColumns.PERF_DATE.value)
    benchmark_dates = _date_set(benchmark_daily_returns_df, "date")
    calendar_alignment = _benchmark_calendar_alignment(
        portfolio_dates=portfolio_dates,
        benchmark_dates=benchmark_dates,
    )
    warning_codes = list(calendar_alignment.warning_codes)

    currency_state = _benchmark_currency_state(
        benchmark_request=benchmark_request,
        benchmark_daily_returns_df=benchmark_daily_returns_df,
        benchmark_return_source=benchmark_return_source,
        warning_codes=warning_codes,
    )
    if (
        performance_request.report_ccy
        and benchmark_request.benchmark_currency
        and performance_request.report_ccy != benchmark_request.benchmark_currency
    ):
        warning_codes.append("BENCHMARK_CURRENCY_DIFFERS_FROM_REPORTING_CURRENCY")

    return TWRBenchmarkSupportabilityEvidence(
        return_source=benchmark_return_source,
        input_mode=benchmark_input_mode,
        reporting_currency=performance_request.report_ccy,
        benchmark_currency=benchmark_request.benchmark_currency,
        currency_state=currency_state,
        calendar_alignment_state=calendar_alignment.state,
        portfolio_observation_count=len(calendar_alignment.portfolio_dates),
        benchmark_observation_count=len(calendar_alignment.benchmark_dates),
        overlapping_observation_count=len(calendar_alignment.overlapping_dates),
        missing_benchmark_date_count=len(calendar_alignment.missing_benchmark_dates),
        missing_benchmark_dates_sample=list(islice(calendar_alignment.missing_benchmark_dates, _DATE_SAMPLE_LIMIT)),
        extra_benchmark_date_count=len(calendar_alignment.extra_benchmark_dates),
        extra_benchmark_dates_sample=list(islice(calendar_alignment.extra_benchmark_dates, _DATE_SAMPLE_LIMIT)),
        warning_codes=warning_codes,
    )


def _date_set(df: pd.DataFrame, column: str) -> set[date]:
    if column not in df.columns or df.empty:
        return set()
    return observation_date_set(df[column])


def _benchmark_calendar_alignment(
    *,
    portfolio_dates: set[date],
    benchmark_dates: set[date],
) -> _BenchmarkCalendarAlignment:
    missing_benchmark_dates = sorted(portfolio_dates - benchmark_dates)
    extra_benchmark_dates = sorted(benchmark_dates - portfolio_dates)
    overlapping_dates = portfolio_dates & benchmark_dates
    state, warning_codes = _benchmark_calendar_alignment_state(
        portfolio_dates=portfolio_dates,
        benchmark_dates=benchmark_dates,
        overlapping_dates=overlapping_dates,
        missing_benchmark_dates=missing_benchmark_dates,
        extra_benchmark_dates=extra_benchmark_dates,
    )
    return _BenchmarkCalendarAlignment(
        state=state,
        portfolio_dates=portfolio_dates,
        benchmark_dates=benchmark_dates,
        overlapping_dates=overlapping_dates,
        missing_benchmark_dates=missing_benchmark_dates,
        extra_benchmark_dates=extra_benchmark_dates,
        warning_codes=warning_codes,
    )


def _benchmark_calendar_alignment_state(
    *,
    portfolio_dates: set[date],
    benchmark_dates: set[date],
    overlapping_dates: set[date],
    missing_benchmark_dates: list[date],
    extra_benchmark_dates: list[date],
) -> tuple[_CalendarAlignmentState, list[str]]:
    if _has_benchmark_calendar_no_overlap(
        portfolio_dates=portfolio_dates,
        benchmark_dates=benchmark_dates,
        overlapping_dates=overlapping_dates,
    ):
        return "no_overlap", ["BENCHMARK_CALENDAR_NO_OVERLAP"]
    if missing_benchmark_dates or extra_benchmark_dates:
        return "partial_overlap", ["BENCHMARK_CALENDAR_GAP"]
    return "aligned", []


def _has_benchmark_calendar_no_overlap(
    *,
    portfolio_dates: set[date],
    benchmark_dates: set[date],
    overlapping_dates: set[date],
) -> bool:
    return not overlapping_dates and bool(portfolio_dates or benchmark_dates)


def _benchmark_currency_state(
    *,
    benchmark_request: BenchmarkPerformanceRequest,
    benchmark_daily_returns_df: pd.DataFrame,
    benchmark_return_source: str,
    warning_codes: list[str],
) -> Literal["single_currency", "base_only", "fx_decomposed", "vendor_series_base_only"]:
    if benchmark_return_source == "vendor_series":
        warning_codes.append("BENCHMARK_VENDOR_SERIES_BASE_ONLY")
        return "vendor_series_base_only"

    if _has_benchmark_fx_decomposition(benchmark_daily_returns_df):
        return "fx_decomposed"

    component_currencies = _benchmark_component_currencies(benchmark_request)
    if component_currencies and component_currencies != {benchmark_request.benchmark_currency}:
        warning_codes.append("BENCHMARK_FX_DECOMPOSITION_UNAVAILABLE")
        return "base_only"
    return "single_currency"


def _benchmark_component_currencies(benchmark_request: BenchmarkPerformanceRequest) -> set[str]:
    return {
        observation.component_currency
        for observation in benchmark_request.component_observations
        if observation.component_currency is not None
    }


def _has_benchmark_fx_decomposition(benchmark_daily_returns_df: pd.DataFrame) -> bool:
    return bool(
        "benchmark_return_local" in benchmark_daily_returns_df.columns
        and "benchmark_return_fx" in benchmark_daily_returns_df.columns
        and benchmark_daily_returns_df["benchmark_return_local"].notna().any()
        and benchmark_daily_returns_df["benchmark_return_fx"].notna().any()
    )
