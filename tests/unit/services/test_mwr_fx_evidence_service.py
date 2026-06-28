from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.services.mwr_fx_evidence_service import (
    _build_cashflow_response_evidence,
    _market_value_response_evidence_items,
    _validate_component_required_text_fields,
    _validated_cash_flow_evidence_by_index,
    _validated_source_preconverted_fx_inputs,
    build_source_preconverted_mwr_currency_evidence,
)


def _request_with_evidence(**overrides) -> MoneyWeightedReturnRequest:
    payload = {
        "portfolio_id": "MWR_FX_UNIT",
        "begin_mv": 110000.0,
        "end_mv": 126500.0,
        "as_of": "2025-12-31",
        "start_date": "2025-01-01",
        "currency": "EUR",
        "report_ccy": "USD",
        "cash_flows": [{"amount": 5500.0, "date": "2025-06-30"}],
        "mwr_method": "DIETZ",
        "source_preconverted_fx_evidence": {
            "market_values": [
                _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
            ],
            "cash_flows": [_cash_flow()],
        },
    }
    payload.update(overrides)
    return MoneyWeightedReturnRequest.model_validate(payload)


def _market_value(role: str, source_amount: float, reporting_amount: float, rate_date: str, fingerprint: str) -> dict:
    return {
        "value_role": role,
        "source_amount": source_amount,
        "source_currency": "EUR",
        "reporting_amount": reporting_amount,
        "reporting_currency": "USD",
        "fx_rate": 1.1,
        "fx_pair": "EUR/USD",
        "fx_rate_date": rate_date,
        "fx_rate_source": "ECB_FIXING",
        "fx_rate_version": f"ECB-{rate_date}",
        "conversion_policy": "valuation-date-close",
        "conversion_timestamp": f"{rate_date}T17:00:00Z",
        "conversion_fingerprint": fingerprint,
    }


def _cash_flow(**overrides) -> dict:
    payload = {
        "cash_flow_index": 0,
        "cash_flow_date": "2025-06-30",
        "source_amount": 5000.0,
        "source_currency": "EUR",
        "reporting_amount": 5500.0,
        "reporting_currency": "USD",
        "fx_rate": 1.1,
        "fx_pair": "EUR/USD",
        "fx_rate_date": "2025-06-30",
        "fx_rate_source": "ECB_FIXING",
        "fx_rate_version": "ECB-2025-06-30",
        "conversion_policy": "cash-flow-date-close",
        "conversion_timestamp": "2025-06-30T17:00:00Z",
        "conversion_fingerprint": "fx-cashflow",
    }
    payload.update(overrides)
    return payload


def test_source_preconverted_mwr_currency_evidence_returns_none_without_evidence():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "MWR_NO_FX",
            "begin_mv": 100.0,
            "end_mv": 110.0,
            "as_of": "2025-12-31",
            "cash_flows": [],
        }
    )

    assert build_source_preconverted_mwr_currency_evidence(request) is None


def test_source_preconverted_mwr_currency_evidence_maps_valid_payload():
    evidence = build_source_preconverted_mwr_currency_evidence(_request_with_evidence())

    assert evidence is not None
    assert evidence.currency_mode == "SOURCE_PRECONVERTED_WITH_FX_EVIDENCE"
    assert evidence.market_values_used[0].conversion_status == "source_preconverted_with_fx_evidence"
    assert evidence.cashflow_evidence[0].conversion_fingerprint == "fx-cashflow"


def test_cashflow_response_evidence_helpers_preserve_source_conversion_metadata():
    request = _request_with_evidence()
    source_evidence = request.source_preconverted_fx_evidence
    assert source_evidence is not None

    cash_flows_by_index = _validated_cash_flow_evidence_by_index(
        request_cash_flow_count=len(request.cash_flows),
        evidence_cash_flows=source_evidence.cash_flows,
    )
    cashflow_evidence = _build_cashflow_response_evidence(
        request_cash_flows=request.cash_flows,
        cash_flows_by_index=cash_flows_by_index,
        reporting_currency="USD",
    )

    assert len(cashflow_evidence) == 1
    assert cashflow_evidence[0].currency == "USD"
    assert cashflow_evidence[0].source_amount == 5000
    assert cashflow_evidence[0].source_currency == "EUR"
    assert cashflow_evidence[0].conversion_fingerprint == "fx-cashflow"


def test_validated_source_preconverted_fx_inputs_indexes_domain_evidence():
    request = _request_with_evidence()
    source_evidence = request.source_preconverted_fx_evidence
    assert source_evidence is not None

    validated_inputs = _validated_source_preconverted_fx_inputs(request=request, evidence=source_evidence)

    assert validated_inputs.reporting_currency == "USD"
    assert validated_inputs.beginning_market_value.value_role == "beginning_market_value"
    assert validated_inputs.ending_market_value.value_role == "ending_market_value"
    assert list(validated_inputs.cash_flows_by_index) == [0]
    assert validated_inputs.cash_flows_by_index[0].conversion_fingerprint == "fx-cashflow"


def test_market_value_response_evidence_items_preserve_valuation_dates_and_fx_provenance():
    request = _request_with_evidence()
    source_evidence = request.source_preconverted_fx_evidence
    assert source_evidence is not None
    validated_inputs = _validated_source_preconverted_fx_inputs(request=request, evidence=source_evidence)

    market_values = _market_value_response_evidence_items(request=request, validated_inputs=validated_inputs)

    assert [item.value_role for item in market_values] == ["beginning_market_value", "ending_market_value"]
    assert [item.valuation_date.isoformat() for item in market_values] == ["2025-01-01", "2025-12-31"]
    assert [item.conversion_fingerprint for item in market_values] == ["fx-begin", "fx-end"]
    assert {item.reporting_currency for item in market_values} == {"USD"}


def test_validate_component_required_text_fields_reports_missing_fields():
    request = _request_with_evidence(
        source_preconverted_fx_evidence={
            "market_values": [
                _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
            ],
            "cash_flows": [_cash_flow(fx_pair=" ", conversion_fingerprint="")],
        }
    )
    component = request.source_preconverted_fx_evidence.cash_flows[0]

    with pytest.raises(HTTPException, match="fx_pair, conversion_fingerprint"):
        _validate_component_required_text_fields(component, location="source_preconverted_fx_evidence.cash_flows[0]")


@pytest.mark.parametrize(
    "evidence_override, expected_message",
    [
        (
            {
                "market_values": [
                    _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin")
                ],
                "cash_flows": [_cash_flow()],
            },
            "must contain exactly one beginning_market_value and one ending_market_value",
        ),
        (
            {
                "market_values": [
                    _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                    _market_value("beginning_market_value", 100001.0, 110001.0, "2025-01-01", "fx-begin-2"),
                ],
                "cash_flows": [_cash_flow()],
            },
            "must contain exactly one beginning_market_value and one ending_market_value",
        ),
        (
            {
                "market_values": [
                    _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                    _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
                    _market_value("ending_market_value", 115001.0, 126501.0, "2025-12-31", "fx-end-2"),
                ],
                "cash_flows": [_cash_flow()],
            },
            "must contain exactly two records",
        ),
        (
            {
                "market_values": [
                    _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                    _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
                ],
                "cash_flows": [],
            },
            "must contain exactly one record for each cash flow index",
        ),
    ],
)
def test_source_preconverted_mwr_currency_evidence_rejects_incomplete_collections(
    evidence_override,
    expected_message,
):
    request = _request_with_evidence(source_preconverted_fx_evidence=evidence_override)

    with pytest.raises(HTTPException, match=expected_message):
        build_source_preconverted_mwr_currency_evidence(request)


@pytest.mark.parametrize(
    "cash_flow_override, expected_message",
    [
        ({"cash_flow_date": "2025-07-01"}, "cash_flow_date must match"),
        ({"reporting_currency": "CHF"}, "reporting_currency must match"),
        ({"reporting_amount": 5501.0}, "reporting_amount must match"),
        (
            {"source_currency": "USD", "reporting_currency": "USD", "fx_rate": 1.1},
            "fx_rate must be 1 when source_currency equals reporting_currency",
        ),
        ({"conversion_policy": " "}, "missing required FX evidence fields"),
    ],
)
def test_source_preconverted_mwr_currency_evidence_rejects_inconsistent_components(
    cash_flow_override,
    expected_message,
):
    request = _request_with_evidence(
        source_preconverted_fx_evidence={
            "market_values": [
                _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
            ],
            "cash_flows": [_cash_flow(**cash_flow_override)],
        }
    )

    with pytest.raises(HTTPException, match=expected_message):
        build_source_preconverted_mwr_currency_evidence(request)
