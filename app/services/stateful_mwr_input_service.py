from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.mwr_requests import CashFlow
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
    for observation in source_input.observations:
        valuation_date_raw = observation.get("valuation_date")
        if not isinstance(valuation_date_raw, str):
            continue
        valuation_date = date.fromisoformat(valuation_date_raw)
        flows_raw = observation.get("cash_flows", [])
        if not isinstance(flows_raw, list):
            continue
        for flow in flows_raw:
            if not isinstance(flow, dict) or flow.get("amount") is None:
                continue
            cash_flows_by_date.setdefault(valuation_date, Decimal("0"))
            cash_flows_by_date[valuation_date] += Decimal(str(flow["amount"]))

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
