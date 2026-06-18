from __future__ import annotations

import math
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TypeAlias

import pandas as pd

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.benchmark_responses import (
    DailyBenchmarkComponentContribution,
    DailyBenchmarkReturn,
    SinglePeriodBenchmarkResult,
)
from app.models.responses import (
    ComparativeAnalyticsBlock,
    ComparativeBreakdown,
    ComparativeBreakdownItem,
    ComparativeReturnValue,
    ComparativeSummary,
)
from app.services.analytics_observation_dates import observation_date_series, observation_timestamp_series
from common.enums import Frequency
from core.periods import ResolvedPeriod, resolve_periods
from engine.benchmarks import benchmark_return_points_to_dataframe, calculate_benchmark_returns

PERCENT_SCALE = 100.0
PercentagePoint: TypeAlias = float


@dataclass(frozen=True)
class BenchmarkCalculationArtifacts:
    results_by_period: dict[str, SinglePeriodBenchmarkResult]
    daily_returns_df: pd.DataFrame
    component_contributions_df: pd.DataFrame
    effective_period_start: date
    max_weight_sum_deviation: float
    notes: list[str]


@dataclass(frozen=True)
class _BenchmarkSourceArtifacts:
    daily_returns_df: pd.DataFrame
    component_contributions_df: pd.DataFrame
    effective_period_start: date
    max_weight_sum_deviation: float
    notes: list[str]


@dataclass(frozen=True)
class _BenchmarkPeriodTimeseriesRecords:
    daily_returns: list[DailyBenchmarkReturn] | None
    component_contributions: list[DailyBenchmarkComponentContribution] | None


def _build_benchmark_source_artifacts(benchmark_request: BenchmarkPerformanceRequest) -> _BenchmarkSourceArtifacts:
    if benchmark_request.return_source == "calculated":
        engine_result = calculate_benchmark_returns(benchmark_request.component_observations)
        return _BenchmarkSourceArtifacts(
            daily_returns_df=engine_result.daily_returns_df.copy(),
            component_contributions_df=engine_result.component_contributions_df.copy(),
            effective_period_start=engine_result.effective_period_start,
            max_weight_sum_deviation=engine_result.max_weight_sum_deviation,
            notes=list(engine_result.notes),
        )

    return _BenchmarkSourceArtifacts(
        daily_returns_df=benchmark_return_points_to_dataframe(benchmark_request.benchmark_return_points).copy(),
        component_contributions_df=pd.DataFrame(
            columns=["date", "component_id", "weight_bop", "component_return", "contribution"]
        ),
        effective_period_start=benchmark_request.benchmark_start_date,
        max_weight_sum_deviation=0.0,
        notes=["Benchmark returns were sourced from vendor series because return_source=vendor_series was requested."],
    )


def _normalize_benchmark_source_artifact_dates(
    *,
    daily_returns_df: pd.DataFrame,
    component_contributions_df: pd.DataFrame,
) -> None:
    daily_returns_df["date"] = observation_date_series(daily_returns_df["date"])
    if not component_contributions_df.empty:
        component_contributions_df["date"] = observation_date_series(component_contributions_df["date"])


def calculate_benchmark_artifacts(
    benchmark_request: BenchmarkPerformanceRequest,
    *,
    input_mode: str | None = None,
) -> BenchmarkCalculationArtifacts:
    periods_to_resolve = [analysis.period for analysis in benchmark_request.analyses]
    requested_frequencies_by_period = {
        analysis.period.value: list(analysis.frequencies) for analysis in benchmark_request.analyses
    }
    resolved_periods = resolve_periods(
        periods_to_resolve,
        benchmark_request.report_end_date,
        benchmark_request.benchmark_start_date,
        explicit_start_date=benchmark_request.report_start_date,
    )

    source_artifacts = _build_benchmark_source_artifacts(benchmark_request)
    daily_returns_df = source_artifacts.daily_returns_df
    component_contributions_df = source_artifacts.component_contributions_df

    _normalize_benchmark_source_artifact_dates(
        daily_returns_df=daily_returns_df,
        component_contributions_df=component_contributions_df,
    )

    return BenchmarkCalculationArtifacts(
        results_by_period=_benchmark_results_by_period(
            resolved_periods=resolved_periods,
            daily_returns_df=daily_returns_df,
            component_contributions_df=component_contributions_df,
            benchmark_request=benchmark_request,
            requested_frequencies_by_period=requested_frequencies_by_period,
            input_mode=input_mode,
        ),
        daily_returns_df=daily_returns_df,
        component_contributions_df=component_contributions_df,
        effective_period_start=source_artifacts.effective_period_start,
        max_weight_sum_deviation=source_artifacts.max_weight_sum_deviation,
        notes=source_artifacts.notes,
    )


def _benchmark_results_by_period(
    *,
    resolved_periods: list[ResolvedPeriod],
    daily_returns_df: pd.DataFrame,
    component_contributions_df: pd.DataFrame,
    benchmark_request: BenchmarkPerformanceRequest,
    requested_frequencies_by_period: dict[str, list[Frequency]],
    input_mode: str | None,
) -> dict[str, SinglePeriodBenchmarkResult]:
    results_by_period: dict[str, SinglePeriodBenchmarkResult] = {}
    for period in resolved_periods:
        period_result = _benchmark_period_result(
            period=period,
            daily_returns_df=daily_returns_df,
            component_contributions_df=component_contributions_df,
            benchmark_request=benchmark_request,
            frequencies=requested_frequencies_by_period.get(period.name, []),
            input_mode=input_mode,
        )
        if period_result is not None:
            results_by_period[period.name] = period_result
    return results_by_period


def _benchmark_period_daily_returns(
    *,
    period: ResolvedPeriod,
    daily_returns_df: pd.DataFrame,
) -> pd.DataFrame | None:
    period_daily_df = daily_returns_df[
        (daily_returns_df["date"] >= period.start_date) & (daily_returns_df["date"] <= period.end_date)
    ].copy()
    if period_daily_df.empty:
        return None
    period_daily_df = period_daily_df.sort_values("date").reset_index(drop=True)
    running = Decimal("1")
    period_cumulative: list[Decimal] = []
    for benchmark_return in period_daily_df["benchmark_return"]:
        running *= Decimal("1") + Decimal(str(benchmark_return))
        period_cumulative.append(running - Decimal("1"))
    period_daily_df["cumulative_return"] = period_cumulative
    return period_daily_df


def _benchmark_period_result(
    *,
    period: ResolvedPeriod,
    daily_returns_df: pd.DataFrame,
    component_contributions_df: pd.DataFrame,
    benchmark_request: BenchmarkPerformanceRequest,
    frequencies: list[Frequency],
    input_mode: str | None,
) -> SinglePeriodBenchmarkResult | None:
    period_daily_df = _benchmark_period_daily_returns(period=period, daily_returns_df=daily_returns_df)
    if period_daily_df is None:
        return None

    period_component_df = component_contributions_df[
        (component_contributions_df["date"] >= period.start_date)
        & (component_contributions_df["date"] <= period.end_date)
    ].copy()
    timeseries_records = _benchmark_period_timeseries_records(
        period_daily_df=period_daily_df,
        period_component_df=period_component_df,
        include_timeseries=benchmark_request.output.include_timeseries,
    )
    return SinglePeriodBenchmarkResult(
        benchmark=ComparativeAnalyticsBlock(
            summary=ComparativeSummary(
                period_return=_calculate_benchmark_return_from_slice(period_daily_df),
                cumulative_return=_calculate_benchmark_return_from_slice(
                    daily_returns_df[daily_returns_df["date"] <= period.end_date].copy()
                ),
            ),
            breakdowns=_build_benchmark_breakdowns(
                period_daily_df=period_daily_df,
                frequencies=frequencies,
            ),
            benchmark_id=benchmark_request.benchmark_id,
            benchmark_currency=benchmark_request.benchmark_currency,
            input_mode=input_mode,
            return_source=benchmark_request.return_source,
        ),
        daily_returns=timeseries_records.daily_returns,
        component_contributions=timeseries_records.component_contributions,
    )


def _benchmark_period_timeseries_records(
    *,
    period_daily_df: pd.DataFrame,
    period_component_df: pd.DataFrame,
    include_timeseries: bool,
) -> _BenchmarkPeriodTimeseriesRecords:
    if not include_timeseries:
        return _BenchmarkPeriodTimeseriesRecords(daily_returns=None, component_contributions=None)
    return _BenchmarkPeriodTimeseriesRecords(
        daily_returns=_daily_return_records(period_daily_df),
        component_contributions=_component_contribution_records(period_component_df)
        if not period_component_df.empty
        else None,
    )


def _calculate_benchmark_return_from_slice(period_daily_df: pd.DataFrame) -> ComparativeReturnValue:
    return ComparativeReturnValue(
        base=_series_return(period_daily_df["benchmark_return"]),
        local=_optional_benchmark_return_component(period_daily_df, "benchmark_return_local"),
        fx=_optional_benchmark_return_component(period_daily_df, "benchmark_return_fx"),
    )


def _optional_benchmark_return_component(period_daily_df: pd.DataFrame, column: str) -> PercentagePoint | None:
    if column not in period_daily_df.columns or not period_daily_df[column].notna().any():
        return None
    return _series_return(period_daily_df[column])


def _build_benchmark_breakdowns(
    *,
    period_daily_df: pd.DataFrame,
    frequencies: list[Frequency],
) -> ComparativeBreakdown:
    breakdowns: ComparativeBreakdown = {}
    sorted_period_df = period_daily_df.copy()
    sorted_period_df["date"] = observation_date_series(sorted_period_df["date"])
    sorted_period_df = sorted_period_df.sort_values("date").reset_index(drop=True)
    for frequency in frequencies:
        if frequency == Frequency.DAILY:
            breakdowns[frequency] = _daily_benchmark_breakdown_items(sorted_period_df)
            continue
        items: list[ComparativeBreakdownItem] = []
        for frequency_df in _group_benchmark_breakdown_rows(sorted_period_df=sorted_period_df, frequency=frequency):
            items.append(
                _build_benchmark_breakdown_item(
                    sorted_period_df=sorted_period_df,
                    frequency_df=frequency_df,
                    frequency=frequency,
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _daily_benchmark_breakdown_items(sorted_period_df: pd.DataFrame) -> list[ComparativeBreakdownItem]:
    running_base = Decimal("1")
    running_local = Decimal("1")
    running_fx = Decimal("1")
    has_local = _has_return_component(sorted_period_df, "benchmark_return_local")
    has_fx = _has_return_component(sorted_period_df, "benchmark_return_fx")
    items: list[ComparativeBreakdownItem] = []
    for row in sorted_period_df.to_dict("records"):
        benchmark_return = Decimal(str(row["benchmark_return"]))
        running_base *= Decimal("1") + benchmark_return
        running_local, cumulative_local = _next_optional_running_return(
            running=running_local,
            row=row,
            column="benchmark_return_local",
            enabled=has_local,
        )
        running_fx, cumulative_fx = _next_optional_running_return(
            running=running_fx,
            row=row,
            column="benchmark_return_fx",
            enabled=has_fx,
        )
        period_end = row["date"]
        cumulative_return = ComparativeReturnValue(
            base=_scale_decimal_return(running_base - Decimal("1")),
            local=cumulative_local,
            fx=cumulative_fx,
        )
        items.append(
            ComparativeBreakdownItem(
                period=_benchmark_breakdown_label(frequency=Frequency.DAILY, period_end=period_end),
                period_start=period_end,
                period_end=period_end,
                period_return=_daily_benchmark_period_return(row, has_local=has_local, has_fx=has_fx),
                cumulative_return=cumulative_return,
            )
        )
    return items


def _daily_benchmark_period_return(
    row: Mapping[Hashable, object],
    *,
    has_local: bool,
    has_fx: bool,
) -> ComparativeReturnValue:
    return ComparativeReturnValue(
        base=_scale_decimal_return(Decimal(str(row["benchmark_return"]))),
        local=_optional_scaled_return_component(row, "benchmark_return_local") if has_local else None,
        fx=_optional_scaled_return_component(row, "benchmark_return_fx") if has_fx else None,
    )


def _next_optional_running_return(
    *,
    running: Decimal,
    row: Mapping[Hashable, object],
    column: str,
    enabled: bool,
) -> tuple[Decimal, float | None]:  # monetary-float-allow
    if not enabled:
        return running, None
    next_running = running * (Decimal("1") + Decimal(str(row[column])))
    return next_running, _scale_decimal_return(next_running - Decimal("1"))


def _has_return_component(df: pd.DataFrame, column: str) -> bool:
    return bool(column in df.columns and df[column].notna().any())


def _group_benchmark_breakdown_rows(*, sorted_period_df: pd.DataFrame, frequency: Frequency) -> list[pd.DataFrame]:
    if frequency == Frequency.DAILY:
        return _daily_benchmark_breakdown_rows(sorted_period_df)
    return _resampled_benchmark_breakdown_rows(sorted_period_df=sorted_period_df, frequency=frequency)


def _daily_benchmark_breakdown_rows(sorted_period_df: pd.DataFrame) -> list[pd.DataFrame]:
    return [pd.DataFrame([row]).reset_index(drop=True) for _, row in sorted_period_df.iterrows()]


def _resampled_benchmark_breakdown_rows(
    *,
    sorted_period_df: pd.DataFrame,
    frequency: Frequency,
) -> list[pd.DataFrame]:
    local_df = sorted_period_df.copy()
    local_df["date"] = observation_timestamp_series(local_df["date"])
    indexed = local_df.set_index(local_df["date"])
    freq_map = {
        Frequency.WEEKLY: "W-FRI",
        Frequency.MONTHLY: "ME",
        Frequency.QUARTERLY: "QE",
        Frequency.YEARLY: "YE",
    }
    return [
        group_df.copy().reset_index(drop=True).assign(date=lambda frame: observation_date_series(frame["date"]))
        for _, group_df in indexed.resample(freq_map[frequency])
        if not group_df.empty
    ]


def _build_benchmark_breakdown_item(
    *,
    sorted_period_df: pd.DataFrame,
    frequency_df: pd.DataFrame,
    frequency: Frequency,
) -> ComparativeBreakdownItem:
    frequency_df = frequency_df.sort_values("date").reset_index(drop=True)
    period_end = frequency_df["date"].iloc[-1]
    cumulative_df = sorted_period_df[sorted_period_df["date"] <= period_end].copy()
    return ComparativeBreakdownItem(
        period=_benchmark_breakdown_label(frequency=frequency, period_end=period_end),
        period_start=frequency_df["date"].iloc[0],
        period_end=period_end,
        period_return=_calculate_benchmark_return_from_slice(frequency_df),
        cumulative_return=_calculate_benchmark_return_from_slice(cumulative_df),
    )


def _benchmark_breakdown_label(*, frequency: Frequency, period_end: date) -> str:
    if frequency == Frequency.MONTHLY:
        return f"{period_end.year:04d}-{period_end.month:02d}"
    if frequency == Frequency.QUARTERLY:
        return f"{period_end.year:04d}-Q{((period_end.month - 1) // 3) + 1}"
    if frequency == Frequency.YEARLY:
        return f"{period_end.year:04d}"
    return period_end.isoformat()


def _series_return(return_series: pd.Series) -> float:
    running = Decimal("1")
    for value in return_series:
        running *= Decimal("1") + Decimal(str(value))
    return float((running - Decimal("1")) * Decimal(str(PERCENT_SCALE)))


def _scale_decimal_return(value: Decimal) -> float:  # monetary-float-allow
    return float(value * Decimal(str(PERCENT_SCALE)))  # monetary-float-allow


def _optional_scaled_return_component(  # monetary-float-allow
    row: Mapping[Hashable, object], column: str
) -> float | None:
    value = row.get(column)
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):  # monetary-float-allow
        return None
    return _scale_decimal_return(Decimal(str(value)))


def _scale_percent(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value)) * PERCENT_SCALE
    except (TypeError, ValueError):
        return None


def _daily_return_records(df: pd.DataFrame) -> list[DailyBenchmarkReturn]:
    return [
        DailyBenchmarkReturn(
            date=row["date"],
            benchmark_return=float(row["benchmark_return"]) * PERCENT_SCALE,
            cumulative_return=float(row["cumulative_return"]) * PERCENT_SCALE,
            benchmark_return_local=_scale_percent(row.get("benchmark_return_local")),
            benchmark_return_fx=_scale_percent(row.get("benchmark_return_fx")),
        )
        for _, row in df.iterrows()
    ]


def _component_contribution_records(df: pd.DataFrame) -> list[DailyBenchmarkComponentContribution]:
    return [
        DailyBenchmarkComponentContribution(
            date=row["date"],
            component_id=row["component_id"],
            component_currency=row.get("component_currency"),
            weight_bop=float(row["weight_bop"]),
            component_return=float(row["component_return"]) * PERCENT_SCALE,
            component_return_local=_scale_percent(row.get("component_return_local")),
            component_return_fx=_scale_percent(row.get("component_return_fx")),
            contribution=float(row["contribution"]) * PERCENT_SCALE,
            local_contribution=_scale_percent(row.get("local_contribution")),
            fx_contribution=_scale_percent(row.get("fx_contribution")),
        )
        for _, row in df.iterrows()
    ]
