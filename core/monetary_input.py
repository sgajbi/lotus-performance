"""Financial request admission; decimal strings are the exact transport form."""

from decimal import Decimal
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, BeforeValidator, ValidationError, ValidationInfo

from common.precision_policy import normalize_input, to_decimal
from core.errors import APIUnprocessableEntityError

_Model = TypeVar("_Model", bound=BaseModel)
_CALCULATED_MONEY_ORIGIN = object()


def _admit_decimal(value: Any, semantic_type: str, *, calculated_money: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("A finite financial number or decimal string is required.")
    if isinstance(value, float) and abs(value) >= 2**53:  # monetary-float-allow: input type guard
        raise ValueError("Large financial inputs require a decimal string, not a binary64 number.")
    admitted = to_decimal(value) if calculated_money else normalize_input(value, semantic_type)
    if not admitted.is_finite():
        raise ValueError("Financial inputs must be finite.")
    return admitted


def admit_money(value: Any, info: ValidationInfo) -> Decimal:
    # Raw bank imports obey the input-scale policy. Core's calculated Decimal
    # outputs and retained admitted calculations have a different contract: do
    # not quantize them back to a raw-import quantum. HTTP input cannot supply
    # this private context identity; finite/boolean/unsafe-float guards still run.
    calculated_money = info.context is _CALCULATED_MONEY_ORIGIN
    return _admit_decimal(value, "money", calculated_money=calculated_money)


def validate_calculated_money_model(model_type: type[_Model], payload: object) -> _Model:
    """Admit calculated/retained evidence, never an unvalidated public import."""
    try:
        return model_type.model_validate(payload, context=_CALCULATED_MONEY_ORIGIN)
    except ValidationError as exc:
        raise APIUnprocessableEntityError(
            "Calculated financial evidence violates the supported input contract.",
            error_code="CALCULATED_FINANCIAL_INPUT_INVALID",
        ) from exc


def admit_fx_rate(value: Any) -> Decimal:
    return _admit_decimal(value, "fx_rate")


MoneyInput = Annotated[Decimal, BeforeValidator(admit_money)]
FXRateInput = Annotated[Decimal, BeforeValidator(admit_fx_rate)]
