from decimal import Decimal

from app.services.runtime_degradation_policy import threshold_breach_flag, threshold_breach_values


def test_threshold_breach_values_use_governed_ceiling_semantics():
    assert threshold_breach_values(observed_value=100, threshold_value=0) is None
    assert threshold_breach_values(observed_value=9, threshold_value=10) is None

    breached = threshold_breach_values(observed_value=10, threshold_value=10)

    assert breached == (Decimal("10"), Decimal("10"))


def test_threshold_breach_flag_supports_lower_bound_semantics():
    assert threshold_breach_flag(observed_value=100, threshold_value=0, comparison="at_or_below") == 0
    assert threshold_breach_flag(observed_value=11, threshold_value=10, comparison="at_or_below") == 0
    assert threshold_breach_flag(observed_value=10, threshold_value=10, comparison="at_or_below") == 1
