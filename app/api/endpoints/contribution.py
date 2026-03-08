# app/api/endpoints/contribution.py
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.config import get_settings
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    ContributionResponse,
    PositionContribution,
    SinglePeriodContributionResult,
)
from app.services.lineage_service import lineage_service
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from core.repro import generate_canonical_hash
from engine.contribution import (
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
    calculate_hierarchical_contribution,
)
from engine.schema import PortfolioColumns

router = APIRouter()
settings = get_settings()


def _as_numeric(value: object, default=0):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


@router.post("/contribution", response_model=ContributionResponse, summary="Calculate Position Contribution")
async def calculate_contribution_endpoint(request: ContributionRequest, background_tasks: BackgroundTasks):
    """
    Calculates the performance contribution for each position within a portfolio
    for one or more requested periods.
    """
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)

    periods_to_resolve = [analysis.period for analysis in request.analyses]
    inception_date = (
        request.portfolio_data.valuation_points[0].perf_date
        if request.portfolio_data.valuation_points
        else request.report_end_date
    )
    resolved_periods = resolve_periods(periods_to_resolve, request.report_end_date, inception_date)

    if not resolved_periods:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

    master_start_date = min(p.start_date for p in resolved_periods)
    master_end_date = max(p.end_date for p in resolved_periods)

    try:
        if request.hierarchy:
            results, lineage_details = calculate_hierarchical_contribution(request)
            period_result = SinglePeriodContributionResult(summary=results.get("summary"), levels=results.get("levels"))
            results_by_period = {resolved_periods[0].name: period_result}
            portfolio_results_df = lineage_details.get("portfolio_twr.csv", pd.DataFrame())
            daily_contributions_df = lineage_details.get("daily_contributions.csv", pd.DataFrame())
        else:
            instruments_df, portfolio_results_df = _prepare_hierarchical_data(request)
            daily_contributions_df = _calculate_daily_instrument_contributions(
                instruments_df, portfolio_results_df, request.weighting_scheme, request.smoothing
            )
            daily_contributions_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
                daily_contributions_df[PortfolioColumns.PERF_DATE.value]
            ).dt.date

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

                total_portfolio_return = (
                    1 + portfolio_period_slice_df[PortfolioColumns.DAILY_ROR.value] / 100
                ).prod() - 1
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

                results_by_period[period.name] = SinglePeriodContributionResult(
                    total_portfolio_return=total_portfolio_return * 100,
                    total_contribution=sum(pc.total_contribution for pc in position_contributions),
                    position_contributions=position_contributions,
                )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during contribution calculation: {str(e)}",
        )

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=settings.APP_VERSION,
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
        results_by_period=results_by_period,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

    lineage_service.create_pending_record(calculation_id=request.calculation_id, calculation_type="Contribution")
    background_tasks.add_task(
        lineage_service.capture,
        calculation_id=request.calculation_id,
        calculation_type="Contribution",
        request_model=request,
        response_model=response_model,
        calculation_details={
            "portfolio_twr.csv": portfolio_results_df,
            "daily_contributions.csv": daily_contributions_df,
        },
    )

    return response_model
