from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    ContributionResponse,
    DailyContribution,
    PositionContribution,
    PositionContributionSeries,
    PositionDailyContribution,
    SinglePeriodContributionResult,
)
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from engine.contribution import (
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
    build_hierarchical_contribution_result,
)
from engine.schema import PortfolioColumns


def _as_numeric(value: Any, default: Any = 0) -> Any:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


def _calculate_total_portfolio_return_from_slice(portfolio_period_slice_df: pd.DataFrame) -> Any:
    daily_returns = pd.to_numeric(
        portfolio_period_slice_df[PortfolioColumns.DAILY_ROR.value],
        errors="coerce",
    )
    total_portfolio_return_product: Any = (1 + daily_returns / 100).prod()
    return _as_numeric(total_portfolio_return_product - 1)


def _build_daily_contribution_series(period_slice_df: pd.DataFrame) -> list[DailyContribution]:
    totals_by_day = (
        period_slice_df.groupby(PortfolioColumns.PERF_DATE.value, dropna=False)
        .agg(total_contribution=("smoothed_contribution", "sum"))
        .reset_index()
        .sort_values(PortfolioColumns.PERF_DATE.value)
    )
    return [
        DailyContribution(
            date=row[PortfolioColumns.PERF_DATE.value],
            total_contribution=_as_numeric(row["total_contribution"]) * 100,
        )
        for _, row in totals_by_day.iterrows()
    ]


def _build_position_contribution_series(period_slice_df: pd.DataFrame) -> list[PositionContributionSeries]:
    position_id_column = "position_id"
    series_by_position: list[PositionContributionSeries] = []
    for position_id, position_slice in (
        period_slice_df.sort_values([position_id_column, PortfolioColumns.PERF_DATE.value]).groupby(
            position_id_column, sort=True
        )
    ):
        series_by_position.append(
            PositionContributionSeries(
                position_id=str(position_id),
                series=[
                    PositionDailyContribution(
                        date=row[PortfolioColumns.PERF_DATE.value],
                        contribution=_as_numeric(row["smoothed_contribution"]) * 100,
                    )
                    for _, row in position_slice.iterrows()
                ],
            )
        )
    return series_by_position


def calculate_contribution(
    request: ContributionRequest,
    *,
    input_fingerprint: str,
    calculation_hash: str,
    input_mode: ContributionInputMode = ContributionInputMode.STATELESS,
) -> ContributionResponse:
    active_settings = get_settings()
    execution_registry.mark_running(request.calculation_id)
    execution_registry.start_stage(request.calculation_id, "execution")

    periods_to_resolve = [analysis.period for analysis in request.analyses]
    inception_date = (
        request.portfolio_data.valuation_points[0].perf_date
        if request.portfolio_data.valuation_points
        else request.report_end_date
    )
    resolved_periods = resolve_periods(periods_to_resolve, request.report_end_date, inception_date)

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

        if request.hierarchy:
            results_by_period = {}
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

                total_portfolio_return = _calculate_total_portfolio_return_from_slice(portfolio_period_slice_df)
                period_results = build_hierarchical_contribution_result(
                    period_slice_df,
                    request,
                    total_portfolio_return=total_portfolio_return,
                )
                results_by_period[period.name] = SinglePeriodContributionResult(
                    summary=period_results.get("summary"),
                    levels=period_results.get("levels"),
                )
        else:
            results_by_period = {}
            for period in resolved_periods:
                period_slice_df = daily_contributions_df[
                    (daily_contributions_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                    & (daily_contributions_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
                ].copy()

                if period_slice_df.empty:
                    continue

                totals = (
                    period_slice_df.groupby("position_id")
                    .agg(
                        total_contribution=("smoothed_contribution", "sum"),
                        local_contribution=("smoothed_local_contribution", "sum"),
                        average_weight=("daily_weight", "mean"),
                    )
                    .reset_index()
                )

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

                total_portfolio_return = _calculate_total_portfolio_return_from_slice(portfolio_period_slice_df)
                sum_of_contributions = _as_numeric(totals["total_contribution"].sum())
                residual = total_portfolio_return - sum_of_contributions
                total_avg_weight = _as_numeric(totals["average_weight"].sum())

                if total_avg_weight > 0 and request.smoothing.method == "CARINO":
                    totals["total_contribution"] += residual * (totals["average_weight"] / total_avg_weight)

                totals["fx_contribution"] = totals["total_contribution"] - totals["local_contribution"]

                position_contributions = [
                    PositionContribution(
                        position_id=row["position_id"],
                        total_contribution=_as_numeric(row["total_contribution"]) * 100,
                        average_weight=_as_numeric(row["average_weight"]) * 100,
                        total_return=0,
                        local_contribution=_as_numeric(row.get("local_contribution", 0)) * 100,
                        fx_contribution=_as_numeric(row.get("fx_contribution", 0)) * 100,
                    )
                    for _, row in totals.iterrows()
                ]

                daily_series = (
                    _build_daily_contribution_series(period_slice_df)
                    if request.emit.timeseries
                    else None
                )
                position_series = (
                    _build_position_contribution_series(period_slice_df)
                    if request.emit.by_position_timeseries
                    else None
                )

                results_by_period[period.name] = SinglePeriodContributionResult(
                    total_portfolio_return=total_portfolio_return * 100,
                    total_contribution=sum(pc.total_contribution for pc in position_contributions),
                    position_contributions=position_contributions,
                    timeseries=daily_series,
                    by_position_timeseries=position_series,
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
    diagnostics = Diagnostics(nip_days=0, reset_days=0, effective_period_start=master_start_date, notes=[])
    audit = Audit(counts={"input_positions": len(request.positions_data)})

    response_model = ContributionResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        input_mode=input_mode,
        results_by_period=results_by_period,
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
