from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from app.models.contribution_requests import ContributionRequest, PositionDailyData, PositionData
from app.models.contribution_responses import PositionContribution
from app.services.contribution_methodology import _as_numeric
from core.envelope import DataPolicy
from engine.config import EndingValueBasis, EngineConfig, PrecisionMode
from engine.contribution import _local_fx_residual_proportions
from engine.contribution_fee_basis import contribution_data_policy_for_entity
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
        entity_type="PORTFOLIO",
        entity_id=request.portfolio_id,
    )


def _portfolio_period_valuation_points(
    *,
    request: ContributionRequest,
    period_start_date,
    period_end_date,
) -> list[dict[str, Any]]:
    return _period_valuation_points(
        valuation_points=request.portfolio_data.valuation_points,
        data_policy=request.data_policy,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        entity_type="PORTFOLIO",
        entity_id=request.portfolio_id,
    )


def _position_period_valuation_points(
    *,
    position_data: PositionData | None,
    data_policy: DataPolicy | None,
    period_start_date: date,
    period_end_date: date,
) -> list[dict[str, Any]]:
    if position_data is None:
        return []
    return _period_valuation_points(
        valuation_points=position_data.valuation_points,
        data_policy=data_policy,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        entity_type="POSITION",
        entity_id=position_data.position_id,
    )


def _period_valuation_points(
    *,
    valuation_points: list[PositionDailyData],
    data_policy: DataPolicy | None,
    period_start_date: date,
    period_end_date: date,
    entity_type: str,
    entity_id: str,
) -> list[dict[str, Any]]:
    ordered_points = sorted(valuation_points, key=lambda valuation_point: valuation_point.perf_date)
    period_points = _valuation_points_in_period(ordered_points, period_start_date, period_end_date)
    if not period_points:
        return []

    first_period_date = period_points[0].perf_date
    ignored_dates = _ignored_dates_for_entity(
        data_policy=data_policy,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    if first_period_date in ignored_dates:
        first_period_index = ordered_points.index(period_points[0])
        context_start = _ignored_prefix_context_start(ordered_points, first_period_index, ignored_dates)
        period_points = ordered_points[context_start:first_period_index] + period_points
    return [valuation_point.model_dump(mode="python") for valuation_point in period_points]


def _valuation_points_in_period(
    valuation_points: list[PositionDailyData],
    period_start_date: date,
    period_end_date: date,
) -> list[PositionDailyData]:
    return [
        valuation_point
        for valuation_point in valuation_points
        if period_start_date <= valuation_point.perf_date <= period_end_date
    ]


def _ignored_dates_for_entity(
    *,
    data_policy: DataPolicy | None,
    entity_type: str,
    entity_id: str,
) -> set[date]:
    scoped_policy = contribution_data_policy_for_entity(
        data_policy,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    if scoped_policy is None:
        return set()
    return {date for item in scoped_policy.ignore_days or [] for date in item.dates}


def _ignored_prefix_context_start(
    ordered_points: list[PositionDailyData],
    first_period_index: int,
    ignored_dates: set[date],
) -> int:
    context_start = first_period_index - 1
    while context_start >= 0 and ordered_points[context_start].perf_date in ignored_dates:
        context_start -= 1
    return max(context_start, 0)


def _calculate_position_total_return_pct(
    *,
    request: ContributionRequest,
    position_data: PositionData | None,
    period_start_date,
    period_end_date,
) -> Any:
    period_valuation_points = _position_period_valuation_points(
        position_data=position_data,
        data_policy=request.data_policy,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return _period_engine_final_cum_ror(
        request=request,
        period_valuation_points=period_valuation_points,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        period_type="EXPLICIT",
        entity_type="POSITION",
        entity_id=position_data.position_id if position_data is not None else "",
    )


def _period_engine_final_cum_ror(
    *,
    request: ContributionRequest,
    period_valuation_points: list[dict[str, Any]],
    period_start_date,
    period_end_date,
    period_type,
    result_scale: float = 1.0,
    entity_type: str,
    entity_id: str,
) -> Any:
    if not period_valuation_points:
        return 0.0

    period_engine_config = EngineConfig(
        performance_start_date=max(period_valuation_points[0]["perf_date"], period_start_date),
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
        data_policy=contribution_data_policy_for_entity(
            request.data_policy,
            entity_type=entity_type,
            entity_id=entity_id,
        ),
        ending_value_basis=EndingValueBasis.AFTER_FEES,
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
    decompose_currency: bool,
    selected_average_weight_source_column: str | None = None,
) -> PositionContributionTotals:
    """Builds residual-adjusted contribution totals before response DTO mapping."""
    aggregation = {"total_contribution": ("smoothed_contribution", "sum")}
    if decompose_currency:
        aggregation["local_contribution"] = ("smoothed_local_contribution", "sum")
    position_totals = (
        period_slice_df.groupby("position_id")
        .agg(**aggregation)
        .reset_index()
        .merge(
            average_weight_df[["position_id", *average_weight_columns]],
            on="position_id",
            how="left",
        )
    )
    if selected_average_weight_source_column is not None:
        position_totals[residual_allocation_weight_column] = position_totals[selected_average_weight_source_column]
    if decompose_currency:
        position_totals["fx_contribution"] = (
            position_totals["total_contribution"] - position_totals["local_contribution"]
        )

    sum_of_contributions = _as_numeric(position_totals["total_contribution"].sum())
    residual = total_portfolio_return - sum_of_contributions
    total_average_weight = _as_numeric(position_totals[residual_allocation_weight_column].sum())

    residual_allocation_applied = False
    if total_average_weight > 0 and smoothing_method == "CARINO":
        residual_allocation_applied = abs(residual) > 1e-12
        weight_proportion = position_totals[residual_allocation_weight_column] / total_average_weight
        if decompose_currency:
            currency_shares = position_totals.apply(_position_currency_residual_shares, axis=1)
            position_totals["local_contribution"] += (
                residual * weight_proportion * currency_shares.map(lambda shares: shares[0])
            )
            position_totals["fx_contribution"] += (
                residual * weight_proportion * currency_shares.map(lambda shares: shares[1])
            )
        position_totals["total_contribution"] += residual * weight_proportion
    return PositionContributionTotals(
        totals_df=position_totals,
        residual_allocation_applied=residual_allocation_applied,
    )


def _position_currency_residual_shares(row: pd.Series) -> tuple[float, float]:
    """Do not allocate a peer's FX economics to this position's residual."""
    return _local_fx_residual_proportions(
        local_contribution_sum=_as_numeric(row["local_contribution"]),
        fx_contribution_sum=_as_numeric(row["fx_contribution"]),
        total_contribution_sum=_as_numeric(row["total_contribution"]),
    )


def build_position_contributions(
    *,
    totals_df: pd.DataFrame,
    request: ContributionRequest,
    period_start_date,
    period_end_date,
    average_weight_column: str,
    decompose_currency: bool,
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
            local_contribution=(_as_numeric(row["local_contribution"]) * 100 if decompose_currency else None),
            fx_contribution=(_as_numeric(row["fx_contribution"]) * 100 if decompose_currency else None),
        )
        for _, row in totals_df.iterrows()
    ]
    position_contributions.sort(key=lambda item: abs(item.total_contribution), reverse=True)
    if top_n is not None:
        return position_contributions[:top_n]
    return position_contributions
