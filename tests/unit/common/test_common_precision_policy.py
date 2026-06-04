from decimal import Decimal

import pytest

from common.precision_policy import (
    ROUNDING_POLICY_VERSION,
    normalize_input,
    quantize_fx_rate,
    quantize_money,
    quantize_performance,
    quantize_price,
    quantize_quantity,
    quantize_risk,
    to_decimal,
)


def test_common_precision_policy_exposes_canonical_quantizers() -> None:
    assert quantize_money("1.005") == Decimal("1.00")
    assert quantize_price("10.1234567") == Decimal("10.123457")
    assert quantize_fx_rate("1.234567895") == Decimal("1.23456790")
    assert quantize_quantity("100.1234567") == Decimal("100.123457")
    assert quantize_performance("0.123456789") == Decimal("0.123457")
    assert quantize_risk("0.22222229") == Decimal("0.222222")


def test_common_precision_policy_preserves_input_validation() -> None:
    assert ROUNDING_POLICY_VERSION == "1.1.0"
    assert normalize_input("0.123456789012", "performance") == Decimal("0.123456789012")

    with pytest.raises(ValueError, match="money scale 9 exceeds max 8"):
        normalize_input("12.123456789", "money")


def test_common_precision_policy_rejects_invalid_decimal_values() -> None:
    with pytest.raises(ValueError):
        to_decimal("bad-number")
