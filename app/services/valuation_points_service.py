from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException

from app.services.error_details import insufficient_data_detail
from app.services.source_cashflow_taxonomy import classify_cashflow_type
from core.errors import HTTP_422_UNPROCESSABLE


def portfolio_timeseries_to_valuation_points(*, observations: list[dict[str, object]]) -> list[dict[str, object]]:
    valuation_points: list[dict[str, object]] = []
    for point in observations:
        valuation_date = point.get("valuation_date")
        begin_mv = point.get("beginning_market_value")
        end_mv = point.get("ending_market_value")
        cash_flows_raw = point.get("cash_flows", [])
        if not isinstance(valuation_date, str) or begin_mv is None or end_mv is None:
            continue
        bod_cf, eod_cf, mgmt_fees = _valuation_cashflow_totals(cash_flows_raw)
        valuation_points.append(
            {
                "perf_date": valuation_date,
                "begin_mv": Decimal(str(begin_mv)),
                "end_mv": Decimal(str(end_mv)),
                "bod_cf": bod_cf,
                "eod_cf": eod_cf,
                "mgmt_fees": mgmt_fees,
            }
        )
    if not valuation_points:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=insufficient_data_detail("No valid valuation observations after canonical normalization."),
        )
    return valuation_points


def _valuation_cashflow_totals(cash_flows: object) -> tuple[Decimal, Decimal, Decimal]:
    bod_cf = Decimal("0")
    eod_cf = Decimal("0")
    mgmt_fees = Decimal("0")
    if not isinstance(cash_flows, list):
        return bod_cf, eod_cf, mgmt_fees
    for flow in cash_flows:
        if not isinstance(flow, dict):
            continue
        amount = flow.get("amount")
        timing = flow.get("timing")
        if amount is None or timing not in {"bod", "eod"}:
            continue
        decimal_amount = Decimal(str(amount))
        economics_role = classify_cashflow_type(flow.get("cash_flow_type")).economics_role
        if economics_role == "fee":
            mgmt_fees += decimal_amount
        elif economics_role != "unsupported" and timing == "bod":
            bod_cf += decimal_amount
        elif economics_role != "unsupported":
            eod_cf += decimal_amount
    return bod_cf, eod_cf, mgmt_fees
