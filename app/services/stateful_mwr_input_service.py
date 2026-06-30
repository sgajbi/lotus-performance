from __future__ import annotations

from dataclasses import dataclass, field
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
    source_transaction_id: str | None = None
    source_event_id: str | None = None
    lifecycle_status: str | None = None
    correction_reference_id: str | None = None
    reversal_reference_id: str | None = None
    cancellation_reference_id: str | None = None
    trade_date: Date | None = None
    settlement_date: Date | None = None
    effective_date: Date | None = None
    posting_date: Date | None = None
    lifecycle_identity_status: Literal["available", "not_supplied_by_source"] = "not_supplied_by_source"


@dataclass(frozen=True)
class MWRSourceCashFlowQuality:
    source_product: Literal["PortfolioTimeseriesInput"] = "PortfolioTimeseriesInput"
    observed_source_row_count: int = 0
    included_source_row_count: int = 0
    excluded_source_row_count: int = 0
    observed_economics_role_counts: dict[str, int] = field(default_factory=dict)
    exclusion_counts: dict[str, int] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)


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
    source_cashflow_quality: MWRSourceCashFlowQuality | None = None


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
    source_cashflow_quality: MWRSourceCashFlowQuality = field(default_factory=MWRSourceCashFlowQuality)


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
            source_cashflow_quality=cash_flow_collection.source_cashflow_quality,
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
    source_quality = _StatefulMWRSourceCashFlowQualityAccumulator()
    previous_ending_market_value: Decimal | None = None
    for observation in observations:
        valuation_date_raw = observation.get("valuation_date")
        if not isinstance(valuation_date_raw, str):
            _record_invalid_observation_cash_flows(source_quality=source_quality, observation=observation)
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
            source_quality.exclude("invalid_cash_flow_collection")
            previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))
            continue
        _collect_stateful_mwr_source_flow_components(
            cash_flows_by_date=cash_flows_by_date,
            cash_flow_components_by_date=cash_flow_components_by_date,
            valuation_date=valuation_date,
            flows=flows_raw,
            reporting_currency=reporting_currency,
            source_quality=source_quality,
        )
        previous_ending_market_value = _parse_decimal(observation.get("ending_market_value"))

    return _StatefulMWRCashFlowCollection(
        cash_flows_by_date=cash_flows_by_date,
        cash_flow_components_by_date=cash_flow_components_by_date,
        source_cashflow_quality=source_quality.to_evidence(),
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
    source_quality: "_StatefulMWRSourceCashFlowQualityAccumulator",
) -> None:
    for flow in flows:
        component = _source_mwr_cash_flow_component(
            flow,
            reporting_currency=reporting_currency,
            source_quality=source_quality,
        )
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
    source_quality: "_StatefulMWRSourceCashFlowQualityAccumulator | None" = None,
) -> MWRCashFlowEvidenceComponent | None:
    source_quality = source_quality or _StatefulMWRSourceCashFlowQualityAccumulator()
    source_quality.observe(flow)
    if not isinstance(flow, dict):
        source_quality.exclude("invalid_source_row_shape")
        return None
    amount = _parse_decimal(flow.get("amount"))
    if flow.get("amount") is None:
        source_quality.exclude("missing_amount")
        return None
    if amount is None:
        source_quality.exclude("invalid_amount")
        return None
    classification = classify_cashflow_type(flow.get("cash_flow_type"))
    source_quality.observe_role(classification.economics_role)
    if classification.economics_role not in {"external", "missing"}:
        source_quality.exclude(_mwr_source_exclusion_reason(classification.economics_role))
        return None
    source_quality.include()
    if not _has_source_lifecycle_identity(flow):
        source_quality.record_missing_lifecycle_identity()
    return MWRCashFlowEvidenceComponent(
        component_type="source_cash_flow",
        amount=amount,
        currency=reporting_currency,
        cash_flow_type=_optional_source_flow_string(flow=flow, field_name="cash_flow_type"),
        flow_scope=_optional_source_flow_string(flow=flow, field_name="flow_scope"),
        source_classification=_optional_source_flow_string(flow=flow, field_name="source_classification"),
        source_transaction_id=_optional_source_flow_string_from_any(
            flow=flow,
            field_names=("source_transaction_id", "transaction_id"),
        ),
        source_event_id=_optional_source_flow_string_from_any(
            flow=flow,
            field_names=("source_event_id", "event_id"),
        ),
        lifecycle_status=_optional_source_flow_string_from_any(
            flow=flow,
            field_names=("lifecycle_status", "status"),
        ),
        correction_reference_id=_optional_source_flow_string_from_any(
            flow=flow,
            field_names=("correction_reference_id", "correction_id"),
        ),
        reversal_reference_id=_optional_source_flow_string_from_any(
            flow=flow,
            field_names=("reversal_reference_id", "reversal_id"),
        ),
        cancellation_reference_id=_optional_source_flow_string_from_any(
            flow=flow,
            field_names=("cancellation_reference_id", "cancellation_id"),
        ),
        trade_date=_optional_source_flow_date(flow=flow, field_name="trade_date"),
        settlement_date=_optional_source_flow_date(flow=flow, field_name="settlement_date"),
        effective_date=_optional_source_flow_date(flow=flow, field_name="effective_date"),
        posting_date=_optional_source_flow_date(flow=flow, field_name="posting_date"),
        lifecycle_identity_status="available" if _has_source_lifecycle_identity(flow) else "not_supplied_by_source",
    )


class _StatefulMWRSourceCashFlowQualityAccumulator:
    def __init__(self) -> None:
        self.observed_source_row_count = 0
        self.included_source_row_count = 0
        self.exclusion_counts: dict[str, int] = {}
        self.observed_economics_role_counts: dict[str, int] = {}
        self.missing_lifecycle_identity_count = 0

    def observe(self, flow: object) -> None:
        self.observed_source_row_count += 1

    def observe_role(self, role: str) -> None:
        self.observed_economics_role_counts[role] = self.observed_economics_role_counts.get(role, 0) + 1

    def include(self) -> None:
        self.included_source_row_count += 1

    def record_missing_lifecycle_identity(self) -> None:
        self.missing_lifecycle_identity_count += 1

    def exclude(self, reason: str) -> None:
        self.exclusion_counts[reason] = self.exclusion_counts.get(reason, 0) + 1

    def to_evidence(self) -> MWRSourceCashFlowQuality:
        excluded_source_row_count = sum(self.exclusion_counts.values())
        return MWRSourceCashFlowQuality(
            observed_source_row_count=self.observed_source_row_count,
            included_source_row_count=self.included_source_row_count,
            excluded_source_row_count=excluded_source_row_count,
            observed_economics_role_counts=dict(sorted(self.observed_economics_role_counts.items())),
            exclusion_counts=dict(sorted(self.exclusion_counts.items())),
            reason_codes=_source_cashflow_quality_reason_codes(
                excluded_source_row_count=excluded_source_row_count,
                missing_lifecycle_identity_count=self.missing_lifecycle_identity_count,
            ),
        )


def _record_invalid_observation_cash_flows(
    *,
    source_quality: _StatefulMWRSourceCashFlowQualityAccumulator,
    observation: dict[str, object],
) -> None:
    flows_raw = observation.get("cash_flows", [])
    if not isinstance(flows_raw, list):
        return
    for flow in flows_raw:
        source_quality.observe(flow)
        source_quality.exclude("invalid_observation_date")


def _mwr_source_exclusion_reason(role: str) -> str:
    return {
        "fee": "fee_or_operational",
        "internal": "internal_flow",
        "unsupported": "unsupported_or_income_like",
    }.get(role, "unsupported_or_income_like")


def _source_cashflow_quality_reason_codes(
    *,
    excluded_source_row_count: int,
    missing_lifecycle_identity_count: int,
) -> list[str]:
    reason_codes = ["SOURCE_CASHFLOW_NORMALIZATION_RECORDED"]
    if excluded_source_row_count:
        reason_codes.append("SOURCE_CASHFLOW_ROWS_EXCLUDED")
    if missing_lifecycle_identity_count:
        reason_codes.append("SOURCE_LIFECYCLE_IDENTITY_NOT_SUPPLIED_BY_UPSTREAM")
    return reason_codes


def _has_source_lifecycle_identity(flow: dict[object, object]) -> bool:
    return any(
        _optional_source_flow_string_from_any(flow=flow, field_names=field_names)
        for field_names in (
            ("source_transaction_id", "transaction_id"),
            ("source_event_id", "event_id"),
            ("correction_reference_id", "correction_id"),
            ("reversal_reference_id", "reversal_id"),
            ("cancellation_reference_id", "cancellation_id"),
        )
    )


def _optional_source_flow_string_from_any(*, flow: dict[object, object], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        value = _optional_source_flow_string(flow=flow, field_name=field_name)
        if value is not None:
            return value
    return None


def _optional_source_flow_date(*, flow: dict[object, object], field_name: str) -> Date | None:
    value = flow.get(field_name)
    if not isinstance(value, str):
        return None
    try:
        return Date.fromisoformat(value)
    except ValueError:
        return None


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
