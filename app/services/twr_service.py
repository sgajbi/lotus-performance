from __future__ import annotations

from decimal import Decimal

import pandas as pd
from fastapi import HTTPException

from adapters.api_adapter import create_engine_config, create_engine_dataframe
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.performance_diagnostics import build_performance_diagnostics, build_reset_events
from app.models.requests import PerformanceRequest
from app.models.responses import (
    ComparativeAnalyticsBlock,
    ComparativeBreakdownItem,
    ComparativeReturnValue,
    ComparativeSummary,
    PerformanceResponse,
    PortfolioReturnDecomposition,
    SinglePeriodPerformanceResult,
    TWRBenchmarkContext,
)
from app.models.twr_requests import TWRInputMode
from app.services.benchmark_calculation_service import calculate_benchmark_artifacts
from app.services.execution_lifecycle_service import complete_execution_with_lineage
from app.services.execution_registry import execution_registry
from common.enums import Frequency
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


def _build_return_value(
    base: float,
    *,
    local: float | None = None,
    fx: float | None = None,
) -> ComparativeReturnValue:
    return ComparativeReturnValue(base=base, local=local, fx=fx)


def _build_return_value_from_decomposition(
    decomposition: PortfolioReturnDecomposition,
) -> ComparativeReturnValue:
    return _build_return_value(
        decomposition.base,
        local=decomposition.local,
        fx=decomposition.fx,
    )


def _link_return_series(series: pd.Series) -> float:
    running = Decimal("1")
    for value in series.tolist():
        running *= Decimal("1") + Decimal(str(_as_numeric(value)))
    return float((running - Decimal("1")) * Decimal("100"))


def _calculate_benchmark_return_from_slice(period_daily_df: pd.DataFrame) -> ComparativeReturnValue:
    local = None
    fx = None
    if "benchmark_return_local" in period_daily_df.columns and period_daily_df["benchmark_return_local"].notna().any():
        local = _link_return_series(period_daily_df["benchmark_return_local"])
    if "benchmark_return_fx" in period_daily_df.columns and period_daily_df["benchmark_return_fx"].notna().any():
        fx = _link_return_series(period_daily_df["benchmark_return_fx"])
    return _build_return_value(
        _link_return_series(period_daily_df["benchmark_return"]),
        local=local,
        fx=fx,
    )


def _build_relative_return_value(
    portfolio_value: ComparativeReturnValue,
    benchmark_value: ComparativeReturnValue,
) -> ComparativeReturnValue:
    return ComparativeReturnValue(
        base=portfolio_value.base - benchmark_value.base,
        local=(
            None
            if portfolio_value.local is None or benchmark_value.local is None
            else portfolio_value.local - benchmark_value.local
        ),
        fx=(
            None
            if portfolio_value.fx is None or benchmark_value.fx is None
            else portfolio_value.fx - benchmark_value.fx
        ),
    )


def _iter_frequency_windows(
    period_df: pd.DataFrame,
    *,
    date_column: str,
    frequency: Frequency,
) -> list[tuple[str, object, object, pd.DataFrame]]:
    if period_df.empty:
        return []
    if frequency == Frequency.DAILY:
        daily_windows: list[tuple[str, object, object, pd.DataFrame]] = []
        for point_date, group_df in period_df.groupby(date_column, sort=True):
            label = point_date.isoformat() if hasattr(point_date, "isoformat") else str(point_date)
            daily_windows.append((label, point_date, point_date, group_df.copy()))
        return daily_windows

    local_df = period_df.copy()
    local_df[date_column] = pd.to_datetime(local_df[date_column])
    indexed = local_df.set_index(local_df[date_column])
    freq_map = {
        Frequency.WEEKLY: "W-FRI",
        Frequency.MONTHLY: "ME",
        Frequency.QUARTERLY: "QE",
        Frequency.YEARLY: "YE",
    }

    windows: list[tuple[str, object, object, pd.DataFrame]] = []
    for raw_period_timestamp, group_df in indexed.resample(freq_map[frequency]):
        if group_df.empty:
            continue
        period_timestamp = pd.Timestamp(str(raw_period_timestamp))
        group_df = group_df.copy()
        group_df[date_column] = pd.to_datetime(group_df[date_column]).dt.date
        start_date = group_df[date_column].min()
        end_date = group_df[date_column].max()
        if frequency == Frequency.MONTHLY:
            label = period_timestamp.strftime("%Y-%m")
        elif frequency == Frequency.QUARTERLY:
            label = f"{period_timestamp.year}-Q{period_timestamp.quarter}"
        elif frequency == Frequency.YEARLY:
            label = period_timestamp.strftime("%Y")
        else:
            label = period_timestamp.strftime("%Y-%m-%d")
        windows.append((label, start_date, end_date, group_df))
    return windows


def _build_portfolio_breakdowns(
    *,
    period_slice_df: pd.DataFrame,
    daily_results_df: pd.DataFrame,
    requested_frequencies: list[Frequency],
    breakdowns_data: dict[Frequency, list[dict]],
    include_timeseries: bool,
) -> dict[Frequency, list[ComparativeBreakdownItem]]:
    breakdowns: dict[Frequency, list[ComparativeBreakdownItem]] = {}
    for frequency in requested_frequencies:
        items: list[ComparativeBreakdownItem] = []
        window_items = _iter_frequency_windows(
            period_slice_df,
            date_column=PortfolioColumns.PERF_DATE.value,
            frequency=frequency,
        )
        summary_items = breakdowns_data.get(frequency, [])
        for index, (label, start_date, end_date, frequency_df) in enumerate(window_items):
            cumulative_df = period_slice_df[period_slice_df[PortfolioColumns.PERF_DATE.value] <= end_date].copy()
            summary_data = summary_items[index]["summary"] if index < len(summary_items) else {}
            items.append(
                ComparativeBreakdownItem(
                    period=label,
                    period_start=start_date,
                    period_end=end_date,
                    period_return=_build_return_value_from_decomposition(
                        _calculate_total_return_from_slice(frequency_df, daily_results_df)
                    ),
                    cumulative_return=_build_return_value_from_decomposition(
                        _calculate_total_return_from_slice(cumulative_df, daily_results_df)
                    ),
                    annualized_return=(
                        _build_return_value(summary_data["annualized_return_pct"])
                        if summary_data.get("annualized_return_pct") is not None
                        else None
                    ),
                    daily_data=(
                        [frequency_df.iloc[0].to_dict()]
                        if include_timeseries and frequency == Frequency.DAILY and not frequency_df.empty
                        else None
                    ),
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _build_benchmark_breakdowns(
    *,
    period_daily_df: pd.DataFrame,
    requested_frequencies: list[Frequency],
) -> dict[Frequency, list[ComparativeBreakdownItem]]:
    breakdowns: dict[Frequency, list[ComparativeBreakdownItem]] = {}
    for frequency in requested_frequencies:
        items: list[ComparativeBreakdownItem] = []
        for label, start_date, end_date, frequency_df in _iter_frequency_windows(
            period_daily_df,
            date_column="date",
            frequency=frequency,
        ):
            cumulative_df = period_daily_df[period_daily_df["date"] <= end_date].copy()
            items.append(
                ComparativeBreakdownItem(
                    period=label,
                    period_start=start_date,
                    period_end=end_date,
                    period_return=_calculate_benchmark_return_from_slice(frequency_df),
                    cumulative_return=_calculate_benchmark_return_from_slice(cumulative_df),
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _build_relative_breakdowns(
    *,
    portfolio_breakdowns: dict[Frequency, list[ComparativeBreakdownItem]],
    benchmark_breakdowns: dict[Frequency, list[ComparativeBreakdownItem]],
) -> dict[Frequency, list[ComparativeBreakdownItem]]:
    breakdowns: dict[Frequency, list[ComparativeBreakdownItem]] = {}
    for frequency, portfolio_items in portfolio_breakdowns.items():
        benchmark_items = benchmark_breakdowns.get(frequency, [])
        items: list[ComparativeBreakdownItem] = []
        for portfolio_item, benchmark_item in zip(portfolio_items, benchmark_items):
            items.append(
                ComparativeBreakdownItem(
                    period=portfolio_item.period,
                    period_start=portfolio_item.period_start,
                    period_end=portfolio_item.period_end,
                    period_return=_build_relative_return_value(
                        portfolio_item.period_return,
                        benchmark_item.period_return,
                    ),
                    cumulative_return=(
                        None
                        if portfolio_item.cumulative_return is None or benchmark_item.cumulative_return is None
                        else _build_relative_return_value(
                            portfolio_item.cumulative_return,
                            benchmark_item.cumulative_return,
                        )
                    ),
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _get_portfolio_cumulative_return_to_date(
    *,
    period_end_date,
    daily_results_df: pd.DataFrame,
) -> ComparativeReturnValue:
    cumulative_rows = daily_results_df[daily_results_df[PortfolioColumns.PERF_DATE.value] <= period_end_date].copy()
    return _build_return_value_from_decomposition(_calculate_total_return_from_slice(cumulative_rows, daily_results_df))


def _get_benchmark_cumulative_return_to_date(
    *,
    period_end_date,
    benchmark_daily_returns_df: pd.DataFrame,
) -> ComparativeReturnValue:
    cumulative_rows = benchmark_daily_returns_df[benchmark_daily_returns_df["date"] <= period_end_date].copy()
    return _calculate_benchmark_return_from_slice(cumulative_rows)


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
    benchmark_return_source: BenchmarkReturnSource | str = BenchmarkReturnSource.CALCULATED,
) -> PerformanceResponse:
    normalized_benchmark_return_source = (
        benchmark_return_source
        if isinstance(benchmark_return_source, BenchmarkReturnSource)
        else BenchmarkReturnSource(str(benchmark_return_source))
    )
    execution_registry.start_stage(performance_request.calculation_id, "execution")

    daily_results_df: pd.DataFrame | None = None
    benchmark_artifacts = None
    try:
        periods_to_resolve = [analysis.period for analysis in performance_request.analyses]
        freqs_by_period = {analysis.period.value: analysis.frequencies for analysis in performance_request.analyses}

        as_of_date = performance_request.report_end_date
        resolved_periods = resolve_periods(periods_to_resolve, as_of_date, performance_request.performance_start_date)
        if not resolved_periods:
            raise HTTPException(status_code=400, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)

        engine_config = create_engine_config(performance_request, master_start_date, master_end_date)
        engine_df = create_engine_dataframe([item.model_dump() for item in performance_request.valuation_points])
        daily_results_df, engine_diagnostics = run_calculations(engine_df, engine_config)
        benchmark_artifacts = (
            calculate_benchmark_artifacts(benchmark_request) if benchmark_request is not None else None
        )
    except Exception as exc:
        execution_registry.fail_stage(performance_request.calculation_id, "execution", str(exc))
        raise

    results_by_period: dict[str, SinglePeriodPerformanceResult] = {}
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

        requested_frequencies_for_period = freqs_by_period.get(period.name, [])
        breakdowns_data = generate_performance_breakdowns(
            period_slice_df.copy(),
            requested_frequencies_for_period,
            performance_request.annualization,
            performance_request.output.include_cumulative,
            performance_request.rounding_precision,
        )
        portfolio_period_return = _calculate_total_return_from_slice(period_slice_df, daily_results_df)
        portfolio_breakdowns = _build_portfolio_breakdowns(
            period_slice_df=period_slice_df,
            daily_results_df=daily_results_df,
            requested_frequencies=requested_frequencies_for_period,
            breakdowns_data=breakdowns_data,
            include_timeseries=performance_request.output.include_timeseries,
        )

        period_result = SinglePeriodPerformanceResult(
            portfolio=ComparativeAnalyticsBlock(
                summary=ComparativeSummary(
                    period_return=_build_return_value_from_decomposition(portfolio_period_return),
                    cumulative_return=_get_portfolio_cumulative_return_to_date(
                        period_end_date=period.end_date,
                        daily_results_df=daily_results_df,
                    ),
                ),
                breakdowns=portfolio_breakdowns,
            ),
        )

        if benchmark_artifacts is not None and benchmark_request is not None:
            benchmark_period_df = benchmark_artifacts.daily_returns_df[
                (benchmark_artifacts.daily_returns_df["date"] >= period.start_date)
                & (benchmark_artifacts.daily_returns_df["date"] <= period.end_date)
            ].copy()
            if not benchmark_period_df.empty:
                benchmark_period_return = _calculate_benchmark_return_from_slice(benchmark_period_df)
                benchmark_breakdowns = _build_benchmark_breakdowns(
                    period_daily_df=benchmark_period_df,
                    requested_frequencies=requested_frequencies_for_period,
                )
                period_result.benchmark = ComparativeAnalyticsBlock(
                    summary=ComparativeSummary(
                        period_return=benchmark_period_return,
                        cumulative_return=_get_benchmark_cumulative_return_to_date(
                            period_end_date=period.end_date,
                            benchmark_daily_returns_df=benchmark_artifacts.daily_returns_df,
                        ),
                    ),
                    breakdowns=benchmark_breakdowns,
                    benchmark_id=resolved_benchmark_id or benchmark_request.benchmark_id,
                    benchmark_currency=benchmark_request.benchmark_currency,
                    input_mode=(benchmark_input_mode or BenchmarkInputMode.STATELESS).value,
                    return_source=normalized_benchmark_return_source.value,
                )
                period_result.relative_performance = ComparativeAnalyticsBlock(
                    summary=ComparativeSummary(
                        period_return=_build_relative_return_value(
                            period_result.portfolio.summary.period_return,
                            benchmark_period_return,
                        ),
                        cumulative_return=_build_relative_return_value(
                            period_result.portfolio.summary.cumulative_return
                            or period_result.portfolio.summary.period_return,
                            period_result.benchmark.summary.cumulative_return or benchmark_period_return,
                        ),
                    ),
                    breakdowns=_build_relative_breakdowns(
                        portfolio_breakdowns=portfolio_breakdowns,
                        benchmark_breakdowns=benchmark_breakdowns,
                    ),
                )

        if performance_request.reset_policy.emit and engine_diagnostics.resets:
            period_result.reset_events = [
                event
                for event in build_reset_events(engine_diagnostics)
                if period.start_date <= event.date <= period.end_date
            ]

        results_by_period[period.name] = period_result

    response_model = PerformanceResponse(
        calculation_id=performance_request.calculation_id,
        portfolio_id=portfolio_id,
        input_mode=input_mode,
        benchmark_context=(
            TWRBenchmarkContext(
                benchmark_id=resolved_benchmark_id or benchmark_request.benchmark_id,
                benchmark_currency=benchmark_request.benchmark_currency,
                input_mode=(benchmark_input_mode or BenchmarkInputMode.STATELESS).value,
                return_source=normalized_benchmark_return_source.value,
            )
            if benchmark_artifacts is not None and benchmark_request is not None
            else None
        ),
        results_by_period=results_by_period,
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
        execution_details["benchmark_component_contributions"] = len(benchmark_artifacts.component_contributions_df)
        calculation_details["benchmark_daily_returns.csv"] = benchmark_artifacts.daily_returns_df
        calculation_details["benchmark_component_contributions.csv"] = benchmark_artifacts.component_contributions_df

    complete_execution_with_lineage(
        calculation_id=performance_request.calculation_id,
        calculation_type="TWR",
        request_model=request_artifact_model,
        response_model=response_model,
        execution_details=execution_details,
        calculation_details=calculation_details,
    )
    return response_model
