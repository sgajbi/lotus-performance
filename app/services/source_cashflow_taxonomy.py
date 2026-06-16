from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CashflowEconomicsRole = Literal["fee", "external", "internal", "unsupported", "missing"]
CashflowTypeClassificationRule = tuple[CashflowEconomicsRole, bool, bool]

_CANONICAL_FEE_TYPES = {"fee"}
_CANONICAL_EXTERNAL_TYPES = {"external_flow", "transfer"}
_CANONICAL_INTERNAL_TYPES = {"internal_trade_flow"}
_FEE_LIKE_ALIASES = {
    "advisory_fee",
    "custody_fee",
    "management_fee",
    "platform_fee",
}
_EXTERNAL_LIKE_ALIASES = {
    "capital_call",
    "contribution",
    "deposit",
    "redemption",
    "subscription",
    "transfer_in",
    "transfer_out",
    "withdrawal",
}
_INCOME_LIKE_UNSUPPORTED_TYPES = {
    "coupon",
    "dividend",
    "distribution",
    "interest",
    "tax",
}
_CASHFLOW_TYPE_CLASSIFICATION_RULES: dict[str, CashflowTypeClassificationRule] = {
    **{cashflow_type: ("fee", True, False) for cashflow_type in _CANONICAL_FEE_TYPES},
    **{cashflow_type: ("external", True, False) for cashflow_type in _CANONICAL_EXTERNAL_TYPES},
    **{cashflow_type: ("internal", True, False) for cashflow_type in _CANONICAL_INTERNAL_TYPES},
    **{cashflow_type: ("fee", False, True) for cashflow_type in _FEE_LIKE_ALIASES},
    **{cashflow_type: ("external", False, True) for cashflow_type in _EXTERNAL_LIKE_ALIASES},
    **{cashflow_type: ("unsupported", False, False) for cashflow_type in _INCOME_LIKE_UNSUPPORTED_TYPES},
}


@dataclass(frozen=True)
class CashflowTypeClassification:
    raw_value: object
    normalized_value: str | None
    economics_role: CashflowEconomicsRole
    canonical: bool
    governed_alias: bool


def classify_cashflow_type(raw_value: object) -> CashflowTypeClassification:
    normalized_value = _normalize_cashflow_type(raw_value)
    if normalized_value is None:
        return CashflowTypeClassification(
            raw_value=raw_value,
            normalized_value=None,
            economics_role="missing",
            canonical=False,
            governed_alias=False,
        )
    economics_role, canonical, governed_alias = _cashflow_type_classification_rule(normalized_value)
    return CashflowTypeClassification(
        raw_value=raw_value,
        normalized_value=normalized_value,
        economics_role=economics_role,
        canonical=canonical,
        governed_alias=governed_alias,
    )


def _cashflow_type_classification_rule(normalized_value: str) -> CashflowTypeClassificationRule:
    return _CASHFLOW_TYPE_CLASSIFICATION_RULES.get(normalized_value, ("unsupported", False, False))


def _normalize_cashflow_type(raw_value: object) -> str | None:
    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip().lower()
    return normalized_value or None
