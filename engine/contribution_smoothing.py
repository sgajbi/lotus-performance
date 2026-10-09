from decimal import Decimal
from typing import Protocol

import numpy as np
import pandas as pd

from engine.schema import PortfolioColumns

CARINO_ZERO_RETURN_TOLERANCE = 1e-12
DECIMAL_CARINO_ZERO_RETURN_TOLERANCE = Decimal("1e-12")


class ContributionSmoothingLike(Protocol):
    method: str


def _calculate_carino_factor_for_return(
    portfolio_return: Decimal | float,  # monetary-float-allow: dimensionless return
    *,
    strict_decimal: bool = False,
) -> Decimal | float:  # monetary-float-allow: dimensionless Carino factor
    """Returns the Carino linking factor for a single return when the log domain is valid.

    Domain meaning:
    Carino smoothing relies on ``log(1 + r)``, so it is only defined while the linked gross return
    factor remains strictly positive. When the portfolio path falls to ``-100%`` or below, that
    assumption breaks and the caller must avoid Carino adjustments for that episode.
    """
    if isinstance(portfolio_return, Decimal):
        one = Decimal(1)
        if strict_decimal:
            if not portfolio_return.is_finite() or portfolio_return <= -one:
                raise ValueError("Carino requires a finite return strictly above -100%")
            if abs(portfolio_return) <= DECIMAL_CARINO_ZERO_RETURN_TOLERANCE:
                # log1p(r)/r's continuous series avoids losing 1+r at tiny r.
                # Six terms leave absolute error below 1e-72 in this interval.
                return one + sum(((-portfolio_return) ** n / Decimal(n + 1) for n in range(1, 6)), Decimal(0))
            return (one + portfolio_return).ln() / portfolio_return
        if one + portfolio_return <= 0:
            return one
        if abs(portfolio_return) <= DECIMAL_CARINO_ZERO_RETURN_TOLERANCE:
            return one
        return (one + portfolio_return).ln() / portfolio_return

    if 1.0 + portfolio_return <= 0:
        return 1.0
    if np.isclose(portfolio_return, 0.0, atol=CARINO_ZERO_RETURN_TOLERANCE):
        return 1.0
    return float(np.log1p(portfolio_return) / portfolio_return)  # monetary-float-allow: dimensionless Carino factor


def _carino_smoothing_domain_is_valid(portfolio_return_series: pd.Series) -> bool:
    """Reports whether Carino smoothing is mathematically valid for a linked portfolio path."""
    for portfolio_return in portfolio_return_series:
        if pd.isna(portfolio_return):
            return False
        one = Decimal(1) if isinstance(portfolio_return, Decimal) else 1.0
        if one + portfolio_return <= 0:
            return False
    return True


def _calculate_carino_factors(ror_series: pd.Series) -> pd.Series:
    """Calculates daily Carino factors for returns that remain inside the valid log domain."""
    if not isinstance(ror_series.index, pd.DatetimeIndex):
        ror_series.index = pd.to_datetime(ror_series.index)

    factors = [_calculate_carino_factor_for_return(portfolio_return) for portfolio_return in ror_series]
    return pd.Series(
        factors,
        index=ror_series.index,
        dtype=object if any(isinstance(value, Decimal) for value in factors) else None,
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
    decimal_mode = any(
        isinstance(value, Decimal)
        for value in portfolio_df_indexed[PortfolioColumns.DAILY_ROR.value]
        if pd.notna(value)
    )
    hundred = Decimal(100) if decimal_mode else 100.0
    one = Decimal(1) if decimal_mode else 1.0
    port_ror_series = portfolio_df_indexed[PortfolioColumns.DAILY_ROR.value] / hundred
    if not _carino_smoothing_domain_is_valid(port_ror_series):
        contribution_df["smoothed_local_contribution"] = contribution_df["raw_local_contribution"]
        contribution_df["smoothed_fx_contribution"] = contribution_df["raw_fx_contribution"]
        contribution_df["smoothed_contribution"] = contribution_df["raw_contribution"]
        return contribution_df

    k_daily = _calculate_carino_factors(port_ror_series)
    port_total_ror = (one + port_ror_series).prod() - one
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
