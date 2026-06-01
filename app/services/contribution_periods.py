from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.services.contribution_diagnostics import _calculate_position_flow_balance_counts
from app.services.contribution_methodology import (
    _calculate_reset_aware_average_weight_shadow,
    _numeric_series_or_default,
)
from engine.schema import PortfolioColumns


@dataclass(frozen=True)
class ContributionPeriodFrames:
    period_slice_df: pd.DataFrame
    portfolio_period_slice_df: pd.DataFrame


@dataclass(frozen=True)
class ContributionPeriodMethodologyContext:
    average_weight_shadow_df: pd.DataFrame
    delta_positions: int
    max_shadow_delta_bp: int
    sum_shadow_delta_bp: int
    position_reset_dates: set[date]
    portfolio_reset_dates: set[date]
    position_flow_balance_counts: dict[str, int]

    @property
    def portfolio_reset_without_position_reset_days(self) -> int:
        return len(self.portfolio_reset_dates - self.position_reset_dates)

    @property
    def position_reset_without_portfolio_reset_days(self) -> int:
        return len(self.position_reset_dates - self.portfolio_reset_dates)


def _slice_contribution_period_frames(
    *,
    daily_contributions_df: pd.DataFrame,
    portfolio_results_df: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> ContributionPeriodFrames:
    contribution_date_series = pd.to_datetime(daily_contributions_df[PortfolioColumns.PERF_DATE.value]).dt.date
    portfolio_date_series = pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date

    return ContributionPeriodFrames(
        period_slice_df=daily_contributions_df[
            (contribution_date_series >= start_date) & (contribution_date_series <= end_date)
        ].copy(),
        portfolio_period_slice_df=portfolio_results_df[
            (portfolio_date_series >= start_date) & (portfolio_date_series <= end_date)
        ],
    )


def _build_contribution_period_methodology_context(
    *,
    period_slice_df: pd.DataFrame,
    portfolio_period_slice_df: pd.DataFrame,
) -> ContributionPeriodMethodologyContext:
    (
        average_weight_shadow_df,
        delta_positions,
        max_shadow_delta_bp,
        sum_shadow_delta_bp,
    ) = _calculate_reset_aware_average_weight_shadow(
        period_slice_df,
        portfolio_period_slice_df,
    )

    return ContributionPeriodMethodologyContext(
        average_weight_shadow_df=average_weight_shadow_df,
        delta_positions=delta_positions,
        max_shadow_delta_bp=max_shadow_delta_bp,
        sum_shadow_delta_bp=sum_shadow_delta_bp,
        position_reset_dates=_extract_reset_dates(period_slice_df),
        portfolio_reset_dates=_extract_reset_dates(portfolio_period_slice_df),
        position_flow_balance_counts=_calculate_position_flow_balance_counts(
            period_slice_df,
            portfolio_period_slice_df,
        ),
    )


def _extract_reset_dates(period_df: pd.DataFrame) -> set[date]:
    if period_df.empty or PortfolioColumns.PERF_DATE.value not in period_df.columns:
        return set()

    reset_rows = _numeric_series_or_default(period_df, PortfolioColumns.PERF_RESET.value) == 1
    return set(
        pd.to_datetime(
            period_df.loc[
                reset_rows,
                PortfolioColumns.PERF_DATE.value,
            ]
        ).dt.date
    )
