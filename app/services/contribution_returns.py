from __future__ import annotations

from typing import Any

import pandas as pd

from app.models.contribution_requests import ContributionRequest, PositionData
from app.models.contribution_responses import PositionContribution
from app.services.contribution_methodology import _as_numeric
from engine.config import EngineConfig, PrecisionMode
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns


def _calculate_reset_aware_period_portfolio_return(
    request: ContributionRequest,
    period_start_date,
    period_end_date,
    period_type,
) -> Any:
    """Calculates the portfolio return for a resolved contribution slice using engine reset semantics.

    Domain meaning:
    contribution must use the same episode-aware portfolio return that the TWR engine produces for
    the same slice. Multiplying daily returns across the window is incorrect once performance resets
    break the economic continuity of the path.
    """
    period_valuation_points = [
        valuation_point.model_dump()
        for valuation_point in request.portfolio_data.valuation_points
        if period_start_date <= valuation_point.perf_date <= period_end_date
    ]
    if not period_valuation_points:
        return 0.0

    period_engine_config = EngineConfig(
        performance_start_date=period_valuation_points[0]["perf_date"],
        report_start_date=period_start_date,
        report_end_date=period_end_date,
        metric_basis=request.portfolio_data.metric_basis,
        period_type=period_type,
        precision_mode=PrecisionMode(request.precision_mode),
        rounding_precision=request.rounding_precision,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )
    period_results_df = run_engine_for_valuation_points(
        period_valuation_points,
        period_engine_config,
        force_base_only=period_engine_config.currency_mode == "BOTH",
    )
    if period_results_df.empty:
        return 0.0

    return _as_numeric(period_results_df[PortfolioColumns.FINAL_CUM_ROR.value].iloc[-1] / 100)


def _calculate_position_total_return_pct(
    *,
    request: ContributionRequest,
    position_data: PositionData | None,
    period_start_date,
    period_end_date,
) -> Any:
    if position_data is None:
        return 0.0

    period_valuation_points = [
        valuation_point.model_dump(mode="python")
        for valuation_point in position_data.valuation_points
        if period_start_date <= valuation_point.perf_date <= period_end_date
    ]
    if not period_valuation_points:
        return 0.0

    period_engine_config = EngineConfig(
        performance_start_date=period_valuation_points[0]["perf_date"],
        report_start_date=period_start_date,
        report_end_date=period_end_date,
        metric_basis=request.portfolio_data.metric_basis,
        period_type="EXPLICIT",
        precision_mode=PrecisionMode(request.precision_mode),
        rounding_precision=request.rounding_precision,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )
    period_results_df = run_engine_for_valuation_points(
        period_valuation_points,
        period_engine_config,
        force_base_only=period_engine_config.currency_mode == "BOTH",
    )
    if period_results_df.empty:
        return 0.0

    return _as_numeric(period_results_df[PortfolioColumns.FINAL_CUM_ROR.value].iloc[-1])


def build_position_contributions(
    *,
    totals_df: pd.DataFrame,
    request: ContributionRequest,
    period_start_date,
    period_end_date,
    average_weight_column: str,
    top_n: int | None = None,
) -> list[PositionContribution]:
    positions_by_id = {position.position_id: position for position in request.positions_data}
    position_contributions = [
        PositionContribution(
            position_id=row["position_id"],
            total_contribution=_as_numeric(row["total_contribution"]) * 100,
            average_weight=_as_numeric(row.get(average_weight_column)) * 100,
            total_return=_calculate_position_total_return_pct(
                request=request,
                position_data=positions_by_id.get(str(row["position_id"])),
                period_start_date=period_start_date,
                period_end_date=period_end_date,
            ),
            local_contribution=_as_numeric(row.get("local_contribution", 0)) * 100,
            fx_contribution=_as_numeric(row.get("fx_contribution", 0)) * 100,
        )
        for _, row in totals_df.iterrows()
    ]
    position_contributions.sort(key=lambda item: abs(item.total_contribution), reverse=True)
    if top_n is not None:
        return position_contributions[:top_n]
    return position_contributions
