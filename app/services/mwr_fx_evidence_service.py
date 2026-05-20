from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status

from app.models.mwr_requests import (
    MoneyWeightedReturnRequest,
    MWRMarketValueFXEvidence,
    MWRSourcePreconvertedFXComponent,
)
from app.services.stateful_mwr_input_service import (
    MWRCashFlowEvidence,
    MWRCurrencyEvidence,
    MWRMarketValueEvidence,
)

FX_EVIDENCE_COMPLETE_REASON_CODES = [
    "SOURCE_PRECONVERTED_INPUTS_SUPPLIED",
    "PER_INPUT_FX_METADATA_VALIDATED",
    "MWR_ENGINE_CALCULATED_REPORTING_CURRENCY_SCHEDULE",
]


def build_source_preconverted_mwr_currency_evidence(
    request: MoneyWeightedReturnRequest,
) -> MWRCurrencyEvidence | None:
    """Validate stateless source-preconverted FX evidence and return response evidence."""

    evidence = request.source_preconverted_fx_evidence
    if evidence is None:
        return None

    reporting_currency = request.report_ccy or request.currency
    market_values_by_role = {item.value_role: item for item in evidence.market_values}
    if set(market_values_by_role) != {"beginning_market_value", "ending_market_value"}:
        _raise_fx_evidence_error(
            "source_preconverted_fx_evidence.market_values must contain exactly one beginning_market_value "
            "and one ending_market_value record"
        )
    if len(evidence.market_values) != 2:
        _raise_fx_evidence_error("source_preconverted_fx_evidence.market_values must contain exactly two records")

    cash_flows_by_index = {item.cash_flow_index: item for item in evidence.cash_flows}
    expected_indexes = set(range(len(request.cash_flows)))
    if set(cash_flows_by_index) != expected_indexes or len(evidence.cash_flows) != len(request.cash_flows):
        _raise_fx_evidence_error(
            "source_preconverted_fx_evidence.cash_flows must contain exactly one record for each cash flow index"
        )

    beginning_evidence = market_values_by_role["beginning_market_value"]
    ending_evidence = market_values_by_role["ending_market_value"]
    _validate_component(
        beginning_evidence,
        reporting_amount=_decimal(request.begin_mv),
        reporting_currency=reporting_currency,
        location="source_preconverted_fx_evidence.market_values[beginning_market_value]",
    )
    _validate_component(
        ending_evidence,
        reporting_amount=_decimal(request.end_mv),
        reporting_currency=reporting_currency,
        location="source_preconverted_fx_evidence.market_values[ending_market_value]",
    )

    cashflow_evidence: list[MWRCashFlowEvidence] = []
    for index, cash_flow in enumerate(request.cash_flows):
        item = cash_flows_by_index[index]
        if item.cash_flow_date != cash_flow.date:
            _raise_fx_evidence_error(
                f"source_preconverted_fx_evidence.cash_flows[{index}].cash_flow_date must match cash_flows[{index}].date"
            )
        _validate_component(
            item,
            reporting_amount=_decimal(cash_flow.amount),
            reporting_currency=reporting_currency,
            location=f"source_preconverted_fx_evidence.cash_flows[{index}]",
        )
        cashflow_evidence.append(
            MWRCashFlowEvidence(
                date=cash_flow.date,
                amount=_decimal(cash_flow.amount),
                currency=reporting_currency,
                source_components=[],
                source_amount=_decimal(item.source_amount),
                source_currency=item.source_currency,
                reporting_amount=_decimal(item.reporting_amount),
                reporting_currency=item.reporting_currency,
                fx_rate=_decimal(item.fx_rate),
                fx_pair=item.fx_pair,
                fx_rate_date=item.fx_rate_date,
                fx_rate_source=item.fx_rate_source,
                fx_rate_version=item.fx_rate_version,
                conversion_policy=item.conversion_policy,
                conversion_timestamp=item.conversion_timestamp,
                conversion_fingerprint=item.conversion_fingerprint,
            )
        )

    return MWRCurrencyEvidence(
        reporting_currency=reporting_currency,
        portfolio_currency=request.currency,
        currency_mode="SOURCE_PRECONVERTED_WITH_FX_EVIDENCE",
        conversion_evidence_status="complete_source_preconverted_fx_metadata",
        conversion_evidence_reason_codes=FX_EVIDENCE_COMPLETE_REASON_CODES,
        market_values_used=[
            _market_value_response_evidence(
                beginning_evidence,
                reporting_amount=_decimal(request.begin_mv),
                reporting_currency=reporting_currency,
                value_role="beginning_market_value",
                valuation_date=request.start_date or request.as_of,
            ),
            _market_value_response_evidence(
                ending_evidence,
                reporting_amount=_decimal(request.end_mv),
                reporting_currency=reporting_currency,
                value_role="ending_market_value",
                valuation_date=request.as_of,
            ),
        ],
        cashflow_evidence=cashflow_evidence,
    )


def _market_value_response_evidence(
    item: MWRMarketValueFXEvidence,
    *,
    reporting_amount: Decimal,
    reporting_currency: str,
    value_role: Literal["beginning_market_value", "ending_market_value"],
    valuation_date,
) -> MWRMarketValueEvidence:
    return MWRMarketValueEvidence(
        valuation_date=valuation_date,
        amount=reporting_amount,
        currency=reporting_currency,
        value_role=value_role,
        conversion_status="source_preconverted_with_fx_evidence",
        source_amount=_decimal(item.source_amount),
        source_currency=item.source_currency,
        reporting_amount=_decimal(item.reporting_amount),
        reporting_currency=item.reporting_currency,
        fx_rate=_decimal(item.fx_rate),
        fx_pair=item.fx_pair,
        fx_rate_date=item.fx_rate_date,
        fx_rate_source=item.fx_rate_source,
        fx_rate_version=item.fx_rate_version,
        conversion_policy=item.conversion_policy,
        conversion_timestamp=item.conversion_timestamp,
        conversion_fingerprint=item.conversion_fingerprint,
    )


def _validate_component(
    item: MWRSourcePreconvertedFXComponent,
    *,
    reporting_amount: Decimal,
    reporting_currency: str,
    location: str,
) -> None:
    if item.reporting_currency != reporting_currency:
        _raise_fx_evidence_error(f"{location}.reporting_currency must match the MWR reporting currency")
    if _decimal(item.reporting_amount) != reporting_amount:
        _raise_fx_evidence_error(f"{location}.reporting_amount must match the MWR input amount")
    if item.source_currency == item.reporting_currency and _decimal(item.fx_rate) != Decimal("1"):
        _raise_fx_evidence_error(f"{location}.fx_rate must be 1 when source_currency equals reporting_currency")
    required_text_fields = {
        "source_currency": item.source_currency,
        "reporting_currency": item.reporting_currency,
        "fx_pair": item.fx_pair,
        "fx_rate_source": item.fx_rate_source,
        "fx_rate_version": item.fx_rate_version,
        "conversion_policy": item.conversion_policy,
        "conversion_fingerprint": item.conversion_fingerprint,
    }
    missing_fields = [field for field, value in required_text_fields.items() if not value.strip()]
    if missing_fields:
        _raise_fx_evidence_error(f"{location} is missing required FX evidence fields: {', '.join(missing_fields)}")


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _raise_fx_evidence_error(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Invalid source_preconverted_fx_evidence: {message}",
    )
