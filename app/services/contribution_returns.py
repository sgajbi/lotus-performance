from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.models.contribution_requests import ContributionRequest, PositionData
from app.models.contribution_responses import PositionContribution
from app.services.contribution_methodology import _as_numeric
from engine.config import EngineConfig, PrecisionMode
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns


@dataclass(frozen=True)
class PositionContributionTotals:
    totals_df: pd.DataFrame
    residual_allocation_applied: bool


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
    return _period_engine_final_cum_ror(
        request=request,
        period_valuation_points=_portfolio_period_valuation_points(
            request=request,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
        ),
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        period_type=period_type,
        result_scale=0.01,
    )


def _portfolio_period_valuation_points(
    *,
    request: ContributionRequest,
    period_start_date,
    period_end_date,
) -> list[dict[str, Any]]:
    return [
        valuation_point.model_dump()
        for valuation_point in request.portfolio_data.valuation_points
        if period_start_date <= valuation_point.perf_date <= period_end_date
    ]


def _position_period_valuation_points(
    *,
    position_data: PositionData | None,
    period_start_date,
    period_end_date,
) -> list[dict[str, Any]]:
    if position_data is None:
        return []
    return [
        valuation_point.model_dump(mode="python")
        for valuation_point in position_data.valuation_points
        if period_start_date <= valuation_point.perf_date <= period_end_date
    ]


def _calculate_position_total_return_pct(
    *,
    request: ContributionRequest,
    position_data: PositionData | None,
    period_start_date,
    period_end_date,
) -> Any:
    period_valuation_points = _position_period_valuation_points(
        position_data=position_data,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return _period_engine_final_cum_ror(
        request=request,
        period_valuation_points=period_valuation_points,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        period_type="EXPLICIT",
    )


def _period_engine_final_cum_ror(
    *,
    request: ContributionRequest,
    period_valuation_points: list[dict[str, Any]],
    period_start_date,
    period_end_date,
    period_type,
    result_scale: float = 1.0,
) -> Any:
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

    return _as_numeric(period_results_df[PortfolioColumns.FINAL_CUM_ROR.value].iloc[-1] * result_scale)


def build_residual_adjusted_position_totals(
    *,
    period_slice_df: pd.DataFrame,
    average_weight_df: pd.DataFrame,
    total_portfolio_return: Any,
    smoothing_method: str,
    average_weight_columns: list[str],
    residual_allocation_weight_column: str,
    selected_average_weight_source_column: str | None = None,
) -> PositionContributionTotals:
    """Builds residual-adjusted contribution totals before response DTO mapping."""
    position_totals = (
        period_slice_df.groupby("position_id")
        .agg(
            total_contribution=("smoothed_contribution", "sum"),
            local_contribution=("smoothed_local_contribution", "sum"),
        )
        .reset_index()
        .merge(
            average_weight_df[["position_id", *average_weight_columns]],
            on="position_id",
            how="left",
        )
    )
    if selected_average_weight_source_column is not None:
        position_totals[residual_allocation_weight_column] = position_totals[selected_average_weight_source_column]

    sum_of_contributions = _as_numeric(position_totals["total_contribution"].sum())
    residual = total_portfolio_return - sum_of_contributions
    total_average_weight = _as_numeric(position_totals[residual_allocation_weight_column].sum())

    residual_allocation_applied = False
    if total_average_weight > 0 and smoothing_method == "CARINO":
        residual_allocation_applied = abs(residual) > 1e-12
        position_totals["total_contribution"] += residual * (
            position_totals[residual_allocation_weight_column] / total_average_weight
        )

    position_totals["fx_contribution"] = position_totals["total_contribution"] - position_totals["local_contribution"]
    return PositionContributionTotals(
        totals_df=position_totals,
        residual_allocation_applied=residual_allocation_applied,
    )


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
