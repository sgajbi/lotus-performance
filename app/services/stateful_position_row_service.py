from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from app.services.currency_code_normalization import normalized_currency_code
from app.services.source_cashflow_taxonomy import CashflowTypeClassification, classify_cashflow_type
from core.errors import APIUnprocessableEntityError

PositionValueBasis = Literal["position", "portfolio", "reporting"]


def position_cash_flows_are_losslessly_normalizable(
    cash_flows_raw: object,
    *,
    row: dict[str, object] | None = None,
    value_basis: PositionValueBasis = "position",
    portfolio_currency: str | None = None,
    reporting_currency: str | None = None,
) -> bool:
    """Report whether every supplied nested cash-flow row has calculable semantics."""
    if not isinstance(cash_flows_raw, list):
        return False
    if not cash_flows_raw:
        return True
    source_row = row or {}
    if not _cash_flow_conversion_evidence_is_complete(
        cash_flows_raw=cash_flows_raw,
        row=source_row,
        value_basis=value_basis,
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    ):
        return False
    conversion_factor = _cash_flow_conversion_factor(row=source_row, value_basis=value_basis)
    if not conversion_factor.is_finite() or conversion_factor <= 0:
        return False
    return all(_cash_flow_is_losslessly_projected(flow, conversion_factor=conversion_factor) for flow in cash_flows_raw)


def _cash_flow_conversion_evidence_is_complete(
    *,
    cash_flows_raw: list[object],
    row: dict[str, object],
    value_basis: PositionValueBasis,
    portfolio_currency: str | None,
    reporting_currency: str | None,
) -> bool:
    if not _cash_flows_require_conversion(cash_flows_raw):
        return True
    return _required_cash_flow_conversion_rates_are_present(
        row=row,
        value_basis=value_basis,
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    )


def _cash_flows_require_conversion(cash_flows: list[object]) -> bool:
    return any(_cash_flow_requires_conversion(flow) for flow in cash_flows)


def _cash_flow_requires_conversion(flow: object) -> bool:
    projected_flow = _position_cash_flow_projection(flow, conversion_factor=Decimal("1"))
    return projected_flow is not None and projected_flow[1] != 0 and projected_flow[2].economics_role != "unsupported"


def _cash_flow_is_losslessly_projected(flow: object, *, conversion_factor: Decimal) -> bool:
    projected_flow = _position_cash_flow_projection(flow, conversion_factor=conversion_factor)
    return projected_flow is not None and projected_flow[2].economics_role != "unsupported"


def _required_cash_flow_conversion_rates_are_present(
    *,
    row: dict[str, object],
    value_basis: PositionValueBasis,
    portfolio_currency: str | None,
    reporting_currency: str | None,
) -> bool:
    if value_basis == "position":
        return True
    if not _currency_conversion_evidence_is_complete(
        source_currency=row.get("position_currency"),
        target_currency=portfolio_currency,
        rate=row.get("position_to_portfolio_fx_rate"),
    ):
        return False
    if value_basis != "reporting":
        return True
    return _currency_conversion_evidence_is_complete(
        source_currency=portfolio_currency,
        target_currency=reporting_currency,
        rate=row.get("portfolio_to_reporting_fx_rate"),
    )


def _currency_conversion_evidence_is_complete(
    *,
    source_currency: object,
    target_currency: object,
    rate: object,
) -> bool:
    normalized_source_currency = normalized_currency_code(source_currency)
    normalized_target_currency = normalized_currency_code(target_currency)
    if normalized_source_currency is None or normalized_target_currency is None:
        return False
    return normalized_source_currency == normalized_target_currency or _is_positive_finite_decimal(rate)


def _is_positive_finite_decimal(value: object) -> bool:
    decimal_value = _finite_decimal_or_none(value)
    return decimal_value is not None and decimal_value > 0


def split_position_cash_flows_in_value_basis(
    *,
    cash_flows_raw: object,
    row: dict[str, object],
    value_basis: PositionValueBasis,
) -> tuple[Decimal, Decimal, Decimal]:
    bod_cf = Decimal("0")
    eod_cf = Decimal("0")
    mgmt_fees = Decimal("0")
    if not isinstance(cash_flows_raw, list):
        return bod_cf, eod_cf, mgmt_fees

    conversion_factor = _cash_flow_conversion_factor(row=row, value_basis=value_basis)
    for flow in cash_flows_raw:
        projected_flow = _position_cash_flow_projection(flow, conversion_factor=conversion_factor)
        if projected_flow is None:
            continue
        bod_cf, eod_cf, mgmt_fees = _accumulate_position_cash_flow_projection(
            bod_cf=bod_cf,
            eod_cf=eod_cf,
            mgmt_fees=mgmt_fees,
            projected_flow=projected_flow,
        )
    return bod_cf, eod_cf, mgmt_fees


def _accumulate_position_cash_flow_projection(
    *,
    bod_cf: Decimal,
    eod_cf: Decimal,
    mgmt_fees: Decimal,
    projected_flow: tuple[Literal["bod", "eod"], Decimal, CashflowTypeClassification],
) -> tuple[Decimal, Decimal, Decimal]:
    timing, decimal_amount, cashflow_type = projected_flow
    if cashflow_type.economics_role == "fee":
        return bod_cf, eod_cf, mgmt_fees + decimal_amount
    if cashflow_type.economics_role == "unsupported":
        return bod_cf, eod_cf, mgmt_fees
    if timing == "bod":
        return bod_cf + decimal_amount, eod_cf, mgmt_fees
    return bod_cf, eod_cf + decimal_amount, mgmt_fees


def _position_cash_flow_projection(
    flow: object,
    *,
    conversion_factor: Decimal,
) -> tuple[Literal["bod", "eod"], Decimal, CashflowTypeClassification] | None:
    if not isinstance(flow, dict):
        return None
    amount = flow.get("amount")
    timing = flow.get("timing")
    if amount is None or timing not in {"bod", "eod"}:
        return None
    decimal_amount = _finite_decimal_or_none(amount)
    if decimal_amount is None:
        return None
    decimal_amount *= conversion_factor
    if not decimal_amount.is_finite():
        return None
    return timing, decimal_amount, classify_cashflow_type(flow.get("cash_flow_type"))


def _finite_decimal_or_none(value: object) -> Decimal | None:
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return None
    return decimal_value if decimal_value.is_finite() else None


def _cash_flow_conversion_factor(
    *,
    row: dict[str, object],
    value_basis: PositionValueBasis,
) -> Decimal:
    if value_basis == "position":
        return Decimal("1")

    if _has_cash_flow_position_currency_mismatch(row):
        raise APIUnprocessableEntityError(
            (
                "Stateful position-timeseries cash_flow_currency must match position_currency when lotus-performance "
                "normalizes contribution or attribution cash flows from position currency into portfolio/reporting currency."
            ),
        )

    position_to_portfolio_rate = _decimal_or_one(row.get("position_to_portfolio_fx_rate"))
    if value_basis == "portfolio":
        return position_to_portfolio_rate

    portfolio_to_reporting_rate = _decimal_or_one(row.get("portfolio_to_reporting_fx_rate"))
    return position_to_portfolio_rate * portfolio_to_reporting_rate


def _has_cash_flow_position_currency_mismatch(row: dict[str, object]) -> bool:
    cash_flow_currency = normalized_currency_code(row.get("cash_flow_currency"))
    position_currency = normalized_currency_code(row.get("position_currency"))
    return cash_flow_currency is not None and position_currency is not None and cash_flow_currency != position_currency


def _decimal_or_one(value: object) -> Decimal:
    if value is None:
        return Decimal("1")
    return Decimal(str(value))
