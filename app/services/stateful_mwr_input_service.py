from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from app.models.mwr_requests import CashFlow
from app.services.source_cashflow_taxonomy import classify_cashflow_type
from app.services.stateful_performance_input_service import StatefulPortfolioInput


@dataclass(frozen=True)
class StatefulMWRInput:
    start_date: date
    begin_mv: Decimal
    end_mv: Decimal
    cash_flows: list[CashFlow]
    observations: list[dict[str, object]]


def build_stateful_mwr_input(*, source_input: StatefulPortfolioInput) -> StatefulMWRInput:
    return build_stateful_mwr_input_for_window(
        source_input=source_input,
        window_start_date=source_input.performance_start_date,
    )


def build_stateful_mwr_input_for_window(
    *,
    source_input: StatefulPortfolioInput,
    window_start_date: date,
) -> StatefulMWRInput:
    first_observation = source_input.observations[0]
    last_observation = source_input.observations[-1]

    begin_mv = Decimal(str(first_observation["beginning_market_value"]))
    end_mv = Decimal(str(last_observation["ending_market_value"]))

    cash_flows_by_date: dict[date, Decimal] = {}
    previous_ending_market_value: Decimal | None = None
    for observation in source_input.observations:
        valuation_date_raw = observation.get("valuation_date")
        if not isinstance(valuation_date_raw, str):
            previous_ending_market_value = None
            continue
        valuation_date = date.fromisoformat(valuation_date_raw)
        beginning_market_value = _parse_decimal(observation.get("beginning_market_value"))
        if beginning_market_value is not None and previous_ending_market_value is not None:
            carry_forward_adjustment = beginning_market_value - previous_ending_market_value
            if carry_forward_adjustment != 0:
                cash_flows_by_date.setdefault(valuation_date, Decimal("0"))
                cash_flows_by_date[valuation_date] += carry_forward_adjustment
        flows_raw = observation.get("cash_flows", [])
        if not isinstance(flows_raw, list):
            previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))
            continue
        for flow in flows_raw:
            if not isinstance(flow, dict) or flow.get("amount") is None:
                continue
            cashflow_type = classify_cashflow_type(flow.get("cash_flow_type"))
            if cashflow_type.economics_role not in {"external", "missing"}:
                continue
            cash_flows_by_date.setdefault(valuation_date, Decimal("0"))
            cash_flows_by_date[valuation_date] += Decimal(str(flow["amount"]))
        previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))

    cash_flows = [
        CashFlow(amount=amount, date=cash_flow_date)
        for cash_flow_date, amount in sorted(cash_flows_by_date.items())
        if amount != 0
    ]

    return StatefulMWRInput(
        start_date=window_start_date,
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        observations=source_input.observations,
    )


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
