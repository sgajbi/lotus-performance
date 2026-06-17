from decimal import Decimal

from app.services.runtime_degradation_policy import (
    _is_supported_threshold,
    _threshold_comparison_is_breached,
    threshold_breach_flag,
    threshold_breach_values,
)


def test_supported_threshold_requires_positive_threshold():
    assert _is_supported_threshold(Decimal("0.01"))
    assert not _is_supported_threshold(Decimal("0"))
    assert not _is_supported_threshold(Decimal("-1"))


def test_threshold_comparison_policy_supports_upper_and_lower_bounds():
    assert _threshold_comparison_is_breached(
        observed_decimal=Decimal("10"),
        threshold_decimal=Decimal("10"),
        comparison="at_or_above",
    )
    assert not _threshold_comparison_is_breached(
        observed_decimal=Decimal("9"),
        threshold_decimal=Decimal("10"),
        comparison="at_or_above",
    )
    assert _threshold_comparison_is_breached(
        observed_decimal=Decimal("10"),
        threshold_decimal=Decimal("10"),
        comparison="at_or_below",
    )
    assert not _threshold_comparison_is_breached(
        observed_decimal=Decimal("11"),
        threshold_decimal=Decimal("10"),
        comparison="at_or_below",
    )


def test_threshold_breach_values_use_governed_ceiling_semantics():
    assert threshold_breach_values(observed_value=100, threshold_value=0) is None
    assert threshold_breach_values(observed_value=9, threshold_value=10) is None

    breached = threshold_breach_values(observed_value=10, threshold_value=10)

    assert breached == (Decimal("10"), Decimal("10"))


def test_threshold_breach_flag_supports_lower_bound_semantics():
    assert threshold_breach_flag(observed_value=100, threshold_value=0, comparison="at_or_below") == 0
    assert threshold_breach_flag(observed_value=11, threshold_value=10, comparison="at_or_below") == 0
    assert threshold_breach_flag(observed_value=10, threshold_value=10, comparison="at_or_below") == 1
