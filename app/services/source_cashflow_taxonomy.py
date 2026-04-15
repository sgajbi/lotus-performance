from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CashflowEconomicsRole = Literal["fee", "external", "unsupported", "missing"]

_CANONICAL_FEE_TYPES = {"fee"}
_CANONICAL_EXTERNAL_TYPES = {"external_flow"}
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
    if normalized_value in _CANONICAL_FEE_TYPES:
        return CashflowTypeClassification(
            raw_value=raw_value,
            normalized_value=normalized_value,
            economics_role="fee",
            canonical=True,
            governed_alias=False,
        )
    if normalized_value in _CANONICAL_EXTERNAL_TYPES:
        return CashflowTypeClassification(
            raw_value=raw_value,
            normalized_value=normalized_value,
            economics_role="external",
            canonical=True,
            governed_alias=False,
        )
    if normalized_value in _FEE_LIKE_ALIASES:
        return CashflowTypeClassification(
            raw_value=raw_value,
            normalized_value=normalized_value,
            economics_role="fee",
            canonical=False,
            governed_alias=True,
        )
    if normalized_value in _EXTERNAL_LIKE_ALIASES:
        return CashflowTypeClassification(
            raw_value=raw_value,
            normalized_value=normalized_value,
            economics_role="external",
            canonical=False,
            governed_alias=True,
        )
    if normalized_value in _INCOME_LIKE_UNSUPPORTED_TYPES:
        return CashflowTypeClassification(
            raw_value=raw_value,
            normalized_value=normalized_value,
            economics_role="unsupported",
            canonical=False,
            governed_alias=False,
        )
    return CashflowTypeClassification(
        raw_value=raw_value,
        normalized_value=normalized_value,
        economics_role="unsupported",
        canonical=False,
        governed_alias=False,
    )


def _normalize_cashflow_type(raw_value: object) -> str | None:
    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip().lower()
    return normalized_value or None
