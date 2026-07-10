from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    AverageWeightMethodologyStatus,
    ContributionResponse,
    ContributionSmoothingEvidence,
    DailyContribution,
    PositionContribution,
    PositionContributionSeries,
    SinglePeriodContributionResult,
)
from app.services.analytics_observation_dates import observation_date_series
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
from app.services.contribution_audit import AverageWeightShadowAuditState
from app.services.contribution_diagnostics import (
    _build_portfolio_engine_diagnostics,
    _calculate_grouped_return_reset_alignment_counts,
    _calculate_position_flow_balance_counts,
)
from app.services.contribution_evidence import (
    _count_contribution_input_rows,
    _latest_contribution_observation_date,
    _list_upstream_snapshots_for_contribution,
)
from app.services.contribution_methodology import (
    RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS,
    RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF,
    _assess_average_weight_shadow_cutover,
    _build_average_weight_methodology_status,
    _calculate_average_weight_sum_residual_bp,
    _calculate_average_weight_sum_residual_bp_from_ratio_series,
    _normalize_reset_aware_average_weight_mode,
)
from app.services.contribution_periods import (
    ContributionPeriodMethodologyContext,
    _build_contribution_period_methodology_context,
    _slice_contribution_period_frames,
)
from app.services.contribution_returns import (
    _calculate_reset_aware_period_portfolio_return,
    build_position_contributions,
    build_residual_adjusted_position_totals,
)
from app.services.contribution_series import (
    _build_hierarchy_from_adjusted_position_series,
    _build_residual_adjusted_daily_contribution_series,
    _build_residual_adjusted_position_timeseries,
)
from app.services.contribution_smoothing import (
    _build_contribution_smoothing_evidence,
    _count_carino_invalid_domain_days,
)
from app.services.contribution_source_economics import build_contribution_source_economics_evidence
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import is_mappable_application_error, safe_unexpected_failure_message
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from app.services.fail_fast_policy import enforce_core_analytics_fail_fast
from core.envelope import Audit, Meta
from core.errors import APIBadRequestError, APIError, APIInternalServerError
from core.periods import resolve_periods
from engine.contribution import (
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
)
from engine.schema import PortfolioColumns


@dataclass(frozen=True)
class _ContributionEngineInputs:
    periods_to_resolve: list[Any]
    resolved_periods: list[Any]
    master_start_date: date
    master_end_date: date
    instruments_df: Any
    portfolio_results_df: Any
    daily_contributions_df: Any


@dataclass(frozen=True)
class _ContributionPeriodResolution:
    periods_to_resolve: list[Any]
    resolved_periods: list[Any]
    master_start_date: date
    master_end_date: date


@dataclass(frozen=True)
class _ContributionPeriodResult:
    period_name: str
    result: SinglePeriodContributionResult
    average_weight_sum_residual_bp: int


@dataclass(frozen=True)
class _ContributionPeriodResults:
    results_by_period: dict[str, SinglePeriodContributionResult]
    average_weight_sum_residual_bp: int


@dataclass(frozen=True)
class _ContributionPeriodSupportability:
    average_weight_sum_residual_bp: int
    total_contribution: float
    smoothing_evidence: ContributionSmoothingEvidence | None
    average_weight_methodology_status: AverageWeightMethodologyStatus


@dataclass(frozen=True)
class _ContributionPeriodPreparation:
    period_slice_df: Any
    portfolio_period_slice_df: Any
    period_methodology_context: ContributionPeriodMethodologyContext


@dataclass(frozen=True)
class _ContributionResponseEvidence:
    diagnostics: Any
    audit: Audit
    calculation_supportability: Any
    source_economics_evidence: Any


@dataclass(frozen=True)
class _ContributionCalculationRun:
    engine_inputs: _ContributionEngineInputs
    results_by_period: dict[str, SinglePeriodContributionResult]
    average_weight_audit_state: AverageWeightShadowAuditState
    average_weight_sum_residual_bp: int


@dataclass(frozen=True)
class _FlatContributionPositionAssembly:
    selected_average_weight_column: str
    use_reset_aware_average_weight: bool
    position_contributions: list[PositionContribution]
    daily_series: list[DailyContribution] | None
    emitted_position_series: list[PositionContributionSeries] | None
    residual_allocation_applied: bool


@dataclass(frozen=True)
class _HierarchyContributionPositionAssembly:
    selected_average_weight_column: str
    use_reset_aware_average_weight: bool
    position_contributions: list[PositionContribution]
    daily_series: list[DailyContribution] | None
    emitted_position_series: list[PositionContributionSeries] | None
    hierarchy_results: dict[str, Any]
    residual_allocation_applied: bool


def _build_period_average_weight_methodology_status(
    *,
    period_methodology_context: ContributionPeriodMethodologyContext,
    average_weight_sum_residual_bp: int,
    timeseries_total_delta_periods: int,
    average_weight_audit_state: AverageWeightShadowAuditState,
    is_promoted: bool = False,
) -> AverageWeightMethodologyStatus:
    cutover_assessment = _assess_average_weight_shadow_cutover(
        max_shadow_delta_bp=period_methodology_context.max_shadow_delta_bp,
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
        position_flow_residual_days=period_methodology_context.position_flow_balance_counts[
            "position_flow_residual_days"
        ],
        portfolio_reset_without_position_reset_days=(
            period_methodology_context.portfolio_reset_without_position_reset_days
        ),
        position_reset_without_portfolio_reset_days=(
            period_methodology_context.position_reset_without_portfolio_reset_days
        ),
        timeseries_total_delta_periods=timeseries_total_delta_periods,
    )
    period_cutover_blockers = average_weight_audit_state.record_cutover_assessment(
        is_cutover_candidate=cutover_assessment.is_cutover_candidate,
        blocker_reason_codes=cutover_assessment.blocker_reason_codes,
        is_promoted=is_promoted,
    )
    return _build_average_weight_methodology_status(
        max_shadow_delta_bp=period_methodology_context.max_shadow_delta_bp,
        is_cutover_candidate=cutover_assessment.is_cutover_candidate,
        is_promoted=is_promoted,
        blocker_reason_codes=period_cutover_blockers,
    )


def _record_period_timeseries_total_delta(
    *,
    daily_series: list[DailyContribution] | None,
    period_total_contribution: float,
    average_weight_audit_state: AverageWeightShadowAuditState,
) -> int:
    if daily_series is None:
        return 0

    daily_timeseries_total = sum(point.total_contribution for point in daily_series)
    if abs(daily_timeseries_total - period_total_contribution) <= 1e-9:
        return 0

    average_weight_audit_state.record_timeseries_total_delta()
    return 1


def _select_period_average_weight_column(
    *,
    period_methodology_context: ContributionPeriodMethodologyContext,
    reset_aware_average_weight_mode: str,
) -> tuple[str, bool]:
    active_average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp_from_ratio_series(
        period_methodology_context.average_weight_shadow_df["average_weight"]
    )
    active_average_weight_cutover_assessment = _assess_average_weight_shadow_cutover(
        max_shadow_delta_bp=period_methodology_context.max_shadow_delta_bp,
        average_weight_sum_residual_bp=active_average_weight_sum_residual_bp,
        position_flow_residual_days=period_methodology_context.position_flow_balance_counts[
            "position_flow_residual_days"
        ],
        portfolio_reset_without_position_reset_days=(
            period_methodology_context.portfolio_reset_without_position_reset_days
        ),
        position_reset_without_portfolio_reset_days=(
            period_methodology_context.position_reset_without_portfolio_reset_days
        ),
        timeseries_total_delta_periods=0,
    )
    use_reset_aware_average_weight = (
        reset_aware_average_weight_mode == RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS
        and active_average_weight_cutover_assessment.is_cutover_candidate
    )
    selected_average_weight_column = (
        "reset_aware_average_weight_shadow" if use_reset_aware_average_weight else "average_weight"
    )
    return selected_average_weight_column, use_reset_aware_average_weight


def _build_period_contribution_series_outputs(
    *,
    period_slice_df,
    position_contributions: list[PositionContribution],
    emit_timeseries: bool,
    emit_by_position_timeseries: bool,
    force_position_series: bool = False,
) -> tuple[list[PositionContributionSeries], list[DailyContribution] | None, list[PositionContributionSeries] | None]:
    position_series = (
        _build_residual_adjusted_position_timeseries(period_slice_df, position_contributions)
        if _requires_position_contribution_series(
            emit_timeseries=emit_timeseries,
            emit_by_position_timeseries=emit_by_position_timeseries,
            force_position_series=force_position_series,
        )
        else []
    )
    daily_series = _build_residual_adjusted_daily_contribution_series(position_series) if emit_timeseries else None
    emitted_position_series = position_series if emit_by_position_timeseries else None
    return position_series, daily_series, emitted_position_series


def _requires_position_contribution_series(
    *,
    emit_timeseries: bool,
    emit_by_position_timeseries: bool,
    force_position_series: bool,
) -> bool:
    return emit_timeseries or emit_by_position_timeseries or force_position_series


def _build_contribution_period_supportability(
    *,
    period_slice_df: Any,
    portfolio_period_slice_df: Any,
    position_contributions: list[PositionContribution],
    daily_series: list[DailyContribution] | None,
    total_portfolio_return: Any,
    smoothing_method: str,
    residual_allocation_applied: bool,
    residual_allocation_basis: str,
    period_methodology_context: ContributionPeriodMethodologyContext,
    average_weight_audit_state: AverageWeightShadowAuditState,
    is_promoted: bool = False,
) -> _ContributionPeriodSupportability:
    average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp(position_contributions)
    total_contribution = sum(
        position_contribution.total_contribution for position_contribution in position_contributions
    )
    smoothing_evidence = _build_contribution_smoothing_evidence(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=portfolio_period_slice_df,
        smoothing_method=smoothing_method,
        linked_return=total_portfolio_return,
        final_contribution=total_contribution / 100,
        residual_allocation_applied=residual_allocation_applied,
        residual_allocation_basis=residual_allocation_basis,
    )
    timeseries_total_delta_periods = _record_period_timeseries_total_delta(
        daily_series=daily_series,
        period_total_contribution=total_contribution,
        average_weight_audit_state=average_weight_audit_state,
    )
    average_weight_methodology_status = _build_period_average_weight_methodology_status(
        period_methodology_context=period_methodology_context,
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
        timeseries_total_delta_periods=timeseries_total_delta_periods,
        average_weight_audit_state=average_weight_audit_state,
        is_promoted=is_promoted,
    )
    return _ContributionPeriodSupportability(
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
        total_contribution=total_contribution,
        smoothing_evidence=smoothing_evidence,
        average_weight_methodology_status=average_weight_methodology_status,
    )


def _build_flat_contribution_position_assembly(
    *,
    request: ContributionRequest,
    period: Any,
    period_slice_df: Any,
    period_methodology_context: ContributionPeriodMethodologyContext,
    reset_aware_average_weight_mode: str,
    total_portfolio_return: Any,
) -> _FlatContributionPositionAssembly:
    selected_average_weight_column, use_reset_aware_average_weight = _select_period_average_weight_column(
        period_methodology_context=period_methodology_context,
        reset_aware_average_weight_mode=reset_aware_average_weight_mode,
    )
    position_totals_result = build_residual_adjusted_position_totals(
        period_slice_df=period_slice_df,
        average_weight_df=period_methodology_context.average_weight_shadow_df,
        total_portfolio_return=total_portfolio_return,
        smoothing_method=request.smoothing.method,
        average_weight_columns=["average_weight", "reset_aware_average_weight_shadow"],
        residual_allocation_weight_column="selected_average_weight",
        selected_average_weight_source_column=selected_average_weight_column,
    )
    position_contributions = build_position_contributions(
        totals_df=position_totals_result.totals_df,
        request=request,
        period_start_date=period.start_date,
        period_end_date=period.end_date,
        average_weight_column="selected_average_weight",
    )
    _position_series, daily_series, emitted_position_series = _build_period_contribution_series_outputs(
        period_slice_df=period_slice_df,
        position_contributions=position_contributions,
        emit_timeseries=request.emit.timeseries,
        emit_by_position_timeseries=request.emit.by_position_timeseries,
    )
    return _FlatContributionPositionAssembly(
        selected_average_weight_column=selected_average_weight_column,
        use_reset_aware_average_weight=use_reset_aware_average_weight,
        position_contributions=position_contributions,
        daily_series=daily_series,
        emitted_position_series=emitted_position_series,
        residual_allocation_applied=position_totals_result.residual_allocation_applied,
    )


def _build_hierarchy_contribution_position_assembly(
    *,
    request: ContributionRequest,
    period: Any,
    period_slice_df: Any,
    period_methodology_context: ContributionPeriodMethodologyContext,
    reset_aware_average_weight_mode: str,
    total_portfolio_return: Any,
) -> _HierarchyContributionPositionAssembly:
    selected_average_weight_column, use_reset_aware_average_weight = _select_period_average_weight_column(
        period_methodology_context=period_methodology_context,
        reset_aware_average_weight_mode=reset_aware_average_weight_mode,
    )
    position_totals_result = build_residual_adjusted_position_totals(
        period_slice_df=period_slice_df,
        average_weight_df=period_methodology_context.average_weight_shadow_df,
        total_portfolio_return=total_portfolio_return,
        smoothing_method=request.smoothing.method,
        average_weight_columns=["average_weight", "reset_aware_average_weight_shadow"],
        residual_allocation_weight_column="selected_average_weight",
        selected_average_weight_source_column=selected_average_weight_column,
    )
    position_contributions = build_position_contributions(
        totals_df=position_totals_result.totals_df,
        request=request,
        period_start_date=period.start_date,
        period_end_date=period.end_date,
        average_weight_column="selected_average_weight",
    )
    position_series, daily_series, emitted_position_series = _build_period_contribution_series_outputs(
        period_slice_df=period_slice_df,
        position_contributions=position_contributions,
        emit_timeseries=request.emit.timeseries,
        emit_by_position_timeseries=request.emit.by_position_timeseries,
        force_position_series=True,
    )
    hierarchy_results = _build_hierarchy_from_adjusted_position_series(
        period_slice_df=period_slice_df,
        position_series=position_series,
        position_average_weights=position_totals_result.totals_df[["position_id", "selected_average_weight"]],
        request=request,
    )
    return _HierarchyContributionPositionAssembly(
        selected_average_weight_column=selected_average_weight_column,
        use_reset_aware_average_weight=use_reset_aware_average_weight,
        position_contributions=position_contributions,
        daily_series=daily_series,
        emitted_position_series=emitted_position_series,
        hierarchy_results=hierarchy_results,
        residual_allocation_applied=position_totals_result.residual_allocation_applied,
    )


def _build_flat_period_contribution_result(
    *,
    request: ContributionRequest,
    period: Any,
    daily_contributions_df: Any,
    portfolio_results_df: Any,
    reset_aware_average_weight_mode: str,
    average_weight_audit_state: AverageWeightShadowAuditState,
) -> _ContributionPeriodResult | None:
    period_preparation = _prepare_contribution_period(
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        period=period,
        average_weight_audit_state=average_weight_audit_state,
    )
    if period_preparation is None:
        return None

    total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
        request,
        period.start_date,
        period.end_date,
        period.name,
    )
    position_assembly = _build_flat_contribution_position_assembly(
        request=request,
        period=period,
        period_slice_df=period_preparation.period_slice_df,
        period_methodology_context=period_preparation.period_methodology_context,
        reset_aware_average_weight_mode=reset_aware_average_weight_mode,
        total_portfolio_return=total_portfolio_return,
    )
    supportability = _build_contribution_period_supportability(
        period_slice_df=period_preparation.period_slice_df,
        portfolio_period_slice_df=period_preparation.portfolio_period_slice_df,
        position_contributions=position_assembly.position_contributions,
        daily_series=position_assembly.daily_series,
        total_portfolio_return=total_portfolio_return,
        smoothing_method=request.smoothing.method,
        residual_allocation_applied=position_assembly.residual_allocation_applied,
        residual_allocation_basis=position_assembly.selected_average_weight_column,
        period_methodology_context=period_preparation.period_methodology_context,
        average_weight_audit_state=average_weight_audit_state,
        is_promoted=position_assembly.use_reset_aware_average_weight,
    )
    return _build_contribution_period_result(
        period_name=period.name,
        total_portfolio_return=total_portfolio_return,
        supportability=supportability,
        position_contributions=position_assembly.position_contributions,
        daily_series=position_assembly.daily_series,
        emitted_position_series=position_assembly.emitted_position_series,
    )


def _build_hierarchy_period_contribution_result(
    *,
    request: ContributionRequest,
    period: Any,
    daily_contributions_df: Any,
    portfolio_results_df: Any,
    reset_aware_average_weight_mode: str,
    average_weight_audit_state: AverageWeightShadowAuditState,
) -> _ContributionPeriodResult | None:
    period_preparation = _prepare_contribution_period(
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        period=period,
        average_weight_audit_state=average_weight_audit_state,
        require_portfolio_slice=True,
    )
    if period_preparation is None:
        return None

    total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
        request,
        period.start_date,
        period.end_date,
        period.name,
    )
    position_assembly = _build_hierarchy_contribution_position_assembly(
        request=request,
        period=period,
        period_slice_df=period_preparation.period_slice_df,
        period_methodology_context=period_preparation.period_methodology_context,
        reset_aware_average_weight_mode=reset_aware_average_weight_mode,
        total_portfolio_return=total_portfolio_return,
    )
    supportability = _build_contribution_period_supportability(
        period_slice_df=period_preparation.period_slice_df,
        portfolio_period_slice_df=period_preparation.portfolio_period_slice_df,
        position_contributions=position_assembly.position_contributions,
        daily_series=position_assembly.daily_series,
        total_portfolio_return=total_portfolio_return,
        smoothing_method=request.smoothing.method,
        residual_allocation_applied=position_assembly.residual_allocation_applied,
        residual_allocation_basis=position_assembly.selected_average_weight_column,
        period_methodology_context=period_preparation.period_methodology_context,
        average_weight_audit_state=average_weight_audit_state,
        is_promoted=position_assembly.use_reset_aware_average_weight,
    )
    return _build_contribution_period_result(
        period_name=period.name,
        total_portfolio_return=total_portfolio_return,
        supportability=supportability,
        position_contributions=position_assembly.position_contributions,
        daily_series=position_assembly.daily_series,
        emitted_position_series=position_assembly.emitted_position_series,
        hierarchy_results=position_assembly.hierarchy_results,
    )


def _prepare_contribution_period(
    *,
    daily_contributions_df: Any,
    portfolio_results_df: Any,
    period: Any,
    average_weight_audit_state: AverageWeightShadowAuditState,
    require_portfolio_slice: bool = False,
) -> _ContributionPeriodPreparation | None:
    period_frames = _slice_contribution_period_frames(
        daily_contributions_df=daily_contributions_df,
        portfolio_results_df=portfolio_results_df,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    period_slice_df = period_frames.period_slice_df
    portfolio_period_slice_df = period_frames.portfolio_period_slice_df

    if period_slice_df.empty or (require_portfolio_slice and portfolio_period_slice_df.empty):
        return None

    period_methodology_context = _build_contribution_period_methodology_context(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=portfolio_period_slice_df,
    )
    _record_average_weight_shadow_observation(
        average_weight_audit_state=average_weight_audit_state,
        period_methodology_context=period_methodology_context,
    )
    return _ContributionPeriodPreparation(
        period_slice_df=period_slice_df,
        portfolio_period_slice_df=portfolio_period_slice_df,
        period_methodology_context=period_methodology_context,
    )


def _record_average_weight_shadow_observation(
    *,
    average_weight_audit_state: AverageWeightShadowAuditState,
    period_methodology_context: ContributionPeriodMethodologyContext,
) -> None:
    average_weight_audit_state.record_shadow_observation(
        delta_positions=period_methodology_context.delta_positions,
        max_shadow_delta_bp=period_methodology_context.max_shadow_delta_bp,
        sum_shadow_delta_bp=period_methodology_context.sum_shadow_delta_bp,
    )


def _build_contribution_period_result(
    *,
    period_name: str,
    total_portfolio_return: Any,
    supportability: _ContributionPeriodSupportability,
    position_contributions: list[PositionContribution],
    daily_series: list[DailyContribution] | None,
    emitted_position_series: list[PositionContributionSeries] | None,
    hierarchy_results: dict[str, Any] | None = None,
) -> _ContributionPeriodResult:
    result_payload: dict[str, Any] = {
        "total_portfolio_return": total_portfolio_return * 100,
        "total_contribution": supportability.total_contribution,
        "position_contributions": position_contributions,
        "timeseries": daily_series,
        "by_position_timeseries": emitted_position_series,
        "average_weight_methodology_status": supportability.average_weight_methodology_status,
        "smoothing_evidence": supportability.smoothing_evidence,
    }
    if hierarchy_results is not None:
        result_payload["summary"] = hierarchy_results.get("summary")
        result_payload["levels"] = hierarchy_results.get("levels")

    return _ContributionPeriodResult(
        period_name=period_name,
        average_weight_sum_residual_bp=supportability.average_weight_sum_residual_bp,
        result=SinglePeriodContributionResult(**result_payload),
    )


def _prepare_contribution_engine_inputs(request: ContributionRequest) -> _ContributionEngineInputs:
    period_resolution = _resolve_contribution_periods(request)
    instruments_df, portfolio_results_df = _prepare_hierarchical_data(request)
    daily_contributions_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_results_df, request.weighting_scheme, request.smoothing
    )
    daily_contributions_df[PortfolioColumns.PERF_DATE.value] = observation_date_series(
        daily_contributions_df[PortfolioColumns.PERF_DATE.value]
    )
    return _ContributionEngineInputs(
        periods_to_resolve=period_resolution.periods_to_resolve,
        resolved_periods=period_resolution.resolved_periods,
        master_start_date=period_resolution.master_start_date,
        master_end_date=period_resolution.master_end_date,
        instruments_df=instruments_df,
        portfolio_results_df=portfolio_results_df,
        daily_contributions_df=daily_contributions_df,
    )


def _resolve_contribution_periods(request: ContributionRequest) -> _ContributionPeriodResolution:
    periods_to_resolve = [analysis.period for analysis in request.analyses]
    resolved_periods = resolve_periods(
        periods_to_resolve,
        request.report_end_date,
        _contribution_inception_date(request),
        explicit_start_date=request.report_start_date,
    )
    if not resolved_periods:
        raise APIBadRequestError("No valid periods could be resolved.")

    master_start_date, master_end_date = _contribution_master_window(resolved_periods)
    return _ContributionPeriodResolution(
        periods_to_resolve=periods_to_resolve,
        resolved_periods=resolved_periods,
        master_start_date=master_start_date,
        master_end_date=master_end_date,
    )


def _contribution_inception_date(request: ContributionRequest) -> date:
    if request.portfolio_data.valuation_points:
        return request.portfolio_data.valuation_points[0].perf_date
    return request.report_end_date


def _contribution_master_window(resolved_periods: list[Any]) -> tuple[date, date]:
    return (
        min(period.start_date for period in resolved_periods),
        max(period.end_date for period in resolved_periods),
    )


def _build_contribution_results_by_period(
    *,
    request: ContributionRequest,
    resolved_periods: list[Any],
    daily_contributions_df: Any,
    portfolio_results_df: Any,
    reset_aware_average_weight_mode: str,
    average_weight_audit_state: AverageWeightShadowAuditState,
) -> _ContributionPeriodResults:
    results_by_period: dict[str, SinglePeriodContributionResult] = {}
    average_weight_sum_residual_bp = 0

    for period in resolved_periods:
        period_result = (
            _build_hierarchy_period_contribution_result(
                request=request,
                period=period,
                daily_contributions_df=daily_contributions_df,
                portfolio_results_df=portfolio_results_df,
                reset_aware_average_weight_mode=reset_aware_average_weight_mode,
                average_weight_audit_state=average_weight_audit_state,
            )
            if request.hierarchy
            else _build_flat_period_contribution_result(
                request=request,
                period=period,
                daily_contributions_df=daily_contributions_df,
                portfolio_results_df=portfolio_results_df,
                reset_aware_average_weight_mode=reset_aware_average_weight_mode,
                average_weight_audit_state=average_weight_audit_state,
            )
        )
        if period_result is None:
            continue
        average_weight_sum_residual_bp = max(
            average_weight_sum_residual_bp,
            period_result.average_weight_sum_residual_bp,
        )
        results_by_period[period_result.period_name] = period_result.result

    return _ContributionPeriodResults(
        results_by_period=results_by_period,
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
    )


def _build_contribution_response(
    *,
    request: ContributionRequest,
    input_mode: ContributionInputMode,
    input_fingerprint: str,
    calculation_hash: str,
    engine_version: str,
    periods_to_resolve,
    master_start_date: date,
    master_end_date: date,
    instruments_df,
    portfolio_results_df,
    results_by_period: dict[str, SinglePeriodContributionResult],
    average_weight_audit_state: AverageWeightShadowAuditState,
    average_weight_sum_residual_bp: int,
) -> ContributionResponse:
    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=engine_version,
        precision_mode=request.precision_mode,
        calendar=request.calendar,
        annualization=request.annualization,
        periods={
            "requested": [p.value for p in periods_to_resolve],
            "master_start": str(master_start_date),
            "master_end": str(master_end_date),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        report_ccy=request.report_ccy,
    )
    evidence = _build_contribution_response_evidence(
        request=request,
        input_mode=input_mode,
        instruments_df=instruments_df,
        portfolio_results_df=portfolio_results_df,
        master_start_date=master_start_date,
        resolved_period_count=len(results_by_period),
        average_weight_audit_state=average_weight_audit_state,
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
    )

    return ContributionResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        input_mode=input_mode,
        results_by_period=results_by_period,
        calculation_supportability=evidence.calculation_supportability,
        source_economics_evidence=evidence.source_economics_evidence,
        meta=meta,
        diagnostics=evidence.diagnostics,
        audit=evidence.audit,
    )


def _build_contribution_response_evidence(
    *,
    request: ContributionRequest,
    input_mode: ContributionInputMode,
    instruments_df,
    portfolio_results_df,
    master_start_date: date,
    resolved_period_count: int,
    average_weight_audit_state: AverageWeightShadowAuditState,
    average_weight_sum_residual_bp: int,
) -> _ContributionResponseEvidence:
    diagnostics = _build_portfolio_engine_diagnostics(portfolio_results_df, master_start_date)
    carino_invalid_domain_days = (
        _count_carino_invalid_domain_days(portfolio_results_df) if request.smoothing.method == "CARINO" else 0
    )
    reset_alignment_counts = _calculate_grouped_return_reset_alignment_counts(instruments_df, portfolio_results_df)
    position_flow_balance_counts = _calculate_position_flow_balance_counts(instruments_df, portfolio_results_df)
    average_weight_audit_state.append_diagnostic_notes(
        diagnostics,
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
        carino_invalid_domain_days=carino_invalid_domain_days,
        reset_alignment_counts=reset_alignment_counts,
        position_flow_balance_counts=position_flow_balance_counts,
    )
    audit = Audit(
        counts={
            "input_positions": len(request.positions_data),
            **average_weight_audit_state.to_audit_counts(
                average_weight_sum_residual_bp=average_weight_sum_residual_bp,
                carino_invalid_domain_days=carino_invalid_domain_days,
            ),
            **reset_alignment_counts,
            **position_flow_balance_counts,
        }
    )
    calculation_supportability = build_calculation_supportability(
        input_row_count=_count_contribution_input_rows(request),
        resolved_period_count=resolved_period_count,
        latest_observation_date=_latest_contribution_observation_date(request),
        report_end_date=request.report_end_date,
    )
    source_economics_evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=input_mode,
        upstream_snapshots=_list_upstream_snapshots_for_contribution(request.calculation_id),
    )
    record_supportability_metric(operation="contribution", supportability=calculation_supportability)
    return _ContributionResponseEvidence(
        diagnostics=diagnostics,
        audit=audit,
        calculation_supportability=calculation_supportability,
        source_economics_evidence=source_economics_evidence,
    )


def _complete_contribution_execution(
    *,
    request: ContributionRequest,
    response_model: ContributionResponse,
    portfolio_results_df,
    daily_contributions_df,
) -> None:
    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="Contribution",
        request_model=request,
        response_model=response_model,
        execution_details={"input_positions": len(request.positions_data)},
        calculation_details={
            "portfolio_twr.csv": portfolio_results_df,
            "daily_contributions.csv": daily_contributions_df,
        },
    )


def _run_contribution_calculation(
    request: ContributionRequest,
    *,
    reset_aware_average_weight_mode: str,
) -> _ContributionCalculationRun:
    try:
        engine_inputs = _prepare_contribution_engine_inputs(request)
        average_weight_audit_state = AverageWeightShadowAuditState()
        period_results = _build_contribution_results_by_period(
            request=request,
            resolved_periods=engine_inputs.resolved_periods,
            daily_contributions_df=engine_inputs.daily_contributions_df,
            portfolio_results_df=engine_inputs.portfolio_results_df,
            reset_aware_average_weight_mode=reset_aware_average_weight_mode,
            average_weight_audit_state=average_weight_audit_state,
        )
        return _ContributionCalculationRun(
            engine_inputs=engine_inputs,
            results_by_period=period_results.results_by_period,
            average_weight_audit_state=average_weight_audit_state,
            average_weight_sum_residual_bp=period_results.average_weight_sum_residual_bp,
        )
    except APIError as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
            execution_stage_started=True,
        )
        raise
    except Exception as exc:
        if is_mappable_application_error(exc):
            detail = getattr(exc, "detail")
            record_execution_failure(
                calculation_id=request.calculation_id,
                message=str(detail),
                execution_stage_started=True,
            )
            raise APIError(status_code=int(getattr(exc, "status_code")), detail=detail) from exc
        failure_detail = safe_unexpected_failure_message("Contribution calculation")
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=failure_detail,
            execution_stage_started=True,
        )
        raise APIInternalServerError(failure_detail) from exc


def calculate_contribution(
    request: ContributionRequest,
    *,
    input_fingerprint: str,
    calculation_hash: str,
    input_mode: ContributionInputMode = ContributionInputMode.STATELESS,
) -> ContributionResponse:
    active_settings = get_settings()
    reset_aware_average_weight_mode = _normalize_reset_aware_average_weight_mode(
        getattr(active_settings, "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE", RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF)
    )
    execution_registry.mark_running(request.calculation_id)
    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)

    calculation_run = _run_contribution_calculation(
        request,
        reset_aware_average_weight_mode=reset_aware_average_weight_mode,
    )
    engine_inputs = calculation_run.engine_inputs

    response_model = _build_contribution_response(
        request=request,
        input_mode=input_mode,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        engine_version=active_settings.APP_VERSION,
        periods_to_resolve=engine_inputs.periods_to_resolve,
        master_start_date=engine_inputs.master_start_date,
        master_end_date=engine_inputs.master_end_date,
        instruments_df=engine_inputs.instruments_df,
        portfolio_results_df=engine_inputs.portfolio_results_df,
        results_by_period=calculation_run.results_by_period,
        average_weight_audit_state=calculation_run.average_weight_audit_state,
        average_weight_sum_residual_bp=calculation_run.average_weight_sum_residual_bp,
    )
    enforce_core_analytics_fail_fast(operation="contribution", request=request, response=response_model)
    _complete_contribution_execution(
        request=request,
        response_model=response_model,
        portfolio_results_df=engine_inputs.portfolio_results_df,
        daily_contributions_df=engine_inputs.daily_contributions_df,
    )
    return response_model
