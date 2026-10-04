from decimal import Decimal, Overflow

import pytest

from engine.composite_annual_dispersion import (
    AnnualDispersionDomainError,
    AnnualMemberReturn,
    calculate_annual_dispersion,
    link_full_year_member_return,
)


def test_sample_annual_dispersion_matches_independent_or11():
    members = [AnnualMemberReturn(str(i), Decimal(i) / 100, Decimal(100)) for i in range(1, 7)]
    result = calculate_annual_dispersion(members, method="EQUAL_WEIGHT_SAMPLE_STDDEV")
    assert result == Decimal("0.018708286934")
    assert calculate_annual_dispersion(list(reversed(members)), method="EQUAL_WEIGHT_SAMPLE_STDDEV") == result


def test_year_begin_asset_weighted_population_is_a_distinct_estimator():
    members = [
        AnnualMemberReturn("A", Decimal(".01"), Decimal(100)),
        AnnualMemberReturn("B", Decimal(".06"), Decimal(300)),
    ]
    assert calculate_annual_dispersion(members, method="YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV") == Decimal(
        ".021650635095"
    )


def test_five_members_remain_financially_computable():
    members = [AnnualMemberReturn(str(i), Decimal(i) / 100, Decimal(100)) for i in range(1, 6)]
    assert calculate_annual_dispersion(members, method="EQUAL_WEIGHT_SAMPLE_STDDEV") == Decimal(".015811388301")
    assert calculate_annual_dispersion(members[:1], method="EQUAL_WEIGHT_SAMPLE_STDDEV") is None


@pytest.mark.parametrize("value", ["-.25", "0", ".00000001", "-1"])
def test_annual_link_preserves_loss_zero_near_zero_and_total_loss(value):
    assert link_full_year_member_return([Decimal(value)] + [Decimal(0)] * 11) == Decimal(value)


@pytest.mark.parametrize(
    "values", [[Decimal(0)] * 11, [Decimal("-1.000001")] + [Decimal(0)] * 11, [Decimal("NaN")] + [Decimal(0)] * 11]
)
def test_annual_link_refuses_incomplete_or_invalid_domain(values):
    with pytest.raises(AnnualDispersionDomainError):
        link_full_year_member_return(values)


@pytest.mark.parametrize("asset", ["0", "-1", "NaN"])
def test_weighted_estimator_refuses_nonpositive_or_invalid_assets(asset):
    with pytest.raises(AnnualDispersionDomainError):
        calculate_annual_dispersion(
            [AnnualMemberReturn("A", Decimal(".1"), Decimal(asset))],
            method="YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV",
        )


def test_zero_dispersion_is_observed_and_duplicate_member_is_refused():
    a = AnnualMemberReturn("A", Decimal("-.1"), Decimal(100))
    b = AnnualMemberReturn("B", Decimal("-.1"), Decimal(300))
    assert calculate_annual_dispersion([a, b], method="EQUAL_WEIGHT_SAMPLE_STDDEV") == Decimal(0)
    with pytest.raises(AnnualDispersionDomainError):
        calculate_annual_dispersion([a, a], method="EQUAL_WEIGHT_SAMPLE_STDDEV")


def test_or10_independent_time_series_contrast_is_not_member_dispersion():
    # 24 nonzero observations with mean zero: sum squares .0024, sample denominator 35.
    variance = Decimal(".0024") / 35
    volatility = variance.sqrt() * Decimal(12).sqrt()
    assert abs(volatility - Decimal(".02868548662402544735925161231")) < Decimal("1e-26")
    assert volatility != Decimal(".018708286934")


@pytest.mark.parametrize("value", ["1e129", "1e-129"])
def test_registered_decimal_magnitude_limit_refuses_unbounded_economics(value):
    with pytest.raises(AnnualDispersionDomainError):
        link_full_year_member_return([Decimal(value)] + [Decimal(0)] * 11)


def test_method_rounding_is_independent_of_caller_decimal_context():
    from decimal import ROUND_FLOOR, localcontext

    members = [AnnualMemberReturn(str(i), Decimal(i) / 100, Decimal(100)) for i in range(1, 7)]
    with localcontext() as context:
        context.rounding = ROUND_FLOOR
        context.prec = 9
        assert calculate_annual_dispersion(members, method="EQUAL_WEIGHT_SAMPLE_STDDEV") == Decimal(".018708286934")
        assert link_full_year_member_return([Decimal(".01")] * 12) == Decimal(".126825030131969720661201")


def test_registered_member_limit_refuses_oversized_population():
    members = [AnnualMemberReturn(str(i), Decimal(0), Decimal(100)) for i in range(1001)]
    with pytest.raises(AnnualDispersionDomainError):
        calculate_annual_dispersion(members, method="EQUAL_WEIGHT_SAMPLE_STDDEV")


def test_complete_year_linking_refuses_arithmetic_overflow_inside_input_magnitude_domain():
    with pytest.raises(AnnualDispersionDomainError, match="Annual linking exceeds the Decimal domain") as refused:
        link_full_year_member_return([Decimal("1e128")] * 12)
    assert isinstance(refused.value.__cause__, Overflow)


def test_weighted_population_refuses_variance_overflow_inside_input_magnitude_domain():
    members = [
        AnnualMemberReturn("A", Decimal("1e128"), Decimal("1e128")),
        AnnualMemberReturn("B", Decimal(0), Decimal("1e128")),
    ]
    with pytest.raises(AnnualDispersionDomainError, match="Dispersion exceeds the Decimal domain") as refused:
        calculate_annual_dispersion(members, method="YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV")
    assert isinstance(refused.value.__cause__, Overflow)


def test_annual_estimator_refuses_negative_growth_independently_of_monthly_linking():
    with pytest.raises(AnnualDispersionDomainError, match="Negative annual growth factors are unsupported"):
        calculate_annual_dispersion(
            [AnnualMemberReturn("A", Decimal("-1.000001"), Decimal(100))],
            method="EQUAL_WEIGHT_SAMPLE_STDDEV",
        )


def test_annual_engine_refuses_unregistered_method_before_selecting_an_estimator():
    with pytest.raises(AnnualDispersionDomainError, match="Dispersion method is unsupported"):
        calculate_annual_dispersion([], method="UNREGISTERED")


def test_valid_single_member_weighted_population_has_insufficient_dispersion_observations():
    assert (
        calculate_annual_dispersion(
            [AnnualMemberReturn("A", Decimal(".01"), Decimal(100))],
            method="YEAR_BEGIN_ASSET_WEIGHTED_POPULATION_STDDEV",
        )
        is None
    )
