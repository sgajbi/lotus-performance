from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status


def portfolio_timeseries_to_valuation_points(*, observations: list[dict[str, object]]) -> list[dict[str, object]]:
    valuation_points: list[dict[str, object]] = []
    for point in observations:
        valuation_date = point.get("valuation_date")
        begin_mv = point.get("beginning_market_value")
        end_mv = point.get("ending_market_value")
        cash_flows_raw = point.get("cash_flows", [])
        if not isinstance(valuation_date, str) or begin_mv is None or end_mv is None:
            continue
        bod_cf = Decimal("0")
        eod_cf = Decimal("0")
        if isinstance(cash_flows_raw, list):
            for flow in cash_flows_raw:
                if not isinstance(flow, dict):
                    continue
                amount = flow.get("amount")
                timing = flow.get("timing")
                if amount is None or timing not in {"bod", "eod"}:
                    continue
                decimal_amount = Decimal(str(amount))
                if timing == "bod":
                    bod_cf += decimal_amount
                else:
                    eod_cf += decimal_amount
        valuation_points.append(
            {
                "perf_date": valuation_date,
                "begin_mv": Decimal(str(begin_mv)),
                "end_mv": Decimal(str(end_mv)),
                "bod_cf": bod_cf,
                "eod_cf": eod_cf,
            }
        )
    if not valuation_points:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INSUFFICIENT_DATA",
                "message": "No valid valuation observations after canonical normalization.",
            },
        )
    return valuation_points
