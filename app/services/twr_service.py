from __future__ import annotations

import pandas as pd
from fastapi import HTTPException, status

from adapters.api_adapter import (
    create_engine_config,
    create_engine_dataframe,
    format_breakdowns_for_response,
)
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.performance_diagnostics import build_performance_diagnostics, build_reset_events
from app.models.requests import PerformanceRequest
from app.models.responses import (
    PerformanceResponse,
    PortfolioReturnDecomposition,
    RelativePerformanceSummary,
    SinglePeriodPerformanceResult,
    TWRBenchmarkResponse,
)
from app.models.twr_requests import TWRInputMode
from app.services.benchmark_calculation_service import calculate_benchmark_artifacts
from app.services.execution_lifecycle_service import complete_execution_with_lineage
from app.services.execution_registry import execution_registry
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from engine.breakdown import generate_performance_breakdowns
from engine.compute import run_calculations
from engine.schema import PortfolioColumns


def _as_numeric(value: object, default=0):
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        return default
    return numeric


def _get_total_cum_ror(row: pd.Series | None, prefix: str = "") -> float:
    if row is None:
        return 0.0
    long_cum = _as_numeric(row.get(f"{prefix}long_cum_ror", 0))
    short_cum = _as_numeric(row.get(f"{prefix}short_cum_ror", 0))
    return ((1 + long_cum / 100) * (1 + short_cum / 100) - 1) * 100


def _calculate_total_return_from_reset_slice(
    df_slice: pd.DataFrame, daily_results_df: pd.DataFrame
) -> PortfolioReturnDecomposition:
    end_row = df_slice.iloc[-1]
    full_perf_dates = pd.to_datetime(daily_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
    slice_min_date = pd.to_datetime(df_slice[PortfolioColumns.PERF_DATE.value].min()).date()
    day_before_mask = full_perf_dates < slice_min_date
    day_before_row = daily_results_df[day_before_mask].iloc[-1] if day_before_mask.any() else None

    start_cum_base = _as_numeric(
        day_before_row[PortfolioColumns.FINAL_CUM_ROR.value] if day_before_row is not None else 0
    )
    end_cum_base = _as_numeric(end_row[PortfolioColumns.FINAL_CUM_ROR.value])

    start_base_denom = 1 + start_cum_base / 100
    if start_base_denom == 0:
        base_total = end_cum_base
    else:
        base_total = (((1 + end_cum_base / 100) / start_base_denom) - 1) * 100

    if "local_ror" not in df_slice.columns:
        return PortfolioReturnDecomposition(local=base_total, fx=0.0, base=base_total)

    start_cum_local = _get_total_cum_ror(day_before_row, "local_ror_")
    end_cum_local = _get_total_cum_ror(end_row, "local_ror_")

    start_local_denom = 1 + start_cum_local / 100
    if start_local_denom == 0:
        local_total = end_cum_local
    else:
        local_total = (((1 + end_cum_local / 100) / start_local_denom) - 1) * 100

    base_denom_for_fx = 1 + local_total / 100
    if base_denom_for_fx == 0:
        fx_total = 0.0
    else:
        fx_total = (((1 + base_total / 100) / base_denom_for_fx) - 1) * 100

    return PortfolioReturnDecomposition(local=local_total, fx=fx_total, base=base_total)


def _calculate_total_return_from_non_reset_slice(df_slice: pd.DataFrame) -> PortfolioReturnDecomposition:
    base_running = 1.0
    for value in df_slice[PortfolioColumns.DAILY_ROR.value].tolist():
        base_running *= 1 + (_as_numeric(value) / 100)
    base_total = _as_numeric((base_running - 1) * 100)

    if "local_ror" not in df_slice.columns:
        return PortfolioReturnDecomposition(local=base_total, fx=0.0, base=base_total)

    local_running = 1.0
    for value in df_slice["local_ror"].tolist():
        local_running *= 1 + (_as_numeric(value) / 100)
    local_total = _as_numeric((local_running - 1) * 100)
    base_denom_for_fx = 1 + local_total / 100
    if base_denom_for_fx == 0:
        fx_total = 0.0
    else:
        fx_total = _as_numeric((((1 + base_total / 100) / base_denom_for_fx) - 1) * 100)

    return PortfolioReturnDecomposition(local=local_total, fx=fx_total, base=base_total)


def _calculate_total_return_from_slice(
    df_slice: pd.DataFrame, daily_results_df: pd.DataFrame
) -> PortfolioReturnDecomposition:
    if df_slice.empty:
        return PortfolioReturnDecomposition(local=0.0, fx=0.0, base=0.0)

    if df_slice[PortfolioColumns.PERF_RESET.value].any():
        return _calculate_total_return_from_reset_slice(df_slice, daily_results_df)

    return _calculate_total_return_from_non_reset_slice(df_slice)


def _build_relative_performance_summary(
    *,
    portfolio_return: PortfolioReturnDecomposition,
    portfolio_cumulative_return_to_date: float,
    benchmark_return: float,
    benchmark_cumulative_return_to_date: float,
) -> RelativePerformanceSummary:
    arithmetic_relative_return = portfolio_return.base - (benchmark_return * 100)
    return RelativePerformanceSummary(
        arithmetic_relative_return=arithmetic_relative_return,
        cumulative_arithmetic_relative_return=(
            portfolio_cumulative_return_to_date - (benchmark_cumulative_return_to_date * 100)
        ),
    )


def _get_portfolio_cumulative_return_to_date(*, period_end_date, daily_results_df: pd.DataFrame) -> float:
    cumulative_rows = daily_results_df[
        daily_results_df[PortfolioColumns.PERF_DATE.value] <= period_end_date
    ]
    if cumulative_rows.empty:
        return 0.0
    return _calculate_total_return_from_slice(cumulative_rows, daily_results_df).base


def _get_benchmark_cumulative_return_to_date(
    *, period_end_date, benchmark_daily_returns_df: pd.DataFrame
) -> float:
    cumulative_rows = benchmark_daily_returns_df[benchmark_daily_returns_df["date"] <= period_end_date]
    if cumulative_rows.empty:
        return 0.0
    running = 1.0
    for benchmark_return in cumulative_rows["benchmark_return"]:
        running *= 1.0 + _as_numeric(benchmark_return)
    return running - 1.0


def calculate_twr_response(
    performance_request: PerformanceRequest,
    *,
    portfolio_id: str,
    input_mode: TWRInputMode,
    input_fingerprint: str,
    calculation_hash: str,
    engine_version: str,
    request_artifact_model,
    benchmark_request: BenchmarkPerformanceRequest | None = None,
    benchmark_input_mode: BenchmarkInputMode | None = None,
    resolved_benchmark_id: str | None = None,
    benchmark_return_source: BenchmarkReturnSource = BenchmarkReturnSource.CALCULATED,
) -> PerformanceResponse:
    execution_registry.start_stage(performance_request.calculation_id, "execution")

    daily_results_df: pd.DataFrame | None = None
    benchmark_artifacts = None
    try:
        periods_to_resolve = [analysis.period for analysis in performance_request.analyses]
        freqs_by_period = {analysis.period.value: analysis.frequencies for analysis in performance_request.analyses}

        as_of_date = performance_request.report_end_date
        resolved_periods = resolve_periods(periods_to_resolve, as_of_date, performance_request.performance_start_date)
        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        engine_config = create_engine_config(performance_request, master_start_date, master_end_date)
        engine_df = create_engine_dataframe([item.model_dump() for item in performance_request.valuation_points])
        daily_results_df, engine_diagnostics = run_calculations(engine_df, engine_config)
        benchmark_artifacts = (
            calculate_benchmark_artifacts(benchmark_request)
            if benchmark_request is not None
            else None
        )
    except Exception as exc:
        execution_registry.fail_stage(performance_request.calculation_id, "execution", str(exc))
        raise

    results_by_period = {}
    resolved_period_end_dates: dict[str, object] = {}
    daily_results_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
        daily_results_df[PortfolioColumns.PERF_DATE.value]
    ).dt.date

    for period in resolved_periods:
        period_slice_df = daily_results_df[
            (daily_results_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
            & (daily_results_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
        ].copy()

        if period_slice_df.empty:
            continue
        resolved_period_end_dates[period.name] = period.end_date

        requested_frequencies_for_period = freqs_by_period.get(period.name, [])
        breakdowns_data = generate_performance_breakdowns(
            period_slice_df,
            requested_frequencies_for_period,
            performance_request.annualization,
            performance_request.output.include_cumulative,
            performance_request.rounding_precision,
        )
        formatted_breakdowns = format_breakdowns_for_response(
            breakdowns_data, period_slice_df, performance_request.output.include_timeseries
        )

        period_return_summary = _calculate_total_return_from_slice(period_slice_df, daily_results_df)
        period_result = SinglePeriodPerformanceResult(
            breakdowns=formatted_breakdowns,
            portfolio_return=period_return_summary,
        )

        if performance_request.reset_policy.emit and engine_diagnostics.resets:
            period_result.reset_events = [
                event
                for event in build_reset_events(engine_diagnostics)
                if period.start_date <= event.date <= period.end_date
            ]

        results_by_period[period.name] = period_result

    benchmark_response = None
    if benchmark_request is not None and benchmark_artifacts is not None:
        effective_benchmark_mode = benchmark_input_mode or BenchmarkInputMode.STATELESS
        for period_name, period_result in results_by_period.items():
            benchmark_period = benchmark_artifacts.results_by_period.get(period_name)
            if benchmark_period is None or period_result.portfolio_return is None:
                continue
            period_result.relative_performance = _build_relative_performance_summary(
                portfolio_return=period_result.portfolio_return,
                portfolio_cumulative_return_to_date=_get_portfolio_cumulative_return_to_date(
                    period_end_date=resolved_period_end_dates[period_name],
                    daily_results_df=daily_results_df,
                ),
                benchmark_return=benchmark_period.benchmark_return,
                benchmark_cumulative_return_to_date=_get_benchmark_cumulative_return_to_date(
                    period_end_date=resolved_period_end_dates[period_name],
                    benchmark_daily_returns_df=benchmark_artifacts.daily_returns_df,
                ),
            )
        benchmark_response = TWRBenchmarkResponse(
            benchmark_id=resolved_benchmark_id or benchmark_request.benchmark_id,
            benchmark_currency=benchmark_request.benchmark_currency,
            input_mode=effective_benchmark_mode,
            return_source=benchmark_return_source,
            results_by_period=benchmark_artifacts.results_by_period,
        )

    response_model = PerformanceResponse(
        calculation_id=performance_request.calculation_id,
        portfolio_id=portfolio_id,
        input_mode=input_mode,
        results_by_period=results_by_period,
        benchmark=benchmark_response,
        meta=Meta(
            calculation_id=performance_request.calculation_id,
            engine_version=engine_version,
            precision_mode=performance_request.precision_mode,
            calendar=performance_request.calendar,
            annualization=performance_request.annualization,
            periods={
                "requested": [analysis.period.value for analysis in performance_request.analyses],
                "master_start": str(master_start_date),
                "master_end": str(master_end_date),
            },
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            report_ccy=performance_request.report_ccy,
        ),
        diagnostics=Diagnostics(
            **build_performance_diagnostics(engine_diagnostics).model_dump(mode="python"),
        ),
        audit=Audit(
            counts={"input_rows": len(performance_request.valuation_points)},
            residual_applied_bp=0,
        ),
    )

    execution_details = {
        "periods_resolved": len(results_by_period),
        "daily_rows": len(daily_results_df),
    }
    calculation_details = {
        "daily_results.csv": daily_results_df,
    }
    if benchmark_artifacts is not None:
        execution_details["benchmark_daily_returns"] = len(benchmark_artifacts.daily_returns_df)
        execution_details["benchmark_component_contributions"] = len(
            benchmark_artifacts.component_contributions_df
        )
        calculation_details["benchmark_daily_returns.csv"] = benchmark_artifacts.daily_returns_df
        calculation_details["benchmark_component_contributions.csv"] = (
            benchmark_artifacts.component_contributions_df
        )

    complete_execution_with_lineage(
        calculation_id=performance_request.calculation_id,
        calculation_type="TWR",
        request_model=request_artifact_model,
        response_model=response_model,
        execution_details=execution_details,
        calculation_details=calculation_details,
    )
    return response_model
