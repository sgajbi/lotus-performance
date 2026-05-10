from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.models.mwr_requests import CashFlow
from app.services.source_cashflow_taxonomy import classify_cashflow_type
from app.services.stateful_performance_input_service import StatefulPortfolioInput


@dataclass(frozen=True)
class MWRCashFlowEvidenceComponent:
    component_type: Literal["source_cash_flow", "carry_forward_adjustment"]
    amount: Decimal
    currency: str | None
    cash_flow_type: str | None = None
    flow_scope: str | None = None
    source_classification: str | None = None


@dataclass(frozen=True)
class MWRCashFlowEvidence:
    date: date
    amount: Decimal
    currency: str | None
    source_components: list[MWRCashFlowEvidenceComponent]


@dataclass(frozen=True)
class MWRMarketValueEvidence:
    valuation_date: date | None
    amount: Decimal
    currency: str | None
    value_role: Literal["beginning_market_value", "ending_market_value"]
    source_product: Literal["PortfolioTimeseriesInput"] = "PortfolioTimeseriesInput"
    conversion_status: Literal["upstream_preconverted"] = "upstream_preconverted"


@dataclass(frozen=True)
class MWRCurrencyEvidence:
    reporting_currency: str | None
    portfolio_currency: str | None
    currency_mode: Literal["SINGLE_REPORTING_CURRENCY"]
    conversion_evidence_status: Literal["upstream_preconverted_missing_per_input_fx_metadata"]
    conversion_evidence_reason_codes: list[str]
    market_values_used: list[MWRMarketValueEvidence]
    cashflow_evidence: list[MWRCashFlowEvidence]


@dataclass(frozen=True)
class StatefulMWRInput:
    start_date: date
    begin_mv: Decimal
    end_mv: Decimal
    cash_flows: list[CashFlow]
    observations: list[dict[str, object]]
    currency_evidence: MWRCurrencyEvidence


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
    reporting_currency = _resolve_reporting_currency(source_input)

    cash_flows_by_date: dict[date, Decimal] = {}
    cash_flow_components_by_date: dict[date, list[MWRCashFlowEvidenceComponent]] = {}
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
                cash_flow_components_by_date.setdefault(valuation_date, []).append(
                    MWRCashFlowEvidenceComponent(
                        component_type="carry_forward_adjustment",
                        amount=carry_forward_adjustment,
                        currency=reporting_currency,
                    )
                )
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
            amount = Decimal(str(flow["amount"]))
            cash_flows_by_date.setdefault(valuation_date, Decimal("0"))
            cash_flows_by_date[valuation_date] += amount
            cash_flow_components_by_date.setdefault(valuation_date, []).append(
                MWRCashFlowEvidenceComponent(
                    component_type="source_cash_flow",
                    amount=amount,
                    currency=reporting_currency,
                    cash_flow_type=str(flow.get("cash_flow_type")) if flow.get("cash_flow_type") is not None else None,
                    flow_scope=str(flow.get("flow_scope")) if flow.get("flow_scope") is not None else None,
                    source_classification=(
                        str(flow.get("source_classification"))
                        if flow.get("source_classification") is not None
                        else None
                    ),
                )
            )
        previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))

    cash_flows = [
        CashFlow(amount=amount, date=cash_flow_date)
        for cash_flow_date, amount in sorted(cash_flows_by_date.items())
        if amount != 0
    ]
    cashflow_evidence = [
        MWRCashFlowEvidence(
            date=cash_flow_date,
            amount=amount,
            currency=reporting_currency,
            source_components=cash_flow_components_by_date.get(cash_flow_date, []),
        )
        for cash_flow_date, amount in sorted(cash_flows_by_date.items())
        if amount != 0
    ]

    return StatefulMWRInput(
        start_date=window_start_date,
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flows,
        observations=source_input.observations,
        currency_evidence=MWRCurrencyEvidence(
            reporting_currency=reporting_currency,
            portfolio_currency=source_input.portfolio_currency,
            currency_mode="SINGLE_REPORTING_CURRENCY",
            conversion_evidence_status="upstream_preconverted_missing_per_input_fx_metadata",
            conversion_evidence_reason_codes=[
                "UPSTREAM_PORTFOLIO_TIMESERIES_PRECONVERTED",
                "PER_INPUT_FX_METADATA_NOT_EXPOSED_BY_SOURCE_CONTRACT",
            ],
            market_values_used=[
                MWRMarketValueEvidence(
                    valuation_date=_parse_observation_date(first_observation),
                    amount=begin_mv,
                    currency=reporting_currency,
                    value_role="beginning_market_value",
                ),
                MWRMarketValueEvidence(
                    valuation_date=_parse_observation_date(last_observation),
                    amount=end_mv,
                    currency=reporting_currency,
                    value_role="ending_market_value",
                ),
            ],
            cashflow_evidence=cashflow_evidence,
        ),
    )


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_observation_date(observation: dict[str, object]) -> date | None:
    valuation_date_raw = observation.get("valuation_date")
    if not isinstance(valuation_date_raw, str):
        return None
    try:
        return date.fromisoformat(valuation_date_raw)
    except ValueError:
        return None


def _resolve_reporting_currency(source_input: StatefulPortfolioInput) -> str | None:
    if source_input.reporting_currency:
        return source_input.reporting_currency
    observation_currencies = {
        str(observation["cash_flow_currency"])
        for observation in source_input.observations
        if isinstance(observation.get("cash_flow_currency"), str)
    }
    if len(observation_currencies) == 1:
        return next(iter(observation_currencies))
    return source_input.portfolio_currency
