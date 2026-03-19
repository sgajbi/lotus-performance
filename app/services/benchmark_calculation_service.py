from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.benchmark_responses import (
    DailyBenchmarkComponentContribution,
    DailyBenchmarkReturn,
    SinglePeriodBenchmarkResult,
)
from core.periods import resolve_periods
from engine.benchmarks import benchmark_return_points_to_dataframe, calculate_benchmark_returns


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
        daily_returns_df = benchmark_return_points_to_dataframe(
            benchmark_request.benchmark_return_points
        ).copy()
        component_contributions_df = pd.DataFrame(
            columns=["date", "component_id", "weight_bop", "component_return", "contribution"]
        )
        notes = [
            "Benchmark returns were sourced from vendor series because return_source=vendor_series was requested."
        ]
        effective_period_start = benchmark_request.benchmark_start_date
        max_weight_sum_deviation = 0.0

    daily_returns_df["date"] = pd.to_datetime(daily_returns_df["date"]).dt.date
    if not component_contributions_df.empty:
        component_contributions_df["date"] = pd.to_datetime(component_contributions_df["date"]).dt.date

    results_by_period: dict[str, SinglePeriodBenchmarkResult] = {}
    for period in resolved_periods:
        period_daily_df = daily_returns_df[
            (daily_returns_df["date"] >= period.start_date)
            & (daily_returns_df["date"] <= period.end_date)
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

        results_by_period[period.name] = SinglePeriodBenchmarkResult(
            benchmark_return=_series_return(period_daily_df["benchmark_return"]),
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


def _series_return(return_series: pd.Series) -> float:
    running = Decimal("1")
    for value in return_series:
        running *= Decimal("1") + Decimal(str(value))
    return float(running - Decimal("1"))


def _daily_return_records(df: pd.DataFrame) -> list[DailyBenchmarkReturn]:
    return [
        DailyBenchmarkReturn(
            date=row["date"],
            benchmark_return=float(row["benchmark_return"]),
            cumulative_return=float(row["cumulative_return"]),
            benchmark_return_local=(
                float(row["benchmark_return_local"]) if pd.notna(row.get("benchmark_return_local")) else None
            ),
            benchmark_return_fx=(
                float(row["benchmark_return_fx"]) if pd.notna(row.get("benchmark_return_fx")) else None
            ),
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
            component_return=float(row["component_return"]),
            component_return_local=(
                float(row["component_return_local"]) if pd.notna(row.get("component_return_local")) else None
            ),
            component_return_fx=(
                float(row["component_return_fx"]) if pd.notna(row.get("component_return_fx")) else None
            ),
            contribution=float(row["contribution"]),
            local_contribution=(
                float(row["local_contribution"]) if pd.notna(row.get("local_contribution")) else None
            ),
            fx_contribution=(
                float(row["fx_contribution"]) if pd.notna(row.get("fx_contribution")) else None
            ),
        )
        for _, row in df.iterrows()
    ]
