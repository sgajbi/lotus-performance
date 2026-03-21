from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast

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
from common.enums import Frequency
from core.periods import resolve_periods
from engine.benchmarks import benchmark_return_points_to_dataframe, calculate_benchmark_returns

PERCENT_SCALE = 100.0


@dataclass(frozen=True)
class BenchmarkCalculationArtifacts:
    results_by_period: dict[str, SinglePeriodBenchmarkResult]
    daily_returns_df: pd.DataFrame
    component_contributions_df: pd.DataFrame
    effective_period_start: date
    max_weight_sum_deviation: float
    notes: list[str]


def calculate_benchmark_artifacts(
    benchmark_request: BenchmarkPerformanceRequest,
) -> BenchmarkCalculationArtifacts:
    periods_to_resolve = [analysis.period for analysis in benchmark_request.analyses]
    requested_frequencies_by_period = {
        analysis.period.value: list(analysis.frequencies) for analysis in benchmark_request.analyses
    }
    resolved_periods = resolve_periods(
        periods_to_resolve,
        benchmark_request.report_end_date,
        benchmark_request.benchmark_start_date,
    )

    if benchmark_request.return_source == "calculated":
        engine_result = calculate_benchmark_returns(benchmark_request.component_observations)
        daily_returns_df = engine_result.daily_returns_df.copy()
        component_contributions_df = engine_result.component_contributions_df.copy()
        notes = list(engine_result.notes)
        effective_period_start = engine_result.effective_period_start
        max_weight_sum_deviation = engine_result.max_weight_sum_deviation
    else:
        daily_returns_df = benchmark_return_points_to_dataframe(benchmark_request.benchmark_return_points).copy()
        component_contributions_df = pd.DataFrame(
            columns=["date", "component_id", "weight_bop", "component_return", "contribution"]
        )
        notes = ["Benchmark returns were sourced from vendor series because return_source=vendor_series was requested."]
        effective_period_start = benchmark_request.benchmark_start_date
        max_weight_sum_deviation = 0.0

    daily_returns_df["date"] = pd.to_datetime(daily_returns_df["date"]).dt.date
    if not component_contributions_df.empty:
        component_contributions_df["date"] = pd.to_datetime(component_contributions_df["date"]).dt.date

    results_by_period: dict[str, SinglePeriodBenchmarkResult] = {}
    for period in resolved_periods:
        period_daily_df = daily_returns_df[
            (daily_returns_df["date"] >= period.start_date) & (daily_returns_df["date"] <= period.end_date)
        ].copy()
        if period_daily_df.empty:
            continue
        period_daily_df = period_daily_df.sort_values("date").reset_index(drop=True)
        running = Decimal("1")
        period_cumulative: list[Decimal] = []
        for benchmark_return in period_daily_df["benchmark_return"]:
            running *= Decimal("1") + Decimal(str(benchmark_return))
            period_cumulative.append(running - Decimal("1"))
        period_daily_df["cumulative_return"] = period_cumulative

        period_component_df = component_contributions_df[
            (component_contributions_df["date"] >= period.start_date)
            & (component_contributions_df["date"] <= period.end_date)
        ].copy()
        benchmark_period_return = _calculate_benchmark_return_from_slice(period_daily_df)
        benchmark_breakdowns = _build_benchmark_breakdowns(
            period_daily_df=period_daily_df,
            frequencies=requested_frequencies_by_period.get(period.name, []),
        )

        results_by_period[period.name] = SinglePeriodBenchmarkResult(
            benchmark=ComparativeAnalyticsBlock(
                summary=ComparativeSummary(
                    period_return=benchmark_period_return,
                    cumulative_return=_calculate_benchmark_return_from_slice(
                        daily_returns_df[daily_returns_df["date"] <= period.end_date].copy()
                    ),
                ),
                breakdowns=benchmark_breakdowns,
                benchmark_id=benchmark_request.benchmark_id,
                benchmark_currency=benchmark_request.benchmark_currency,
                input_mode=None,
                return_source=benchmark_request.return_source,
            ),
            daily_returns=_daily_return_records(period_daily_df)
            if benchmark_request.output.include_timeseries
            else None,
            component_contributions=_component_contribution_records(period_component_df)
            if benchmark_request.output.include_timeseries and not period_component_df.empty
            else None,
        )

    return BenchmarkCalculationArtifacts(
        results_by_period=results_by_period,
        daily_returns_df=daily_returns_df,
        component_contributions_df=component_contributions_df,
        effective_period_start=effective_period_start,
        max_weight_sum_deviation=max_weight_sum_deviation,
        notes=notes,
    )


def _calculate_benchmark_return_from_slice(period_daily_df: pd.DataFrame) -> ComparativeReturnValue:
    local = None
    fx = None
    if "benchmark_return_local" in period_daily_df.columns and period_daily_df["benchmark_return_local"].notna().any():
        local = _series_return(period_daily_df["benchmark_return_local"])
    if "benchmark_return_fx" in period_daily_df.columns and period_daily_df["benchmark_return_fx"].notna().any():
        fx = _series_return(period_daily_df["benchmark_return_fx"])
    return ComparativeReturnValue(
        base=_series_return(period_daily_df["benchmark_return"]),
        local=local,
        fx=fx,
    )


def _build_benchmark_breakdowns(
    *,
    period_daily_df: pd.DataFrame,
    frequencies: list[Frequency],
) -> ComparativeBreakdown:
    breakdowns: ComparativeBreakdown = {}
    sorted_period_df = period_daily_df.sort_values("date").reset_index(drop=True)
    for frequency in frequencies:
        items: list[ComparativeBreakdownItem] = []
        if frequency == Frequency.DAILY:
            grouped_rows = [(row["date"], pd.DataFrame([row])) for _, row in sorted_period_df.iterrows()]
        else:
            local_df = sorted_period_df.copy()
            local_df["date"] = pd.to_datetime(local_df["date"])
            indexed = local_df.set_index(local_df["date"])
            freq_map = {
                Frequency.WEEKLY: "W-FRI",
                Frequency.MONTHLY: "ME",
                Frequency.QUARTERLY: "QE",
                Frequency.YEARLY: "YE",
            }
            grouped_rows = [
                (cast(pd.Timestamp, group_start).date(), group_df.copy())
                for group_start, group_df in indexed.resample(freq_map[frequency])
                if not group_df.empty
            ]
        for _, frequency_df in grouped_rows:
            if frequency != Frequency.DAILY:
                frequency_df = frequency_df.reset_index(drop=True)
                frequency_df["date"] = pd.to_datetime(frequency_df["date"]).dt.date
            frequency_df = frequency_df.sort_values("date").reset_index(drop=True)
            period_end = frequency_df["date"].iloc[-1]
            cumulative_df = sorted_period_df[sorted_period_df["date"] <= period_end].copy()
            if frequency == Frequency.DAILY:
                label = period_end.isoformat()
            elif frequency == Frequency.MONTHLY:
                label = f"{period_end.year:04d}-{period_end.month:02d}"
            elif frequency == Frequency.QUARTERLY:
                label = f"{period_end.year:04d}-Q{((period_end.month - 1) // 3) + 1}"
            elif frequency == Frequency.YEARLY:
                label = f"{period_end.year:04d}"
            else:
                label = period_end.isoformat()
            items.append(
                ComparativeBreakdownItem(
                    period=label,
                    period_start=frequency_df["date"].iloc[0],
                    period_end=period_end,
                    period_return=_calculate_benchmark_return_from_slice(frequency_df),
                    cumulative_return=_calculate_benchmark_return_from_slice(cumulative_df),
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _series_return(return_series: pd.Series) -> float:
    running = Decimal("1")
    for value in return_series:
        running *= Decimal("1") + Decimal(str(value))
    return float((running - Decimal("1")) * Decimal(str(PERCENT_SCALE)))


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
