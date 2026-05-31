from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.services.contribution_methodology import _numeric_series_or_default
from engine.schema import PortfolioColumns


@dataclass(frozen=True)
class ContributionPeriodFrames:
    period_slice_df: pd.DataFrame
    portfolio_period_slice_df: pd.DataFrame


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
