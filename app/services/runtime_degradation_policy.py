from __future__ import annotations

from decimal import Decimal
from typing import Literal

ThresholdComparison = Literal["at_or_above", "at_or_below"]


def as_decimal_number(value: object) -> Decimal:
    return Decimal(str(value))


def threshold_breach_values(
    *,
    observed_value: object,
    threshold_value: object,
    comparison: ThresholdComparison = "at_or_above",
) -> tuple[Decimal, Decimal] | None:
    observed_decimal = as_decimal_number(observed_value)
    threshold_decimal = as_decimal_number(threshold_value)
    if threshold_decimal <= 0:
        return None
    if comparison == "at_or_above" and observed_decimal < threshold_decimal:
        return None
    if comparison == "at_or_below" and observed_decimal > threshold_decimal:
        return None
    return observed_decimal, threshold_decimal


def threshold_breach_flag(
    *,
    observed_value: object,
    threshold_value: object,
    comparison: ThresholdComparison = "at_or_above",
) -> int:
    return (
        1
        if threshold_breach_values(
            observed_value=observed_value,
            threshold_value=threshold_value,
            comparison=comparison,
        )
        else 0
    )
