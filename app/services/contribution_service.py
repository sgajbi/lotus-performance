from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    AverageWeightMethodologyStatus,
    ContributionResponse,
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
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from core.envelope import Audit, Meta
from core.periods import resolve_periods
from engine.contribution import (
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
)
from engine.schema import PortfolioColumns


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

    periods_to_resolve = [analysis.period for analysis in request.analyses]
    inception_date = (
        request.portfolio_data.valuation_points[0].perf_date
        if request.portfolio_data.valuation_points
        else request.report_end_date
    )
    resolved_periods = resolve_periods(
        periods_to_resolve,
        request.report_end_date,
        inception_date,
        explicit_start_date=request.report_start_date,
    )

    try:
        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)
        instruments_df, portfolio_results_df = _prepare_hierarchical_data(request)
        daily_contributions_df = _calculate_daily_instrument_contributions(
            instruments_df, portfolio_results_df, request.weighting_scheme, request.smoothing
        )
        daily_contributions_df[PortfolioColumns.PERF_DATE.value] = observation_date_series(
            daily_contributions_df[PortfolioColumns.PERF_DATE.value]
        )
        average_weight_sum_residual_bp = 0
        average_weight_audit_state = AverageWeightShadowAuditState()

        if request.hierarchy:
            results_by_period = {}
            for period in resolved_periods:
                period_frames = _slice_contribution_period_frames(
                    daily_contributions_df=daily_contributions_df,
                    portfolio_results_df=portfolio_results_df,
                    start_date=period.start_date,
                    end_date=period.end_date,
                )
                period_slice_df = period_frames.period_slice_df
                portfolio_period_slice_df = period_frames.portfolio_period_slice_df

                if period_slice_df.empty or portfolio_period_slice_df.empty:
                    continue

                total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
                    request,
                    period.start_date,
                    period.end_date,
                    period.name,
                )
                period_methodology_context = _build_contribution_period_methodology_context(
                    period_slice_df=period_slice_df,
                    portfolio_period_slice_df=portfolio_period_slice_df,
                )
                average_weight_audit_state.record_shadow_observation(
                    delta_positions=period_methodology_context.delta_positions,
                    max_shadow_delta_bp=period_methodology_context.max_shadow_delta_bp,
                    sum_shadow_delta_bp=period_methodology_context.sum_shadow_delta_bp,
                )

                position_totals_result = build_residual_adjusted_position_totals(
                    period_slice_df=period_slice_df,
                    average_weight_df=period_methodology_context.average_weight_shadow_df,
                    total_portfolio_return=total_portfolio_return,
                    smoothing_method=request.smoothing.method,
                    average_weight_columns=["average_weight"],
                    residual_allocation_weight_column="average_weight",
                )
                position_contributions = build_position_contributions(
                    totals_df=position_totals_result.totals_df,
                    request=request,
                    period_start_date=period.start_date,
                    period_end_date=period.end_date,
                    average_weight_column="average_weight",
                )
                position_series = (
                    _build_residual_adjusted_position_timeseries(period_slice_df, position_contributions)
                    if request.emit.by_position_timeseries or request.emit.timeseries or request.hierarchy
                    else []
                )
                daily_series = (
                    _build_residual_adjusted_daily_contribution_series(position_series)
                    if request.emit.timeseries
                    else None
                )
                emitted_position_series = position_series if request.emit.by_position_timeseries else None
                period_results = _build_hierarchy_from_adjusted_position_series(
                    period_slice_df=period_slice_df,
                    position_series=position_series,
                    request=request,
                )
                period_average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp(
                    position_contributions
                )
                average_weight_sum_residual_bp = max(
                    average_weight_sum_residual_bp,
                    period_average_weight_sum_residual_bp,
                )
                period_total_contribution = sum(
                    position_contribution.total_contribution for position_contribution in position_contributions
                )
                smoothing_evidence = _build_contribution_smoothing_evidence(
                    period_slice_df=period_slice_df,
                    portfolio_period_slice_df=portfolio_period_slice_df,
                    smoothing_method=request.smoothing.method,
                    linked_return=total_portfolio_return,
                    final_contribution=period_total_contribution / 100,
                    residual_allocation_applied=position_totals_result.residual_allocation_applied,
                    residual_allocation_basis="average_weight",
                )
                period_timeseries_total_delta_periods = 0
                if daily_series is not None:
                    daily_timeseries_total = sum(point.total_contribution for point in daily_series)
                    if abs(daily_timeseries_total - period_total_contribution) > 1e-9:
                        period_timeseries_total_delta_periods = 1
                        average_weight_audit_state.record_timeseries_total_delta()
                period_methodology_status = _build_period_average_weight_methodology_status(
                    period_methodology_context=period_methodology_context,
                    average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                    timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                    average_weight_audit_state=average_weight_audit_state,
                )
                results_by_period[period.name] = SinglePeriodContributionResult(
                    total_portfolio_return=total_portfolio_return * 100,
                    total_contribution=period_total_contribution,
                    position_contributions=position_contributions,
                    timeseries=daily_series,
                    by_position_timeseries=emitted_position_series,
                    average_weight_methodology_status=period_methodology_status,
                    smoothing_evidence=smoothing_evidence,
                    summary=period_results.get("summary"),
                    levels=period_results.get("levels"),
                )
        else:
            results_by_period = {}
            for period in resolved_periods:
                period_frames = _slice_contribution_period_frames(
                    daily_contributions_df=daily_contributions_df,
                    portfolio_results_df=portfolio_results_df,
                    start_date=period.start_date,
                    end_date=period.end_date,
                )
                period_slice_df = period_frames.period_slice_df

                if period_slice_df.empty:
                    continue

                portfolio_period_slice_df = period_frames.portfolio_period_slice_df

                period_methodology_context = _build_contribution_period_methodology_context(
                    period_slice_df=period_slice_df,
                    portfolio_period_slice_df=portfolio_period_slice_df,
                )
                average_weight_audit_state.record_shadow_observation(
                    delta_positions=period_methodology_context.delta_positions,
                    max_shadow_delta_bp=period_methodology_context.max_shadow_delta_bp,
                    sum_shadow_delta_bp=period_methodology_context.sum_shadow_delta_bp,
                )

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

                total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
                    request,
                    period.start_date,
                    period.end_date,
                    period.name,
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
                average_weight_sum_residual_bp = max(
                    average_weight_sum_residual_bp,
                    _calculate_average_weight_sum_residual_bp(position_contributions),
                )

                position_series = (
                    _build_residual_adjusted_position_timeseries(period_slice_df, position_contributions)
                    if request.emit.by_position_timeseries or request.emit.timeseries
                    else []
                )
                daily_series = (
                    _build_residual_adjusted_daily_contribution_series(position_series)
                    if request.emit.timeseries
                    else None
                )
                emitted_position_series = position_series if request.emit.by_position_timeseries else None
                period_average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp(
                    position_contributions
                )
                period_timeseries_total_delta_periods = 0
                period_total_contribution = sum(pc.total_contribution for pc in position_contributions)
                smoothing_evidence = _build_contribution_smoothing_evidence(
                    period_slice_df=period_slice_df,
                    portfolio_period_slice_df=portfolio_period_slice_df,
                    smoothing_method=request.smoothing.method,
                    linked_return=total_portfolio_return,
                    final_contribution=period_total_contribution / 100,
                    residual_allocation_applied=position_totals_result.residual_allocation_applied,
                    residual_allocation_basis=selected_average_weight_column,
                )
                if daily_series is not None:
                    daily_timeseries_total = sum(point.total_contribution for point in daily_series)
                    if abs(daily_timeseries_total - period_total_contribution) > 1e-9:
                        period_timeseries_total_delta_periods = 1
                        average_weight_audit_state.record_timeseries_total_delta()
                period_methodology_status = _build_period_average_weight_methodology_status(
                    period_methodology_context=period_methodology_context,
                    average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                    timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                    average_weight_audit_state=average_weight_audit_state,
                    is_promoted=use_reset_aware_average_weight,
                )
                results_by_period[period.name] = SinglePeriodContributionResult(
                    total_portfolio_return=total_portfolio_return * 100,
                    total_contribution=period_total_contribution,
                    position_contributions=position_contributions,
                    timeseries=daily_series,
                    by_position_timeseries=emitted_position_series,
                    average_weight_methodology_status=period_methodology_status,
                    smoothing_evidence=smoothing_evidence,
                )
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
            execution_stage_started=True,
        )
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected error occurred during contribution calculation: {str(exc)}",
            execution_stage_started=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during contribution calculation: {str(exc)}",
        ) from exc

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=active_settings.APP_VERSION,
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
        resolved_period_count=len(results_by_period),
        latest_observation_date=_latest_contribution_observation_date(request),
        report_end_date=request.report_end_date,
    )
    source_economics_evidence = build_contribution_source_economics_evidence(
        request=request,
        input_mode=input_mode,
        upstream_snapshots=_list_upstream_snapshots_for_contribution(request.calculation_id),
    )
    record_supportability_metric(operation="contribution", supportability=calculation_supportability)

    response_model = ContributionResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        input_mode=input_mode,
        results_by_period=results_by_period,
        calculation_supportability=calculation_supportability,
        source_economics_evidence=source_economics_evidence,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

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
    return response_model
