from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime as DateTime
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
    date: Date
    amount: Decimal
    currency: str | None
    source_components: list[MWRCashFlowEvidenceComponent]
    source_amount: Decimal | None = None
    source_currency: str | None = None
    reporting_amount: Decimal | None = None
    reporting_currency: str | None = None
    fx_rate: Decimal | None = None
    fx_pair: str | None = None
    fx_rate_date: Date | None = None
    fx_rate_source: str | None = None
    fx_rate_version: str | None = None
    conversion_policy: str | None = None
    conversion_timestamp: DateTime | None = None
    conversion_fingerprint: str | None = None


@dataclass(frozen=True)
class MWRMarketValueEvidence:
    valuation_date: Date | None
    amount: Decimal
    currency: str | None
    value_role: Literal["beginning_market_value", "ending_market_value"]
    source_product: Literal["PortfolioTimeseriesInput"] = "PortfolioTimeseriesInput"
    conversion_status: Literal[
        "upstream_preconverted", "source_preconverted_with_fx_evidence", "no_conversion_required"
    ] = "upstream_preconverted"
    source_amount: Decimal | None = None
    source_currency: str | None = None
    reporting_amount: Decimal | None = None
    reporting_currency: str | None = None
    fx_rate: Decimal | None = None
    fx_pair: str | None = None
    fx_rate_date: Date | None = None
    fx_rate_source: str | None = None
    fx_rate_version: str | None = None
    conversion_policy: str | None = None
    conversion_timestamp: DateTime | None = None
    conversion_fingerprint: str | None = None


@dataclass(frozen=True)
class MWRCurrencyEvidence:
    reporting_currency: str | None
    portfolio_currency: str | None
    currency_mode: Literal["SINGLE_REPORTING_CURRENCY", "SOURCE_PRECONVERTED_WITH_FX_EVIDENCE"]
    conversion_evidence_status: Literal[
        "upstream_preconverted_missing_per_input_fx_metadata",
        "complete_source_preconverted_fx_metadata",
        "not_required_single_currency_inputs",
    ]
    conversion_evidence_reason_codes: list[str]
    market_values_used: list[MWRMarketValueEvidence]
    cashflow_evidence: list[MWRCashFlowEvidence]


@dataclass(frozen=True)
class StatefulMWRInput:
    start_date: Date
    begin_mv: Decimal
    end_mv: Decimal
    cash_flows: list[CashFlow]
    observations: list[dict[str, object]]
    currency_evidence: MWRCurrencyEvidence


@dataclass(frozen=True)
class _StatefulMWRCashFlowCollection:
    cash_flows_by_date: dict[Date, Decimal]
    cash_flow_components_by_date: dict[Date, list[MWRCashFlowEvidenceComponent]]


@dataclass(frozen=True)
class _StatefulMWRCashFlowProjection:
    cash_flows: list[CashFlow]
    cashflow_evidence: list[MWRCashFlowEvidence]


def build_stateful_mwr_input(*, source_input: StatefulPortfolioInput) -> StatefulMWRInput:
    return build_stateful_mwr_input_for_window(
        source_input=source_input,
        window_start_date=source_input.performance_start_date,
    )


def build_stateful_mwr_input_for_window(
    *,
    source_input: StatefulPortfolioInput,
    window_start_date: Date,
) -> StatefulMWRInput:
    first_observation = source_input.observations[0]
    last_observation = source_input.observations[-1]

    begin_mv = Decimal(str(first_observation["beginning_market_value"]))
    end_mv = Decimal(str(last_observation["ending_market_value"]))
    reporting_currency = _resolve_reporting_currency(source_input)
    single_currency_inputs = _has_single_currency_inputs(
        source_input=source_input,
        reporting_currency=reporting_currency,
    )

    cash_flow_collection = _collect_stateful_mwr_cash_flows(
        observations=source_input.observations,
        reporting_currency=reporting_currency,
    )
    cash_flow_projection = _stateful_mwr_cash_flow_projection(
        cash_flow_collection=cash_flow_collection,
        reporting_currency=reporting_currency,
    )

    return StatefulMWRInput(
        start_date=window_start_date,
        begin_mv=begin_mv,
        end_mv=end_mv,
        cash_flows=cash_flow_projection.cash_flows,
        observations=source_input.observations,
        currency_evidence=MWRCurrencyEvidence(
            reporting_currency=reporting_currency,
            portfolio_currency=source_input.portfolio_currency,
            currency_mode="SINGLE_REPORTING_CURRENCY",
            conversion_evidence_status=(
                "not_required_single_currency_inputs"
                if single_currency_inputs
                else "upstream_preconverted_missing_per_input_fx_metadata"
            ),
            conversion_evidence_reason_codes=_stateful_currency_reason_codes(
                single_currency_inputs=single_currency_inputs,
            ),
            market_values_used=_stateful_mwr_market_value_evidence(
                first_observation=first_observation,
                last_observation=last_observation,
                begin_mv=begin_mv,
                end_mv=end_mv,
                reporting_currency=reporting_currency,
                single_currency_inputs=single_currency_inputs,
            ),
            cashflow_evidence=cash_flow_projection.cashflow_evidence,
        ),
    )


def _stateful_mwr_market_value_evidence(
    *,
    first_observation: dict[str, object],
    last_observation: dict[str, object],
    begin_mv: Decimal,
    end_mv: Decimal,
    reporting_currency: str | None,
    single_currency_inputs: bool,
) -> list[MWRMarketValueEvidence]:
    conversion_status: Literal["upstream_preconverted", "no_conversion_required"] = (
        "no_conversion_required" if single_currency_inputs else "upstream_preconverted"
    )
    return [
        MWRMarketValueEvidence(
            valuation_date=_parse_observation_date(first_observation),
            amount=begin_mv,
            currency=reporting_currency,
            value_role="beginning_market_value",
            conversion_status=conversion_status,
        ),
        MWRMarketValueEvidence(
            valuation_date=_parse_observation_date(last_observation),
            amount=end_mv,
            currency=reporting_currency,
            value_role="ending_market_value",
            conversion_status=conversion_status,
        ),
    ]


def _stateful_mwr_cash_flow_projection(
    *,
    cash_flow_collection: _StatefulMWRCashFlowCollection,
    reporting_currency: str | None,
) -> _StatefulMWRCashFlowProjection:
    non_zero_cash_flows = [
        (cash_flow_date, amount)
        for cash_flow_date, amount in sorted(cash_flow_collection.cash_flows_by_date.items())
        if amount != 0
    ]
    return _StatefulMWRCashFlowProjection(
        cash_flows=[CashFlow(amount=amount, date=cash_flow_date) for cash_flow_date, amount in non_zero_cash_flows],
        cashflow_evidence=[
            MWRCashFlowEvidence(
                date=cash_flow_date,
                amount=amount,
                currency=reporting_currency,
                source_components=cash_flow_collection.cash_flow_components_by_date.get(cash_flow_date, []),
            )
            for cash_flow_date, amount in non_zero_cash_flows
        ],
    )


def _collect_stateful_mwr_cash_flows(
    *,
    observations: list[dict[str, object]],
    reporting_currency: str | None,
) -> _StatefulMWRCashFlowCollection:
    cash_flows_by_date: dict[Date, Decimal] = {}
    cash_flow_components_by_date: dict[Date, list[MWRCashFlowEvidenceComponent]] = {}
    previous_ending_market_value: Decimal | None = None
    for observation in observations:
        valuation_date_raw = observation.get("valuation_date")
        if not isinstance(valuation_date_raw, str):
            previous_ending_market_value = None
            continue
        valuation_date = Date.fromisoformat(valuation_date_raw)
        beginning_market_value = _parse_decimal(observation.get("beginning_market_value"))
        carry_forward_component = _carry_forward_mwr_cash_flow_component(
            beginning_market_value=beginning_market_value,
            previous_ending_market_value=previous_ending_market_value,
            reporting_currency=reporting_currency,
        )
        if carry_forward_component is not None:
            _add_stateful_mwr_cash_flow_component(
                cash_flows_by_date=cash_flows_by_date,
                cash_flow_components_by_date=cash_flow_components_by_date,
                valuation_date=valuation_date,
                component=carry_forward_component,
            )
        flows_raw = observation.get("cash_flows", [])
        if not isinstance(flows_raw, list):
            previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))
            continue
        _collect_stateful_mwr_source_flow_components(
            cash_flows_by_date=cash_flows_by_date,
            cash_flow_components_by_date=cash_flow_components_by_date,
            valuation_date=valuation_date,
            flows=flows_raw,
            reporting_currency=reporting_currency,
        )
        previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))

    return _StatefulMWRCashFlowCollection(
        cash_flows_by_date=cash_flows_by_date,
        cash_flow_components_by_date=cash_flow_components_by_date,
    )


def _carry_forward_mwr_cash_flow_component(
    *,
    beginning_market_value: Decimal | None,
    previous_ending_market_value: Decimal | None,
    reporting_currency: str | None,
) -> MWRCashFlowEvidenceComponent | None:
    if beginning_market_value is None or previous_ending_market_value is None:
        return None
    carry_forward_adjustment = beginning_market_value - previous_ending_market_value
    if carry_forward_adjustment == 0:
        return None
    return MWRCashFlowEvidenceComponent(
        component_type="carry_forward_adjustment",
        amount=carry_forward_adjustment,
        currency=reporting_currency,
    )


def _collect_stateful_mwr_source_flow_components(
    *,
    cash_flows_by_date: dict[Date, Decimal],
    cash_flow_components_by_date: dict[Date, list[MWRCashFlowEvidenceComponent]],
    valuation_date: Date,
    flows: list[object],
    reporting_currency: str | None,
) -> None:
    for flow in flows:
        component = _source_mwr_cash_flow_component(flow, reporting_currency=reporting_currency)
        if component is None:
            continue
        _add_stateful_mwr_cash_flow_component(
            cash_flows_by_date=cash_flows_by_date,
            cash_flow_components_by_date=cash_flow_components_by_date,
            valuation_date=valuation_date,
            component=component,
        )


def _add_stateful_mwr_cash_flow_component(
    *,
    cash_flows_by_date: dict[Date, Decimal],
    cash_flow_components_by_date: dict[Date, list[MWRCashFlowEvidenceComponent]],
    valuation_date: Date,
    component: MWRCashFlowEvidenceComponent,
) -> None:
    cash_flows_by_date.setdefault(valuation_date, Decimal("0"))
    cash_flows_by_date[valuation_date] += component.amount
    cash_flow_components_by_date.setdefault(valuation_date, []).append(component)


def _source_mwr_cash_flow_component(
    flow: object,
    *,
    reporting_currency: str | None,
) -> MWRCashFlowEvidenceComponent | None:
    if not isinstance(flow, dict) or flow.get("amount") is None:
        return None
    if classify_cashflow_type(flow.get("cash_flow_type")).economics_role not in {"external", "missing"}:
        return None
    return MWRCashFlowEvidenceComponent(
        component_type="source_cash_flow",
        amount=Decimal(str(flow["amount"])),
        currency=reporting_currency,
        cash_flow_type=_optional_source_flow_string(flow=flow, field_name="cash_flow_type"),
        flow_scope=_optional_source_flow_string(flow=flow, field_name="flow_scope"),
        source_classification=_optional_source_flow_string(flow=flow, field_name="source_classification"),
    )


def _optional_source_flow_string(*, flow: dict[object, object], field_name: str) -> str | None:
    value = flow.get(field_name)
    if value is None:
        return None
    return str(value)


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_observation_date(observation: dict[str, object]) -> Date | None:
    valuation_date_raw = observation.get("valuation_date")
    if not isinstance(valuation_date_raw, str):
        return None
    try:
        return Date.fromisoformat(valuation_date_raw)
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


def _has_single_currency_inputs(*, source_input: StatefulPortfolioInput, reporting_currency: str | None) -> bool:
    if not _portfolio_currency_matches_reporting(source_input=source_input, reporting_currency=reporting_currency):
        return False
    if reporting_currency is None:
        return False
    for observation in source_input.observations:
        if not _observation_cash_flow_currency_matches_reporting(
            observation=observation,
            reporting_currency=reporting_currency,
        ):
            return False
    return True


def _portfolio_currency_matches_reporting(
    *,
    source_input: StatefulPortfolioInput,
    reporting_currency: str | None,
) -> bool:
    if not reporting_currency or not source_input.portfolio_currency:
        return False
    return source_input.portfolio_currency.upper() == reporting_currency.upper()


def _observation_cash_flow_currency_matches_reporting(
    *,
    observation: dict[str, object],
    reporting_currency: str,
) -> bool:
    cash_flow_currency = observation.get("cash_flow_currency")
    if not isinstance(cash_flow_currency, str):
        return True
    return cash_flow_currency.upper() == reporting_currency.upper()


def _stateful_currency_reason_codes(*, single_currency_inputs: bool) -> list[str]:
    if single_currency_inputs:
        return [
            "SOURCE_AND_REPORTING_CURRENCY_MATCH",
            "PER_INPUT_FX_CONVERSION_NOT_REQUIRED",
            "MWR_ENGINE_CALCULATED_REPORTING_CURRENCY_SCHEDULE",
        ]
    return [
        "UPSTREAM_PORTFOLIO_TIMESERIES_PRECONVERTED",
        "PER_INPUT_FX_METADATA_NOT_EXPOSED_BY_SOURCE_CONTRACT",
    ]
