from __future__ import annotations

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    AverageWeightMethodologyStatus,
    ContributionResponse,
    SinglePeriodContributionResult,
)
from app.services.calculation_supportability_service import (
    build_calculation_supportability,
    record_supportability_metric,
)
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
    _as_numeric,
    _calculate_average_weight_sum_residual_bp,
    _calculate_average_weight_sum_residual_bp_from_ratio_series,
    _calculate_promotion_ready_rate_bp,
    _calculate_reset_aware_average_weight_shadow,
    _classify_average_weight_methodology_status,
    _classify_average_weight_shadow_cutover_blockers,
    _classify_average_weight_shadow_period,
    _is_average_weight_shadow_cutover_candidate,
    _normalize_reset_aware_average_weight_mode,
    _numeric_series_or_default,
)
from app.services.contribution_returns import (
    _calculate_reset_aware_period_portfolio_return,
    build_position_contributions,
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
from core.envelope import Audit, Meta
from core.periods import resolve_periods
from engine.contribution import (
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
)
from engine.schema import PortfolioColumns


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
    execution_registry.start_stage(request.calculation_id, "execution")

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
        daily_contributions_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
            daily_contributions_df[PortfolioColumns.PERF_DATE.value]
        ).dt.date
        average_weight_sum_residual_bp = 0

        if request.hierarchy:
            results_by_period = {}
            average_weight_shadow_delta_positions = 0
            average_weight_shadow_delta_max_bp = 0
            average_weight_shadow_delta_sum_bp = 0
            average_weight_shadow_noise_periods = 0
            average_weight_shadow_warning_periods = 0
            average_weight_shadow_material_periods = 0
            average_weight_shadow_cutover_candidate_periods = 0
            average_weight_shadow_promoted_periods = 0
            average_weight_shadow_blocked_periods = 0
            average_weight_shadow_blocked_by_weight_residual_periods = 0
            average_weight_shadow_blocked_by_flow_balance_periods = 0
            average_weight_shadow_blocked_by_reset_alignment_periods = 0
            average_weight_shadow_blocked_by_timeseries_delta_periods = 0
            timeseries_total_delta_periods = 0
            for period in resolved_periods:
                period_slice_df = daily_contributions_df[
                    (daily_contributions_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                    & (daily_contributions_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
                ].copy()
                portfolio_period_slice_df = portfolio_results_df[
                    (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        >= period.start_date
                    )
                    & (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        <= period.end_date
                    )
                ]

                if period_slice_df.empty or portfolio_period_slice_df.empty:
                    continue

                total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
                    request,
                    period.start_date,
                    period.end_date,
                    period.name,
                )
                (
                    average_weight_shadow_df,
                    period_delta_positions,
                    period_max_shadow_delta_bp,
                    period_sum_shadow_delta_bp,
                ) = _calculate_reset_aware_average_weight_shadow(
                    period_slice_df,
                    portfolio_period_slice_df,
                )
                average_weight_shadow_delta_positions += period_delta_positions
                average_weight_shadow_delta_max_bp = max(
                    average_weight_shadow_delta_max_bp,
                    period_max_shadow_delta_bp,
                )
                average_weight_shadow_delta_sum_bp += period_sum_shadow_delta_bp
                shadow_period_bucket = _classify_average_weight_shadow_period(period_max_shadow_delta_bp)
                if shadow_period_bucket == "noise":
                    average_weight_shadow_noise_periods += 1
                elif shadow_period_bucket == "warning":
                    average_weight_shadow_warning_periods += 1
                elif shadow_period_bucket == "material":
                    average_weight_shadow_material_periods += 1

                period_position_reset_dates = set(
                    pd.to_datetime(
                        period_slice_df.loc[
                            _numeric_series_or_default(period_slice_df, PortfolioColumns.PERF_RESET.value) == 1,
                            PortfolioColumns.PERF_DATE.value,
                        ]
                    ).dt.date
                )
                period_portfolio_reset_dates = set(
                    pd.to_datetime(
                        portfolio_period_slice_df.loc[
                            _numeric_series_or_default(portfolio_period_slice_df, PortfolioColumns.PERF_RESET.value)
                            == 1,
                            PortfolioColumns.PERF_DATE.value,
                        ]
                    ).dt.date
                )
                period_position_flow_balance_counts = _calculate_position_flow_balance_counts(
                    period_slice_df,
                    portfolio_period_slice_df,
                )
                position_totals = (
                    period_slice_df.groupby("position_id")
                    .agg(
                        total_contribution=("smoothed_contribution", "sum"),
                        local_contribution=("smoothed_local_contribution", "sum"),
                    )
                    .reset_index()
                    .merge(
                        average_weight_shadow_df[["position_id", "average_weight"]],
                        on="position_id",
                        how="left",
                    )
                )
                sum_of_contributions = _as_numeric(position_totals["total_contribution"].sum())
                residual = total_portfolio_return - sum_of_contributions
                total_avg_weight = _as_numeric(position_totals["average_weight"].sum())
                residual_allocation_applied = False
                if total_avg_weight > 0 and request.smoothing.method == "CARINO":
                    residual_allocation_applied = abs(residual) > 1e-12
                    position_totals["total_contribution"] += residual * (
                        position_totals["average_weight"] / total_avg_weight
                    )
                position_totals["fx_contribution"] = (
                    position_totals["total_contribution"] - position_totals["local_contribution"]
                )
                position_contributions = build_position_contributions(
                    totals_df=position_totals,
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
                    residual_allocation_applied=residual_allocation_applied,
                    residual_allocation_basis="average_weight",
                )
                period_timeseries_total_delta_periods = 0
                if daily_series is not None:
                    daily_timeseries_total = sum(point.total_contribution for point in daily_series)
                    if abs(daily_timeseries_total - period_total_contribution) > 1e-9:
                        period_timeseries_total_delta_periods = 1
                        timeseries_total_delta_periods += 1
                hierarchy_period_cutover_blockers = _classify_average_weight_shadow_cutover_blockers(
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                    position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                    portfolio_reset_without_position_reset_days=len(
                        period_portfolio_reset_dates - period_position_reset_dates
                    ),
                    position_reset_without_portfolio_reset_days=len(
                        period_position_reset_dates - period_portfolio_reset_dates
                    ),
                    timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                )
                period_is_cutover_candidate = _is_average_weight_shadow_cutover_candidate(
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                    position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                    portfolio_reset_without_position_reset_days=len(
                        period_portfolio_reset_dates - period_position_reset_dates
                    ),
                    position_reset_without_portfolio_reset_days=len(
                        period_position_reset_dates - period_portfolio_reset_dates
                    ),
                    timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                )
                if period_is_cutover_candidate:
                    average_weight_shadow_cutover_candidate_periods += 1
                    hierarchy_period_cutover_blockers = set()
                elif hierarchy_period_cutover_blockers:
                    average_weight_shadow_blocked_periods += 1
                if "weight_residual" in hierarchy_period_cutover_blockers:
                    average_weight_shadow_blocked_by_weight_residual_periods += 1
                if "flow_balance" in hierarchy_period_cutover_blockers:
                    average_weight_shadow_blocked_by_flow_balance_periods += 1
                if "reset_alignment" in hierarchy_period_cutover_blockers:
                    average_weight_shadow_blocked_by_reset_alignment_periods += 1
                if "timeseries_reconciliation" in hierarchy_period_cutover_blockers:
                    average_weight_shadow_blocked_by_timeseries_delta_periods += 1
                period_methodology_status = AverageWeightMethodologyStatus(
                    status=_classify_average_weight_methodology_status(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        is_cutover_candidate=period_is_cutover_candidate,
                        is_promoted=False,
                        blocker_reason_codes=hierarchy_period_cutover_blockers,
                    ),
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    is_material_shadow=period_max_shadow_delta_bp >= 500,
                    is_cutover_candidate=period_is_cutover_candidate,
                    is_promoted=False,
                    blocker_reason_codes=sorted(hierarchy_period_cutover_blockers),
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
            average_weight_shadow_delta_positions = 0
            average_weight_shadow_delta_max_bp = 0
            average_weight_shadow_delta_sum_bp = 0
            average_weight_shadow_noise_periods = 0
            average_weight_shadow_warning_periods = 0
            average_weight_shadow_material_periods = 0
            average_weight_shadow_cutover_candidate_periods = 0
            average_weight_shadow_promoted_periods = 0
            average_weight_shadow_blocked_periods = 0
            average_weight_shadow_blocked_by_weight_residual_periods = 0
            average_weight_shadow_blocked_by_flow_balance_periods = 0
            average_weight_shadow_blocked_by_reset_alignment_periods = 0
            average_weight_shadow_blocked_by_timeseries_delta_periods = 0
            timeseries_total_delta_periods = 0
            for period in resolved_periods:
                period_slice_df = daily_contributions_df[
                    (daily_contributions_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                    & (daily_contributions_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
                ].copy()

                if period_slice_df.empty:
                    continue

                portfolio_period_slice_df = portfolio_results_df[
                    (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        >= period.start_date
                    )
                    & (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        <= period.end_date
                    )
                ]

                (
                    average_weight_shadow_df,
                    period_delta_positions,
                    period_max_shadow_delta_bp,
                    period_sum_shadow_delta_bp,
                ) = _calculate_reset_aware_average_weight_shadow(
                    period_slice_df,
                    portfolio_period_slice_df,
                )
                average_weight_shadow_delta_positions += period_delta_positions
                average_weight_shadow_delta_max_bp = max(
                    average_weight_shadow_delta_max_bp,
                    period_max_shadow_delta_bp,
                )
                average_weight_shadow_delta_sum_bp += period_sum_shadow_delta_bp
                shadow_period_bucket = _classify_average_weight_shadow_period(period_max_shadow_delta_bp)
                if shadow_period_bucket == "noise":
                    average_weight_shadow_noise_periods += 1
                elif shadow_period_bucket == "warning":
                    average_weight_shadow_warning_periods += 1
                elif shadow_period_bucket == "material":
                    average_weight_shadow_material_periods += 1

                period_position_reset_dates = set(
                    pd.to_datetime(
                        period_slice_df.loc[
                            _numeric_series_or_default(period_slice_df, PortfolioColumns.PERF_RESET.value) == 1,
                            PortfolioColumns.PERF_DATE.value,
                        ]
                    ).dt.date
                )
                period_portfolio_reset_dates = set(
                    pd.to_datetime(
                        portfolio_period_slice_df.loc[
                            _numeric_series_or_default(portfolio_period_slice_df, PortfolioColumns.PERF_RESET.value)
                            == 1,
                            PortfolioColumns.PERF_DATE.value,
                        ]
                    ).dt.date
                )
                period_position_flow_balance_counts = _calculate_position_flow_balance_counts(
                    period_slice_df,
                    portfolio_period_slice_df,
                )
                active_average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp_from_ratio_series(
                    average_weight_shadow_df["average_weight"]
                )
                use_reset_aware_average_weight = (
                    reset_aware_average_weight_mode == RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS
                    and _is_average_weight_shadow_cutover_candidate(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        average_weight_sum_residual_bp=active_average_weight_sum_residual_bp,
                        position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                        portfolio_reset_without_position_reset_days=len(
                            period_portfolio_reset_dates - period_position_reset_dates
                        ),
                        position_reset_without_portfolio_reset_days=len(
                            period_position_reset_dates - period_portfolio_reset_dates
                        ),
                        timeseries_total_delta_periods=0,
                    )
                )
                selected_average_weight_column = (
                    "reset_aware_average_weight_shadow" if use_reset_aware_average_weight else "average_weight"
                )
                if use_reset_aware_average_weight:
                    average_weight_shadow_promoted_periods += 1

                totals = (
                    period_slice_df.groupby("position_id")
                    .agg(
                        total_contribution=("smoothed_contribution", "sum"),
                        local_contribution=("smoothed_local_contribution", "sum"),
                    )
                    .reset_index()
                ).merge(
                    average_weight_shadow_df[["position_id", "average_weight", "reset_aware_average_weight_shadow"]],
                    on="position_id",
                    how="left",
                )
                totals["selected_average_weight"] = totals[selected_average_weight_column]

                total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
                    request,
                    period.start_date,
                    period.end_date,
                    period.name,
                )
                sum_of_contributions = _as_numeric(totals["total_contribution"].sum())
                residual = total_portfolio_return - sum_of_contributions
                total_avg_weight = _as_numeric(totals["selected_average_weight"].sum())

                residual_allocation_applied = False
                if total_avg_weight > 0 and request.smoothing.method == "CARINO":
                    residual_allocation_applied = abs(residual) > 1e-12
                    totals["total_contribution"] += residual * (totals["selected_average_weight"] / total_avg_weight)

                totals["fx_contribution"] = totals["total_contribution"] - totals["local_contribution"]

                position_contributions = build_position_contributions(
                    totals_df=totals,
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
                    residual_allocation_applied=residual_allocation_applied,
                    residual_allocation_basis=selected_average_weight_column,
                )
                if daily_series is not None:
                    daily_timeseries_total = sum(point.total_contribution for point in daily_series)
                    if abs(daily_timeseries_total - period_total_contribution) > 1e-9:
                        period_timeseries_total_delta_periods = 1
                        timeseries_total_delta_periods += 1
                period_cutover_blockers: set[str] = set()
                if _is_average_weight_shadow_cutover_candidate(
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                    position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                    portfolio_reset_without_position_reset_days=len(
                        period_portfolio_reset_dates - period_position_reset_dates
                    ),
                    position_reset_without_portfolio_reset_days=len(
                        period_position_reset_dates - period_portfolio_reset_dates
                    ),
                    timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                ):
                    average_weight_shadow_cutover_candidate_periods += 1
                    period_is_cutover_candidate = True
                else:
                    period_is_cutover_candidate = False
                    period_cutover_blockers = _classify_average_weight_shadow_cutover_blockers(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                        position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                        portfolio_reset_without_position_reset_days=len(
                            period_portfolio_reset_dates - period_position_reset_dates
                        ),
                        position_reset_without_portfolio_reset_days=len(
                            period_position_reset_dates - period_portfolio_reset_dates
                        ),
                        timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                    )
                    if period_cutover_blockers:
                        average_weight_shadow_blocked_periods += 1
                    if "weight_residual" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_weight_residual_periods += 1
                    if "flow_balance" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_flow_balance_periods += 1
                    if "reset_alignment" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_reset_alignment_periods += 1
                    if "timeseries_reconciliation" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_timeseries_delta_periods += 1
                period_methodology_status = AverageWeightMethodologyStatus(
                    status=_classify_average_weight_methodology_status(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        is_cutover_candidate=period_is_cutover_candidate,
                        is_promoted=use_reset_aware_average_weight,
                        blocker_reason_codes=period_cutover_blockers,
                    ),
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    is_material_shadow=period_max_shadow_delta_bp >= 500,
                    is_cutover_candidate=period_is_cutover_candidate,
                    is_promoted=use_reset_aware_average_weight,
                    blocker_reason_codes=sorted(period_cutover_blockers),
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
    average_weight_shadow_promotion_ready_rate_bp = _calculate_promotion_ready_rate_bp(
        ready_periods=average_weight_shadow_cutover_candidate_periods,
        material_periods=average_weight_shadow_material_periods,
    )
    if average_weight_shadow_delta_max_bp >= 500:
        diagnostics.notes.append(
            "Reset-aware average-weight shadow differs from the active mean-weight output for "
            f"{average_weight_shadow_delta_positions} position-period rows."
        )
        diagnostics.notes.append(
            "Reset-aware average-weight shadow differs materially from the active average-weight "
            f"output, with a maximum delta of {average_weight_shadow_delta_max_bp} basis points."
        )
    elif average_weight_shadow_delta_positions > 0:
        diagnostics.notes.append(
            "Reset-aware average-weight shadow differs from the active mean-weight output for "
            f"{average_weight_shadow_delta_positions} position-period rows. The maximum delta was "
            f"{average_weight_shadow_delta_max_bp} basis points, which is still under characterization."
        )
    if average_weight_shadow_cutover_candidate_periods > 0:
        diagnostics.notes.append(
            "Some periods show material reset-aware average-weight pressure while the surrounding "
            "bookkeeping remains clean. Those periods are strong candidates for a future denominator "
            f"cutover study ({average_weight_shadow_cutover_candidate_periods} periods)."
        )
    if average_weight_shadow_material_periods > 0:
        diagnostics.notes.append(
            "Reset-aware average-weight rollout readiness is currently "
            f"{average_weight_shadow_promotion_ready_rate_bp} basis points of material-shadow periods "
            f"({average_weight_shadow_cutover_candidate_periods} of {average_weight_shadow_material_periods})."
        )
    if average_weight_shadow_promoted_periods > 0:
        diagnostics.notes.append(
            "Reset-aware average-weight promotion was applied for "
            f"{average_weight_shadow_promoted_periods} periods under the controlled rollout mode."
        )
    if average_weight_shadow_blocked_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods remained shadow-only because one or "
            "more rollout guardrails were not yet clean "
            f"({average_weight_shadow_blocked_periods} periods)."
        )
    if average_weight_shadow_blocked_by_weight_residual_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because emitted "
            "position weights did not sum cleanly to 100%."
        )
    if average_weight_shadow_blocked_by_flow_balance_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because "
            "position-level stock and cash legs did not cancel cleanly."
        )
    if average_weight_shadow_blocked_by_reset_alignment_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because "
            "portfolio and position reset boundaries were not aligned."
        )
    if average_weight_shadow_blocked_by_timeseries_delta_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because emitted "
            "daily contribution series still drifted from the residual-adjusted period total."
        )
    if average_weight_sum_residual_bp > 1:
        diagnostics.notes.append(
            "Emitted position average weights do not sum to 100% exactly; the maximum residual was "
            f"{average_weight_sum_residual_bp} basis points."
        )
    if carino_invalid_domain_days > 0:
        diagnostics.notes.append(
            "Carino smoothing fell back to raw daily contribution arithmetic on "
            f"{carino_invalid_domain_days} portfolio days because the linked gross return factor "
            "left the valid logarithmic domain."
        )
    if (
        reset_alignment_counts["portfolio_reset_without_position_reset_days"] > 0
        or reset_alignment_counts["position_reset_without_portfolio_reset_days"] > 0
    ):
        diagnostics.notes.append(
            "Portfolio and position reset boundaries differ on some contribution dates; "
            "grouped-return alignment remains under characterization."
        )
    if position_flow_balance_counts["position_flow_residual_max_bp"] > 10:
        diagnostics.notes.append(
            "Summed position-level cash flows show a materially non-flow-neutral scoped slice on "
            f"{position_flow_balance_counts['position_flow_residual_days']} dates. This means the visible "
            "position set is not carrying both offsetting legs inside the current scope, so contribution "
            "is being explained on a partial flow story rather than a fully self-cancelling internal book. "
            f"The maximum residual was {position_flow_balance_counts['position_flow_residual_max_bp']} basis points "
            "of portfolio capital."
        )
    elif position_flow_balance_counts["position_flow_residual_days"] > 0:
        diagnostics.notes.append(
            "Summed position-level cash flows did not net to zero on "
            f"{position_flow_balance_counts['position_flow_residual_days']} dates. This looks like a small "
            "non-flow-neutral scoped slice rather than a material flow imbalance, but it should still be "
            f"reviewed. The maximum residual was {position_flow_balance_counts['position_flow_residual_max_bp']} "
            "basis points of portfolio capital."
        )
    if timeseries_total_delta_periods > 0:
        diagnostics.notes.append(
            "Some emitted daily contribution series remain raw path outputs and do not sum to the "
            "residual-adjusted period total for reset-heavy slices."
        )
    audit = Audit(
        counts={
            "input_positions": len(request.positions_data),
            "average_weight_shadow_delta_positions": average_weight_shadow_delta_positions,
            "average_weight_shadow_delta_max_bp": average_weight_shadow_delta_max_bp,
            "average_weight_shadow_delta_sum_bp": average_weight_shadow_delta_sum_bp,
            "average_weight_shadow_noise_periods": average_weight_shadow_noise_periods,
            "average_weight_shadow_warning_periods": average_weight_shadow_warning_periods,
            "average_weight_shadow_material_periods": average_weight_shadow_material_periods,
            "average_weight_shadow_cutover_candidate_periods": average_weight_shadow_cutover_candidate_periods,
            "average_weight_shadow_promotion_ready_rate_bp": average_weight_shadow_promotion_ready_rate_bp,
            "average_weight_shadow_promoted_periods": average_weight_shadow_promoted_periods,
            "average_weight_shadow_blocked_periods": average_weight_shadow_blocked_periods,
            "average_weight_shadow_blocked_by_weight_residual_periods": (
                average_weight_shadow_blocked_by_weight_residual_periods
            ),
            "average_weight_shadow_blocked_by_flow_balance_periods": (
                average_weight_shadow_blocked_by_flow_balance_periods
            ),
            "average_weight_shadow_blocked_by_reset_alignment_periods": (
                average_weight_shadow_blocked_by_reset_alignment_periods
            ),
            "average_weight_shadow_blocked_by_timeseries_delta_periods": (
                average_weight_shadow_blocked_by_timeseries_delta_periods
            ),
            "average_weight_sum_residual_bp": average_weight_sum_residual_bp,
            "carino_invalid_domain_days": carino_invalid_domain_days,
            "timeseries_total_delta_periods": timeseries_total_delta_periods,
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
