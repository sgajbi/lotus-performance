# tests/unit/core/test_annualize.py
import pytest

from core.annualize import annualize_return, periods_per_year_for_basis
from core.errors import APIBadRequestError


@pytest.mark.parametrize(
    "period_return, num_periods, periods_per_year, basis, expected",
    [
        (0.05, 252, 252, "BUS/252", 0.05),  # Full year, no change
        (0.01, 63, 252, "BUS/252", 0.04060401),  # Quarter to year
        (0.02, 180, 365, "ACT/365", 0.040972),  # Half-year to year - CORRECTED
        (0.10, 540, 365, "ACT/365", 0.066543),  # 1.5 years to year - CORRECTED
        (0.03, 90, 365.25, "ACT/ACT", 0.127451),  # ACT/ACT basis - CORRECTED
    ],
)
def test_annualize_return_happy_path(period_return, num_periods, periods_per_year, basis, expected):
    """Tests various valid annualization scenarios."""
    result = annualize_return(period_return, num_periods, periods_per_year, basis)
    assert result == pytest.approx(expected, abs=1e-6)


def test_annualize_return_invalid_inputs():
    """Tests that annualization raises errors for invalid inputs."""
    with pytest.raises(APIBadRequestError, match="Number of periods for annualization must be positive"):
        annualize_return(0.05, 0, 252, "BUS/252")

    with pytest.raises(APIBadRequestError, match="Periods per year for annualization must be positive"):
        annualize_return(0.05, 252, 0, "BUS/252")


def test_periods_per_year_for_basis_uses_governed_defaults_and_explicit_override():
    assert periods_per_year_for_basis(basis="BUS/252") == pytest.approx(252.0)
    assert periods_per_year_for_basis(basis="ACT/365") == pytest.approx(365.0)
    assert periods_per_year_for_basis(basis="ACT/ACT") == pytest.approx(365.25)
    assert periods_per_year_for_basis(basis="ACT/ACT", periods_per_year=12) == pytest.approx(12.0)


def test_periods_per_year_for_basis_rejects_non_positive_override():
    with pytest.raises(APIBadRequestError, match="Periods per year for annualization must be positive"):
        periods_per_year_for_basis(basis="BUS/252", periods_per_year=0)
