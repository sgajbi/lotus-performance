# core/annualize.py
from typing import Literal

from .errors import APIBadRequestError

BasisType = Literal["BUS/252", "ACT/365", "ACT/ACT"]


def periods_per_year_for_basis(*, basis: BasisType, periods_per_year: float | None = None) -> float:
    if periods_per_year is not None:
        if periods_per_year <= 0:
            raise APIBadRequestError("Periods per year for annualization must be positive.")
        return periods_per_year
    if basis == "BUS/252":
        return 252.0
    if basis == "ACT/ACT":
        return 365.25
    return 365.0


# monetary-float-allow: period_return is a dimensionless ratio and periods_per_year is a
# day-count divisor (252.0 / 365.25 / 365.0). Neither is a monetary amount, so this is
# outside the monetary-float rule rather than deferred debt. See docs/standards/rounding-precision.md.
def annualize_return(
    period_return: float,  # monetary-float-allow
    num_periods: int,
    periods_per_year: float,  # monetary-float-allow
    basis: BasisType,
) -> float:  # monetary-float-allow
    """
    Annualizes a period return using geometric compounding.

    Args:
        period_return: The return for the entire period (e.g., 0.05 for 5%).
        num_periods: The number of periods in the given timeframe (e.g., number of days).
        periods_per_year: The number of periods in a year (e.g., 252 for business days).
        basis: The annualization basis, used for validation.

    Returns:
        The annualized return.
    """
    if num_periods <= 0:
        raise APIBadRequestError("Number of periods for annualization must be positive.")

    if periods_per_year <= 0:
        raise APIBadRequestError("Periods per year for annualization must be positive.")

    scale = periods_per_year / num_periods
    return (1 + period_return) ** scale - 1
