from typing import Protocol

import numpy as np
import pandas as pd

from engine.schema import PortfolioColumns

CARINO_ZERO_RETURN_TOLERANCE = 1e-12


class ContributionSmoothingLike(Protocol):
    method: str


def _calculate_carino_factor_for_return(portfolio_return: float) -> float:
    """Returns the Carino linking factor for a single return when the log domain is valid.

    Domain meaning:
    Carino smoothing relies on ``log(1 + r)``, so it is only defined while the linked gross return
    factor remains strictly positive. When the portfolio path falls to ``-100%`` or below, that
    assumption breaks and the caller must avoid Carino adjustments for that episode.
    """
    if 1 + portfolio_return <= 0:
        return 1.0
    if np.isclose(portfolio_return, 0.0, atol=CARINO_ZERO_RETURN_TOLERANCE):
        return 1.0
    return float(np.log1p(portfolio_return) / portfolio_return)


def _carino_smoothing_domain_is_valid(portfolio_return_series: pd.Series) -> bool:
    """Reports whether Carino smoothing is mathematically valid for a linked portfolio path."""
    numeric_returns = pd.to_numeric(portfolio_return_series, errors="coerce")
    gross_return_factors = 1 + numeric_returns
    return bool(gross_return_factors.gt(0).all())


def _calculate_carino_factors(ror_series: pd.Series) -> pd.Series:
    """Calculates daily Carino factors for returns that remain inside the valid log domain."""
    if not isinstance(ror_series.index, pd.DatetimeIndex):
        ror_series.index = pd.to_datetime(ror_series.index)

    return pd.Series(
        [_calculate_carino_factor_for_return(float(portfolio_return)) for portfolio_return in ror_series],
        index=ror_series.index,
    )


def apply_contribution_smoothing(
    contribution_df: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    smoothing: ContributionSmoothingLike,
) -> pd.DataFrame:
    """Adds smoothed contribution columns to a daily contribution frame.

    The calculation intentionally preserves the current RFC-047 baseline behavior. Slice 3 owns
    methodology correction and deterministic Carino proof; this module only isolates the smoothing
    responsibility so the correction is easier to reason about.
    """
    if smoothing.method != "CARINO":
        contribution_df["smoothed_local_contribution"] = contribution_df["raw_local_contribution"]
        contribution_df["smoothed_fx_contribution"] = contribution_df["raw_fx_contribution"]
        contribution_df["smoothed_contribution"] = contribution_df["raw_contribution"]
        return contribution_df

    portfolio_df_indexed = portfolio_df.set_index(PortfolioColumns.PERF_DATE.value)
    port_ror_series = portfolio_df_indexed[PortfolioColumns.DAILY_ROR.value] / 100
    if not _carino_smoothing_domain_is_valid(port_ror_series):
        contribution_df["smoothed_local_contribution"] = contribution_df["raw_local_contribution"]
        contribution_df["smoothed_fx_contribution"] = contribution_df["raw_fx_contribution"]
        contribution_df["smoothed_contribution"] = contribution_df["raw_contribution"]
        return contribution_df

    k_daily = _calculate_carino_factors(port_ror_series)
    port_total_ror = float((1 + port_ror_series).prod() - 1)
    k_total = _calculate_carino_factor_for_return(port_total_ror)

    contribution_df = pd.merge(
        contribution_df,
        k_daily.rename("k_t"),
        left_on=PortfolioColumns.PERF_DATE.value,
        right_index=True,
    )
    contribution_df["K_total"] = k_total
    contribution_df["R_port_t"] = contribution_df[PortfolioColumns.PERF_DATE.value].map(port_ror_series)
    contribution_df["carino_factor"] = contribution_df["k_t"] / contribution_df["K_total"]

    contribution_df["smoothed_contribution"] = (
        contribution_df["raw_contribution"] * contribution_df["carino_factor"]
    ).fillna(contribution_df["raw_contribution"])
    contribution_df["smoothed_local_contribution"] = (
        contribution_df["raw_local_contribution"] * contribution_df["carino_factor"]
    ).fillna(contribution_df["raw_local_contribution"])
    contribution_df["smoothed_fx_contribution"] = (
        contribution_df["smoothed_contribution"] - contribution_df["smoothed_local_contribution"]
    )
    return contribution_df
