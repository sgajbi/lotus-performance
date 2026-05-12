from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import HTTPException

from app.services.source_cashflow_taxonomy import classify_cashflow_type
from core.errors import HTTP_422_UNPROCESSABLE

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
        if not isinstance(flow, dict):
            continue
        amount = flow.get("amount")
        timing = flow.get("timing")
        cash_flow_type = flow.get("cash_flow_type")
        if amount is None or timing not in {"bod", "eod"}:
            continue
        decimal_amount = Decimal(str(amount)) * conversion_factor
        cashflow_type = classify_cashflow_type(cash_flow_type)
        if cashflow_type.economics_role == "fee":
            mgmt_fees += decimal_amount
            continue
        if cashflow_type.economics_role == "unsupported":
            continue
        if timing == "bod":
            bod_cf += decimal_amount
        else:
            eod_cf += decimal_amount
    return bod_cf, eod_cf, mgmt_fees


def _cash_flow_conversion_factor(
    *,
    row: dict[str, object],
    value_basis: PositionValueBasis,
) -> Decimal:
    if value_basis == "position":
        return Decimal("1")

    cash_flow_currency = row.get("cash_flow_currency")
    position_currency = row.get("position_currency")
    if (
        isinstance(cash_flow_currency, str)
        and cash_flow_currency
        and isinstance(position_currency, str)
        and position_currency
        and cash_flow_currency != position_currency
    ):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=(
                "Stateful position-timeseries cash_flow_currency must match position_currency when lotus-performance "
                "normalizes contribution or attribution cash flows from position currency into portfolio/reporting currency."
            ),
        )

    position_to_portfolio_rate = _decimal_or_one(row.get("position_to_portfolio_fx_rate"))
    if value_basis == "portfolio":
        return position_to_portfolio_rate

    portfolio_to_reporting_rate = _decimal_or_one(row.get("portfolio_to_reporting_fx_rate"))
    return position_to_portfolio_rate * portfolio_to_reporting_rate


def _decimal_or_one(value: object) -> Decimal:
    if value is None:
        return Decimal("1")
    return Decimal(str(value))
