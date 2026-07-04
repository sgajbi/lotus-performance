from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.services.currency_code_normalization import normalized_currency_code
from app.services.source_cashflow_taxonomy import CashflowTypeClassification, classify_cashflow_type
from core.errors import APIUnprocessableEntityError

PositionValueBasis = Literal["position", "portfolio", "reporting"]


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
    decimal_amount = Decimal(str(amount)) * conversion_factor
    return timing, decimal_amount, classify_cashflow_type(flow.get("cash_flow_type"))


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
