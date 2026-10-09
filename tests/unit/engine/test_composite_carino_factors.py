from decimal import Decimal, localcontext

import pytest

from engine.contribution_smoothing import _calculate_carino_factor_for_return


@pytest.mark.parametrize("value", ["0", "1e-18", "-1e-18", "1e-12", "-1e-12", ".02", "-.5"])
def test_strict_decimal_factor_matches_independent_high_precision_log(value):
    ret = Decimal(value)
    with localcontext() as context:
        context.prec = 100
        expected = (1 + ret).ln() / ret if ret else Decimal(1)
    with localcontext() as context:
        context.prec = 80
        actual = _calculate_carino_factor_for_return(ret, strict_decimal=True)
        assert abs(actual - expected) < Decimal("1e-70")


@pytest.mark.parametrize("value", ["-1", "-1.01", "NaN", "Infinity", "-Infinity"])
def test_strict_decimal_factor_refuses_invalid_domain(value):
    with pytest.raises(ValueError):
        _calculate_carino_factor_for_return(Decimal(value), strict_decimal=True)


@pytest.mark.parametrize("value", ["0", "1e-18", "-1", "-1.01"])
def test_legacy_portfolio_fallback_is_preserved(value):
    assert _calculate_carino_factor_for_return(Decimal(value)) == Decimal(1)
