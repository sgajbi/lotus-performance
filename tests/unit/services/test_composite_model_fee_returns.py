"""Independent rational model-return oracles and meaningful domain refusals."""

from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from app.services.composite_materialization.model_fee_returns import periodic_model_net_return


@pytest.mark.parametrize(
    "gross,fee,numerator,denominator",
    [
        ("0.02", "0.001", 949, 50000),
        ("-0.01", "0.002", -599, 50000),
        ("0.02", "0", 1, 50),
        ("-1", "0.999", -1, 1),
    ],
)
def test_periodic_model_net_matches_independent_fraction(gross, fee, numerator, denominator):
    actual = periodic_model_net_return(Decimal(gross), Decimal(fee))
    assert Fraction(actual) == Fraction(numerator, denominator)


def test_linked_returns_and_fee_factor_match_independent_constants():
    first = periodic_model_net_return(Decimal("0.02"), Decimal("0.001"))
    second = periodic_model_net_return(Decimal("-0.01"), Decimal("0.002"))
    linked = (1 + first) * (1 + second) - 1
    assert Fraction(linked) == Fraction(16931549, 2500000000)
    assert Fraction(Decimal("0.0098") - linked) == Fraction(7568451, 2500000000)


def test_worked_actual_gross_and_model_views_keep_their_independent_fee_bases():
    import pandas as pd

    from engine.config import EndingValueBasis, EngineConfig, PrecisionMode
    from engine.runtime import run_engine_for_valuation_points
    from engine.schema import PortfolioColumns

    # Existing actual-fee convention: source end assets 1090 already include
    # the real -10 management posting; it is not an external cash withdrawal.
    points = [
        {"perf_date": "2025-01-01", "begin_mv": Decimal("1000"), "end_mv": Decimal("1090"), "mgmt_fees": Decimal("-10")}
    ]
    returns = {}
    for basis, expected in (("GROSS", Fraction(1, 10)), ("NET", Fraction(9, 100))):
        result = run_engine_for_valuation_points(
            points,
            EngineConfig(
                performance_start_date=pd.Timestamp("2025-01-01").date(),
                report_start_date=pd.Timestamp("2025-01-01").date(),
                report_end_date=pd.Timestamp("2025-01-01").date(),
                period_type="EXPLICIT",
                metric_basis=basis,
                precision_mode=PrecisionMode.DECIMAL_STRICT,
                ending_value_basis=EndingValueBasis.AFTER_FEES,
            ),
        )
        returns[basis] = result[PortfolioColumns.DAILY_ROR.value].iloc[0] / 100
        assert Fraction(returns[basis]) == expected
    model = periodic_model_net_return(returns["GROSS"], Decimal("0.001"))
    assert Fraction(model) == Fraction(989, 10000)
    assert model != returns["NET"]
    assert points[0]["end_mv"] == Decimal("1090") and points[0]["mgmt_fees"] == Decimal("-10")


def test_heterogeneous_fees_transform_members_before_weighting():
    first = periodic_model_net_return(Decimal("0.02"), Decimal("0.001"))
    second = periodic_model_net_return(Decimal("-0.01"), Decimal("0.002"))
    weighted = (100 * first + 300 * second) / 400
    assert Fraction(weighted) == Fraction(-53, 12500)
    incorrect = periodic_model_net_return(Decimal("-0.0025"), Decimal("0.00175"))
    assert Fraction(weighted - incorrect) == Fraction(9, 1600000)


def test_transform_retains_coefficients_under_low_ambient_precision():
    with localcontext() as context:
        context.prec = 6
        actual = periodic_model_net_return(Decimal("0.020000000000000000000000000000001"), Decimal("0.001"))
    assert actual == Decimal("0.018980000000000000000000000000000999")


@pytest.mark.parametrize(
    "gross,fee",
    [
        ("NaN", "0"),
        ("Infinity", "0"),
        ("-1.001", "0"),
        ("0.02", "NaN"),
        ("0.02", "Infinity"),
        ("0.02", "-0.001"),
        ("0.02", "1"),
        ("0.02", "1.01"),
        ("0.02", "1E-5000"),
    ],
)
def test_unsupported_financial_or_representation_domain_refused(gross, fee):
    with pytest.raises(ValueError):
        periodic_model_net_return(Decimal(gross), Decimal(fee))
