"""Financial request admission; decimal strings are the exact transport form."""

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator

from common.precision_policy import normalize_input


def _admit_decimal(value: Any, semantic_type: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("A finite financial number or decimal string is required.")
    if isinstance(value, float) and abs(value) >= 2**53:  # monetary-float-allow: input type guard
        raise ValueError("Large financial inputs require a decimal string, not a binary64 number.")
    admitted = normalize_input(value, semantic_type)
    if not admitted.is_finite():
        raise ValueError("Financial inputs must be finite.")
    return admitted


def admit_money(value: Any) -> Decimal:
    return _admit_decimal(value, "money")


def admit_fx_rate(value: Any) -> Decimal:
    return _admit_decimal(value, "fx_rate")


MoneyInput = Annotated[Decimal, BeforeValidator(admit_money)]
FXRateInput = Annotated[Decimal, BeforeValidator(admit_fx_rate)]
