from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

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
    PerformanceCalculationSupportability,
    PerformanceResponse,
    PortfolioReturnDecomposition,
    ResetEvent,
    SinglePeriodPerformanceResult,
    TWRBenchmarkContext,
)
from app.models.twr_requests import TWRInputMode
from app.services.analytics_numeric import numeric_value
from app.services.analytics_observation_dates import (
    normalize_observation_date,
    observation_date_series,
    observation_timestamp_series,
)
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR
from app.services.benchmark_calculation_service import BenchmarkCalculationArtifacts, calculate_benchmark_artifacts
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.execution_lifecycle_service import complete_execution_with_lineage
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from common.enums import Frequency
from core.envelope import Audit, Diagnostics, Meta
from core.periods import ResolvedPeriod, resolve_periods
from engine.breakdown import generate_performance_breakdowns
from engine.compute import run_calculations
from engine.diagnostics import EngineDiagnostics
from engine.schema import PortfolioColumns


def _as_numeric(value: object, default=0):
    return numeric_value(value, default=default)


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
    full_perf_dates = observation_date_series(daily_results_df[PortfolioColumns.PERF_DATE.value])
    slice_min_date = normalize_observation_date(df_slice[PortfolioColumns.PERF_DATE.value].min())
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


from app.services.twr_benchmark_supportability import build_twr_benchmark_supportability_evidence  # noqa: E402


@dataclass(frozen=True)
class _DailyCalculationEvidenceInputs:
    begin_mv: float
    end_mv: float
    bod_cf: float
    eod_cf: float
    management_fees: float
    signed_adjusted_capital: float
    adjusted_capital: float
    performance_pnl: float  # monetary-float-allow
    daily_return: float  # monetary-float-allow


@dataclass(frozen=True)
class _DailyCalculationEvidenceClassification:
    status: str
    linkability_status: str
    episode_status: str
    reason_codes: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class _TWRExecutionPeriodScope:
    resolved_periods: list[ResolvedPeriod]
    freqs_by_period: dict[str, list[Frequency]]
    master_start_date: date
    master_end_date: date


@dataclass(frozen=True)
class _TWRExecutionCalculation:
    resolved_periods: list[ResolvedPeriod]
    freqs_by_period: dict[str, list[Frequency]]
    master_start_date: date
    master_end_date: date
    daily_results_df: pd.DataFrame
    engine_diagnostics: EngineDiagnostics
    benchmark_artifacts: BenchmarkCalculationArtifacts | None


@dataclass(frozen=True)
class _TWRBenchmarkPeriodContext:
    artifacts: BenchmarkCalculationArtifacts
    request: BenchmarkPerformanceRequest
    input_mode: BenchmarkInputMode | None
    resolved_benchmark_id: str | None
    return_source: BenchmarkReturnSource
    master_start_date: date


def _daily_calculation_evidence_inputs(
    row: pd.Series,
    *,
    metric_basis: str,
) -> _DailyCalculationEvidenceInputs:
    begin_mv = _as_numeric(row.get(PortfolioColumns.BEGIN_MV.value, 0))
    bod_cf = _as_numeric(row.get(PortfolioColumns.BOD_CF.value, 0))
    eod_cf = _as_numeric(row.get(PortfolioColumns.EOD_CF.value, 0))
    management_fees = _as_numeric(row.get(PortfolioColumns.MGMT_FEES.value, 0))
    end_mv = _as_numeric(row.get(PortfolioColumns.END_MV.value, 0))
    signed_adjusted_capital = begin_mv + bod_cf
    adjusted_capital = abs(signed_adjusted_capital)
    performance_pnl = end_mv - bod_cf - begin_mv - eod_cf
    if metric_basis == "NET":
        performance_pnl += management_fees
    return _DailyCalculationEvidenceInputs(
        begin_mv=begin_mv,
        end_mv=end_mv,
        bod_cf=bod_cf,
        eod_cf=eod_cf,
        management_fees=management_fees,
        signed_adjusted_capital=signed_adjusted_capital,
        adjusted_capital=adjusted_capital,
        performance_pnl=performance_pnl,
        daily_return=_as_numeric(row.get(PortfolioColumns.DAILY_ROR.value, 0)),
    )


def _classify_daily_calculation_evidence(
    row: pd.Series,
    *,
    inputs: _DailyCalculationEvidenceInputs,
) -> _DailyCalculationEvidenceClassification:
    classification = _initial_daily_calculation_classification(inputs)
    classification = _with_effective_period_classification(row, classification=classification)
    classification = _with_reset_no_investment_classification(row, classification=classification)
    classification = _with_cashflow_reason_codes(inputs, classification=classification)
    return _with_daily_return_linkability(inputs, classification=classification)


def _initial_daily_calculation_classification(
    inputs: _DailyCalculationEvidenceInputs,
) -> _DailyCalculationEvidenceClassification:
    status = "calculated" if inputs.adjusted_capital != 0 else "not_calculated"
    linkability_status = "linkable"
    reason_codes = ["FLOW_NEUTRALIZED_DAILY_RETURN"]
    warnings: list[str] = []

    if inputs.adjusted_capital == 0:
        reason_codes.append("ZERO_ADJUSTED_CAPITAL")
        warnings.append("ZERO_ADJUSTED_CAPITAL")
        linkability_status = "not_calculated"
    elif inputs.signed_adjusted_capital < 0:
        reason_codes.append("NEGATIVE_ADJUSTED_CAPITAL_INPUT")
        warnings.append("NEGATIVE_ADJUSTED_CAPITAL_INPUT")
    elif inputs.adjusted_capital < 1e-8:
        reason_codes.append("NEAR_ZERO_ADJUSTED_CAPITAL")
        warnings.append("NEAR_ZERO_ADJUSTED_CAPITAL")

    return _DailyCalculationEvidenceClassification(
        status=status,
        linkability_status=linkability_status,
        episode_status="open",
        reason_codes=reason_codes,
        warnings=warnings,
    )


def _with_effective_period_classification(
    row: pd.Series,
    *,
    classification: _DailyCalculationEvidenceClassification,
) -> _DailyCalculationEvidenceClassification:
    perf_date_raw = row.get(PortfolioColumns.PERF_DATE.value)
    effective_start_raw = row.get(PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value)
    if perf_date_raw is None or effective_start_raw is None or pd.isna(effective_start_raw):
        return classification

    perf_date = normalize_observation_date(perf_date_raw)
    effective_start = normalize_observation_date(effective_start_raw)
    if perf_date >= effective_start:
        return classification

    return _DailyCalculationEvidenceClassification(
        status="not_calculated",
        linkability_status="not_calculated",
        episode_status="not_in_period",
        reason_codes=[*classification.reason_codes, "BEFORE_EFFECTIVE_PERIOD_START"],
        warnings=[*classification.warnings, "BEFORE_EFFECTIVE_PERIOD_START"],
    )


def _with_reset_no_investment_classification(
    row: pd.Series,
    *,
    classification: _DailyCalculationEvidenceClassification,
) -> _DailyCalculationEvidenceClassification:
    linkability_status = classification.linkability_status
    episode_status = classification.episode_status
    reason_codes = list(classification.reason_codes)
    if _as_numeric(row.get(PortfolioColumns.PERF_RESET.value, 0)) == 1:
        reason_codes.append("RESET_DAY")
        episode_status = "reset_boundary"
        if linkability_status == "linkable":
            linkability_status = "reset_boundary"
    if _as_numeric(row.get(PortfolioColumns.NIP.value, 0)) == 1:
        reason_codes.append("NO_INVESTMENT_PERIOD")
        if episode_status == "open":
            episode_status = "no_investment"
        if linkability_status == "linkable":
            linkability_status = "not_calculated"

    return _DailyCalculationEvidenceClassification(
        status=classification.status,
        linkability_status=linkability_status,
        episode_status=episode_status,
        reason_codes=reason_codes,
        warnings=classification.warnings,
    )


def _with_cashflow_reason_codes(
    inputs: _DailyCalculationEvidenceInputs,
    *,
    classification: _DailyCalculationEvidenceClassification,
) -> _DailyCalculationEvidenceClassification:
    reason_codes = list(classification.reason_codes)
    if inputs.end_mv == 0 and inputs.eod_cf < 0:
        reason_codes.append("FULL_WITHDRAWAL_DAY")
    if inputs.begin_mv <= 0 and inputs.bod_cf > 0:
        reason_codes.append("REFUNDING_DAY")

    return _DailyCalculationEvidenceClassification(
        status=classification.status,
        linkability_status=classification.linkability_status,
        episode_status=classification.episode_status,
        reason_codes=reason_codes,
        warnings=classification.warnings,
    )


def _with_daily_return_linkability(
    inputs: _DailyCalculationEvidenceInputs,
    *,
    classification: _DailyCalculationEvidenceClassification,
) -> _DailyCalculationEvidenceClassification:
    linkability_status = classification.linkability_status
    reason_codes = list(classification.reason_codes)
    warnings = list(classification.warnings)
    if inputs.daily_return == -100:
        reason_codes.append("FULL_LOSS_RETURN")
        warnings.append("FULL_LOSS_RETURN")
        if linkability_status == "linkable":
            linkability_status = "not_linkable"
    elif inputs.daily_return < -100:
        reason_codes.append("BELOW_FULL_LOSS_RETURN")
        warnings.append("BELOW_FULL_LOSS_RETURN")
        if linkability_status == "linkable":
            linkability_status = "not_linkable"

    return _DailyCalculationEvidenceClassification(
        status=classification.status,
        linkability_status=linkability_status,
        episode_status=classification.episode_status,
        reason_codes=reason_codes,
        warnings=warnings,
    )


def _build_daily_calculation_evidence(
    row: pd.Series,
    *,
    metric_basis: str,
) -> object:
    from app.models.responses import TWRDailyCalculationEvidence

    inputs = _daily_calculation_evidence_inputs(row, metric_basis=metric_basis)
    classification = _classify_daily_calculation_evidence(row, inputs=inputs)

    return TWRDailyCalculationEvidence(
        begin_mv=inputs.begin_mv,
        end_mv=inputs.end_mv,
        bod_cf=inputs.bod_cf,
        eod_cf=inputs.eod_cf,
        external_inflows=sum(value for value in (inputs.bod_cf, inputs.eod_cf) if value > 0),
        external_outflows=abs(sum(value for value in (inputs.bod_cf, inputs.eod_cf) if value < 0)),
        management_fees=inputs.management_fees,
        signed_adjusted_capital=inputs.signed_adjusted_capital,
        adjusted_capital=inputs.adjusted_capital,
        performance_pnl=inputs.performance_pnl,
        daily_return=inputs.daily_return,
        status=classification.status,
        linkability_status=classification.linkability_status,
        episode_status=classification.episode_status,
        reason_codes=classification.reason_codes,
        warnings=classification.warnings,
    )


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
        return _daily_frequency_windows(period_df, date_column=date_column)

    local_df = period_df.copy()
    local_df[date_column] = observation_timestamp_series(local_df[date_column])
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
        group_df[date_column] = observation_date_series(group_df[date_column])
        start_date = group_df[date_column].min()
        end_date = group_df[date_column].max()
        label = _resampled_frequency_window_label(frequency, period_timestamp)
        windows.append((label, start_date, end_date, group_df))
    return windows


def _daily_frequency_windows(
    period_df: pd.DataFrame,
    *,
    date_column: str,
) -> list[tuple[str, object, object, pd.DataFrame]]:
    daily_windows: list[tuple[str, object, object, pd.DataFrame]] = []
    for point_date, group_df in period_df.groupby(date_column, sort=True):
        label = point_date.isoformat() if hasattr(point_date, "isoformat") else str(point_date)
        daily_windows.append((label, point_date, point_date, group_df.copy()))
    return daily_windows


def _resampled_frequency_window_label(frequency: Frequency, period_timestamp: pd.Timestamp) -> str:
    if frequency == Frequency.MONTHLY:
        return period_timestamp.strftime("%Y-%m")
    if frequency == Frequency.QUARTERLY:
        return f"{period_timestamp.year}-Q{period_timestamp.quarter}"
    if frequency == Frequency.YEARLY:
        return period_timestamp.strftime("%Y")
    return period_timestamp.strftime("%Y-%m-%d")


def _build_portfolio_breakdowns(
    *,
    period_slice_df: pd.DataFrame,
    daily_results_df: pd.DataFrame,
    requested_frequencies: list[Frequency],
    breakdowns_data: dict[Frequency, list[dict]],
    include_timeseries: bool,
    metric_basis: str,
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
            summary_data = summary_items[index]["summary"] if index < len(summary_items) else {}
            items.append(
                _build_portfolio_breakdown_item(
                    period_slice_df=period_slice_df,
                    daily_results_df=daily_results_df,
                    label=label,
                    start_date=start_date,
                    end_date=end_date,
                    frequency=frequency,
                    frequency_df=frequency_df,
                    summary_data=summary_data,
                    include_timeseries=include_timeseries,
                    metric_basis=metric_basis,
                )
            )
        breakdowns[frequency] = items
    return breakdowns


def _build_portfolio_breakdown_item(
    *,
    period_slice_df: pd.DataFrame,
    daily_results_df: pd.DataFrame,
    label: str,
    start_date,
    end_date,
    frequency: Frequency,
    frequency_df: pd.DataFrame,
    summary_data: dict,
    include_timeseries: bool,
    metric_basis: str,
) -> ComparativeBreakdownItem:
    cumulative_df = period_slice_df[period_slice_df[PortfolioColumns.PERF_DATE.value] <= end_date].copy()
    return ComparativeBreakdownItem(
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
        calculation_evidence=(
            _build_daily_calculation_evidence(frequency_df.iloc[0], metric_basis=metric_basis)
            if frequency == Frequency.DAILY and not frequency_df.empty
            else None
        ),
    )


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
    master_start_date,
    period_end_date,
    benchmark_daily_returns_df: pd.DataFrame,
) -> ComparativeReturnValue:
    cumulative_rows = benchmark_daily_returns_df[
        (benchmark_daily_returns_df["date"] >= master_start_date)
        & (benchmark_daily_returns_df["date"] <= period_end_date)
    ].copy()
    return _calculate_benchmark_return_from_slice(cumulative_rows)


def _resolve_twr_supportability(
    *,
    performance_request: PerformanceRequest,
    results_by_period: dict[str, SinglePeriodPerformanceResult],
    daily_results_df: pd.DataFrame | None,
    benchmark_row_count: int,
) -> PerformanceCalculationSupportability:
    input_row_count = len(performance_request.valuation_points)
    latest_observation_date = None
    if daily_results_df is not None and not daily_results_df.empty:
        latest_observation_date = daily_results_df[PortfolioColumns.PERF_DATE.value].max()
    return build_calculation_supportability(
        input_row_count=input_row_count,
        resolved_period_count=len(results_by_period),
        latest_observation_date=latest_observation_date,
        report_end_date=performance_request.report_end_date,
        benchmark_row_count=benchmark_row_count,
        minimum_input_row_count=2,
        source_quality_evidence=performance_request.source_quality_evidence,
    )


def _run_twr_execution_calculation(
    *,
    performance_request: PerformanceRequest,
    benchmark_request: BenchmarkPerformanceRequest | None,
) -> _TWRExecutionCalculation:
    period_scope = _resolve_twr_execution_period_scope(performance_request)
    engine_config = create_engine_config(
        performance_request,
        period_scope.master_start_date,
        period_scope.master_end_date,
    )
    engine_df = create_engine_dataframe([item.model_dump() for item in performance_request.valuation_points])
    daily_results_df, engine_diagnostics = run_calculations(engine_df, engine_config)
    benchmark_artifacts = calculate_benchmark_artifacts(benchmark_request) if benchmark_request is not None else None

    return _TWRExecutionCalculation(
        resolved_periods=period_scope.resolved_periods,
        freqs_by_period=period_scope.freqs_by_period,
        master_start_date=period_scope.master_start_date,
        master_end_date=period_scope.master_end_date,
        daily_results_df=daily_results_df,
        engine_diagnostics=engine_diagnostics,
        benchmark_artifacts=benchmark_artifacts,
    )


def _resolve_twr_execution_period_scope(performance_request: PerformanceRequest) -> _TWRExecutionPeriodScope:
    periods_to_resolve = [analysis.period for analysis in performance_request.analyses]
    freqs_by_period = {analysis.period.value: analysis.frequencies for analysis in performance_request.analyses}

    resolved_periods = resolve_periods(
        periods_to_resolve,
        performance_request.report_end_date,
        performance_request.performance_start_date,
        explicit_start_date=performance_request.report_start_date,
    )
    if not resolved_periods:
        raise HTTPException(status_code=400, detail="No valid periods could be resolved.")

    return _TWRExecutionPeriodScope(
        resolved_periods=resolved_periods,
        freqs_by_period=freqs_by_period,
        master_start_date=min(p.start_date for p in resolved_periods),
        master_end_date=max(p.end_date for p in resolved_periods),
    )


def _build_twr_results_by_period(
    *,
    performance_request: PerformanceRequest,
    resolved_periods: list[ResolvedPeriod],
    freqs_by_period: dict[str, list[Frequency]],
    daily_results_df: pd.DataFrame,
    engine_diagnostics: EngineDiagnostics,
    benchmark_artifacts: BenchmarkCalculationArtifacts | None,
    benchmark_request: BenchmarkPerformanceRequest | None,
    benchmark_input_mode: BenchmarkInputMode | None,
    resolved_benchmark_id: str | None,
    benchmark_return_source: BenchmarkReturnSource,
    master_start_date: date,
) -> dict[str, SinglePeriodPerformanceResult]:
    results_by_period: dict[str, SinglePeriodPerformanceResult] = {}
    benchmark_context = (
        _TWRBenchmarkPeriodContext(
            artifacts=benchmark_artifacts,
            request=benchmark_request,
            input_mode=benchmark_input_mode,
            resolved_benchmark_id=resolved_benchmark_id,
            return_source=benchmark_return_source,
            master_start_date=master_start_date,
        )
        if benchmark_artifacts is not None and benchmark_request is not None
        else None
    )
    daily_results_df[PortfolioColumns.PERF_DATE.value] = observation_date_series(
        daily_results_df[PortfolioColumns.PERF_DATE.value]
    )

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
        portfolio = _build_twr_portfolio_period_block(
            performance_request=performance_request,
            period=period,
            period_slice_df=period_slice_df,
            daily_results_df=daily_results_df,
            requested_frequencies=requested_frequencies_for_period,
            breakdowns_data=breakdowns_data,
        )

        period_result = SinglePeriodPerformanceResult(portfolio=portfolio)

        if benchmark_context is not None:
            period_result.benchmark, period_result.relative_performance = _build_twr_benchmark_period_blocks(
                period=period,
                requested_frequencies=requested_frequencies_for_period,
                portfolio=period_result.portfolio,
                context=benchmark_context,
            )

        reset_events = _twr_period_reset_events(
            performance_request=performance_request,
            engine_diagnostics=engine_diagnostics,
            period=period,
        )
        if reset_events is not None:
            period_result.reset_events = reset_events

        results_by_period[period.name] = period_result

    return results_by_period


def _twr_period_reset_events(
    *,
    performance_request: PerformanceRequest,
    engine_diagnostics: EngineDiagnostics,
    period: ResolvedPeriod,
) -> list[ResetEvent] | None:
    if not performance_request.reset_policy.emit or not engine_diagnostics.resets:
        return None
    return [
        event for event in build_reset_events(engine_diagnostics) if period.start_date <= event.date <= period.end_date
    ]


def _build_twr_portfolio_period_block(
    *,
    performance_request: PerformanceRequest,
    period: ResolvedPeriod,
    period_slice_df: pd.DataFrame,
    daily_results_df: pd.DataFrame,
    requested_frequencies: list[Frequency],
    breakdowns_data: dict[Frequency, list[dict]],
) -> ComparativeAnalyticsBlock:
    portfolio_period_return = _calculate_total_return_from_slice(period_slice_df, daily_results_df)
    portfolio_breakdowns = _build_portfolio_breakdowns(
        period_slice_df=period_slice_df,
        daily_results_df=daily_results_df,
        requested_frequencies=requested_frequencies,
        breakdowns_data=breakdowns_data,
        include_timeseries=performance_request.output.include_timeseries,
        metric_basis=performance_request.metric_basis,
    )
    return ComparativeAnalyticsBlock(
        summary=ComparativeSummary(
            period_return=_build_return_value_from_decomposition(portfolio_period_return),
            cumulative_return=_get_portfolio_cumulative_return_to_date(
                period_end_date=period.end_date,
                daily_results_df=daily_results_df,
            ),
        ),
        breakdowns=portfolio_breakdowns,
    )


def _build_twr_benchmark_period_blocks(
    *,
    period: ResolvedPeriod,
    requested_frequencies: list[Frequency],
    portfolio: ComparativeAnalyticsBlock,
    context: _TWRBenchmarkPeriodContext,
) -> tuple[ComparativeAnalyticsBlock | None, ComparativeAnalyticsBlock | None]:
    benchmark_period_df = context.artifacts.daily_returns_df[
        (context.artifacts.daily_returns_df["date"] >= period.start_date)
        & (context.artifacts.daily_returns_df["date"] <= period.end_date)
    ].copy()
    if benchmark_period_df.empty:
        return None, None

    benchmark_period_return = _calculate_benchmark_return_from_slice(benchmark_period_df)
    benchmark_breakdowns = _build_benchmark_breakdowns(
        period_daily_df=benchmark_period_df,
        requested_frequencies=requested_frequencies,
    )
    benchmark = ComparativeAnalyticsBlock(
        summary=ComparativeSummary(
            period_return=benchmark_period_return,
            cumulative_return=_get_benchmark_cumulative_return_to_date(
                master_start_date=context.master_start_date,
                period_end_date=period.end_date,
                benchmark_daily_returns_df=context.artifacts.daily_returns_df,
            ),
        ),
        breakdowns=benchmark_breakdowns,
        benchmark_id=context.resolved_benchmark_id or context.request.benchmark_id,
        benchmark_currency=context.request.benchmark_currency,
        input_mode=(context.input_mode or BenchmarkInputMode.STATELESS).value,
        return_source=context.return_source.value,
    )
    relative = ComparativeAnalyticsBlock(
        summary=ComparativeSummary(
            period_return=_build_relative_return_value(portfolio.summary.period_return, benchmark_period_return),
            cumulative_return=_build_relative_return_value(
                portfolio.summary.cumulative_return or portfolio.summary.period_return,
                benchmark.summary.cumulative_return or benchmark_period_return,
            ),
        ),
        breakdowns=_build_relative_breakdowns(
            portfolio_breakdowns=portfolio.breakdowns,
            benchmark_breakdowns=benchmark_breakdowns,
        ),
    )
    return benchmark, relative


def _build_twr_benchmark_context(
    *,
    performance_request: PerformanceRequest,
    benchmark_request: BenchmarkPerformanceRequest | None,
    benchmark_artifacts: BenchmarkCalculationArtifacts | None,
    benchmark_input_mode: BenchmarkInputMode | None,
    resolved_benchmark_id: str | None,
    benchmark_return_source: BenchmarkReturnSource,
    daily_results_df: pd.DataFrame,
) -> TWRBenchmarkContext | None:
    if benchmark_artifacts is None or benchmark_request is None:
        return None

    return TWRBenchmarkContext(
        benchmark_id=resolved_benchmark_id or benchmark_request.benchmark_id,
        benchmark_currency=benchmark_request.benchmark_currency,
        input_mode=(benchmark_input_mode or BenchmarkInputMode.STATELESS).value,
        return_source=benchmark_return_source.value,
        supportability_evidence=build_twr_benchmark_supportability_evidence(
            performance_request=performance_request,
            benchmark_request=benchmark_request,
            portfolio_daily_results_df=daily_results_df,
            benchmark_daily_returns_df=benchmark_artifacts.daily_returns_df,
            benchmark_input_mode=(benchmark_input_mode or BenchmarkInputMode.STATELESS).value,
            benchmark_return_source=benchmark_return_source.value,
        ),
    )


def _build_twr_response_model(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    input_mode: TWRInputMode,
    input_fingerprint: str,
    calculation_hash: str,
    engine_version: str,
    calculation: _TWRExecutionCalculation,
    results_by_period: dict[str, SinglePeriodPerformanceResult],
    benchmark_context: TWRBenchmarkContext | None,
    calculation_supportability: PerformanceCalculationSupportability,
) -> PerformanceResponse:
    return PerformanceResponse(
        calculation_id=performance_request.calculation_id,
        portfolio_id=portfolio_id,
        input_mode=input_mode,
        benchmark_context=benchmark_context,
        calculation_supportability=calculation_supportability,
        results_by_period=results_by_period,
        meta=Meta(
            calculation_id=performance_request.calculation_id,
            engine_version=engine_version,
            precision_mode=performance_request.precision_mode,
            calendar=performance_request.calendar,
            annualization=performance_request.annualization,
            periods={
                "requested": [analysis.period.value for analysis in performance_request.analyses],
                "master_start": str(calculation.master_start_date),
                "master_end": str(calculation.master_end_date),
            },
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            report_ccy=performance_request.report_ccy,
        ),
        diagnostics=Diagnostics(
            **build_performance_diagnostics(calculation.engine_diagnostics).model_dump(mode="python"),
        ),
        audit=Audit(
            counts={"input_rows": len(performance_request.valuation_points)},
            residual_applied_bp=0,
        ),
    )


def _build_twr_lineage_details(
    *,
    daily_results_df: pd.DataFrame,
    results_by_period: dict[str, SinglePeriodPerformanceResult],
    benchmark_artifacts: BenchmarkCalculationArtifacts | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    execution_details: dict[str, Any] = {
        "periods_resolved": len(results_by_period),
        "daily_rows": len(daily_results_df),
    }
    calculation_details: dict[str, Any] = {
        "daily_results.csv": daily_results_df,
    }
    if benchmark_artifacts is not None:
        execution_details["benchmark_daily_returns"] = len(benchmark_artifacts.daily_returns_df)
        execution_details["benchmark_component_contributions"] = len(benchmark_artifacts.component_contributions_df)
        calculation_details["benchmark_daily_returns.csv"] = benchmark_artifacts.daily_returns_df
        calculation_details["benchmark_component_contributions.csv"] = benchmark_artifacts.component_contributions_df
    return execution_details, calculation_details


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
    execution_registry.start_stage(performance_request.calculation_id, EXECUTION_STAGE_EXECUTION)

    try:
        calculation = _run_twr_execution_calculation(
            performance_request=performance_request,
            benchmark_request=benchmark_request,
        )
    except Exception as exc:
        execution_registry.fail_stage(performance_request.calculation_id, EXECUTION_STAGE_EXECUTION, str(exc))
        raise

    results_by_period = _build_twr_results_by_period(
        performance_request=performance_request,
        resolved_periods=calculation.resolved_periods,
        freqs_by_period=calculation.freqs_by_period,
        daily_results_df=calculation.daily_results_df,
        engine_diagnostics=calculation.engine_diagnostics,
        benchmark_artifacts=calculation.benchmark_artifacts,
        benchmark_request=benchmark_request,
        benchmark_input_mode=benchmark_input_mode,
        resolved_benchmark_id=resolved_benchmark_id,
        benchmark_return_source=normalized_benchmark_return_source,
        master_start_date=calculation.master_start_date,
    )

    calculation_supportability = _resolve_twr_supportability(
        performance_request=performance_request,
        results_by_period=results_by_period,
        daily_results_df=calculation.daily_results_df,
        benchmark_row_count=(
            len(calculation.benchmark_artifacts.daily_returns_df) if calculation.benchmark_artifacts is not None else 0
        ),
    )
    record_supportability_metric(
        operation="twr",
        supportability=calculation_supportability,
    )
    benchmark_context = _build_twr_benchmark_context(
        performance_request=performance_request,
        benchmark_request=benchmark_request,
        benchmark_artifacts=calculation.benchmark_artifacts,
        benchmark_input_mode=benchmark_input_mode,
        resolved_benchmark_id=resolved_benchmark_id,
        benchmark_return_source=normalized_benchmark_return_source,
        daily_results_df=calculation.daily_results_df,
    )
    response_model = _build_twr_response_model(
        performance_request=performance_request,
        portfolio_id=portfolio_id,
        input_mode=input_mode,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        engine_version=engine_version,
        calculation=calculation,
        results_by_period=results_by_period,
        benchmark_context=benchmark_context,
        calculation_supportability=calculation_supportability,
    )

    execution_details, calculation_details = _build_twr_lineage_details(
        daily_results_df=calculation.daily_results_df,
        results_by_period=results_by_period,
        benchmark_artifacts=calculation.benchmark_artifacts,
    )

    complete_execution_with_lineage(
        calculation_id=performance_request.calculation_id,
        calculation_type=ANALYTICS_WORKFLOW_TWR,
        request_model=request_artifact_model,
        response_model=response_model,
        execution_details=execution_details,
        calculation_details=calculation_details,
    )
    return response_model
