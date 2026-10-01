from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.services.mwr_fx_evidence_service import (
    _build_cashflow_response_evidence,
    _market_value_response_evidence_items,
    _validate_component_required_text_fields,
    _validated_cash_flow_evidence_by_index,
    _validated_source_preconverted_fx_inputs,
    build_source_preconverted_mwr_currency_evidence,
)
from core.errors import APIError


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

    for fx_rate in ("1.1", "1.099999901", "1.0999999"):
        beginning = _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin")
        beginning["fx_rate"] = fx_rate
        rounded_evidence = build_source_preconverted_mwr_currency_evidence(
            _request_with_evidence(
                source_preconverted_fx_evidence={
                    "market_values": [
                        beginning,
                        _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
                    ],
                    "cash_flows": [_cash_flow()],
                }
            )
        )
        assert rounded_evidence is not None
        assert rounded_evidence.conversion_evidence_status == "complete_source_preconverted_fx_metadata"

    for reporting_amount, component in (
        (-5500.0, _cash_flow(source_amount=-5000.0, reporting_amount=-5500.0)),
        (0.0, _cash_flow(source_amount=0.0, reporting_amount=0.0)),
        (
            5500.0,
            _cash_flow(
                source_amount=5500.0,
                source_currency="USD",
                reporting_amount=5500.0,
                reporting_currency="USD",
                fx_rate=1,
                fx_pair="USD/USD",
            ),
        ),
    ):
        signed_evidence = build_source_preconverted_mwr_currency_evidence(
            _request_with_evidence(
                cash_flows=[{"amount": reporting_amount, "date": "2025-06-30"}],
                source_preconverted_fx_evidence={
                    "market_values": [
                        _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin"),
                        _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end"),
                    ],
                    "cash_flows": [component],
                },
            )
        )
        assert signed_evidence is not None
        assert signed_evidence.cashflow_evidence[0].reporting_amount == reporting_amount

    for invalid_path, invalid_value in (
        (("currency",), "eur"),
        (("currency",), " EUR "),
        (("report_ccy",), "usd"),
        (("report_ccy",), " USD "),
        (("source_preconverted_fx_evidence", "market_values", 0, "source_currency"), "eur"),
        (("source_preconverted_fx_evidence", "market_values", 0, "source_currency"), " EUR "),
        (("source_preconverted_fx_evidence", "market_values", 0, "reporting_currency"), "usd"),
        (("source_preconverted_fx_evidence", "market_values", 0, "reporting_currency"), " USD "),
        (("source_preconverted_fx_evidence", "market_values", 0, "fx_pair"), "eur/USD"),
        (("source_preconverted_fx_evidence", "market_values", 0, "fx_pair"), " EUR/USD "),
    ):
        invalid_payload = _request_with_evidence().model_dump(mode="python")
        target = invalid_payload
        for path_part in invalid_path[:-1]:
            target = target[path_part]
        target[invalid_path[-1]] = invalid_value
        with pytest.raises(ValidationError):
            MoneyWeightedReturnRequest.model_validate(invalid_payload)

    legacy_lowercase_request = _request_with_evidence(
        currency="eur",
        report_ccy="usd",
        source_preconverted_fx_evidence=None,
    )
    assert build_source_preconverted_mwr_currency_evidence(legacy_lowercase_request) is None


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
    request = _request_with_evidence()
    component = request.source_preconverted_fx_evidence.cash_flows[0].model_copy(
        update={"fx_pair": " ", "conversion_fingerprint": ""}
    )

    with pytest.raises(APIError, match="fx_pair, conversion_fingerprint") as exc:
        _validate_component_required_text_fields(component, location="source_preconverted_fx_evidence.cash_flows[0]")
    assert exc.value.status_code == 422


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

    with pytest.raises(APIError, match=expected_message) as exc:
        build_source_preconverted_mwr_currency_evidence(request)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    "component_target, component_override, expected_message",
    [
        ("cash_flow", {"cash_flow_date": "2025-07-01"}, "cash_flow_date must match"),
        ("cash_flow", {"reporting_currency": "CHF"}, "reporting_currency must match"),
        ("cash_flow", {"reporting_amount": 5501.0}, "reporting_amount must match"),
        (
            "cash_flow",
            {"source_currency": "USD", "reporting_currency": "USD", "fx_rate": 1.1, "fx_pair": "USD/USD"},
            "fx_rate must be 1 when source_currency equals reporting_currency",
        ),
        ("cash_flow", {"conversion_policy": " "}, "missing required FX evidence fields"),
        ("beginning", {"source_amount": 1}, "source_amount multiplied by fx_rate must match reporting_amount"),
        ("beginning", {"fx_pair": "GBP/JPY"}, "fx_pair must equal EUR/USD"),
        (
            "beginning",
            {"source_amount": 100000, "source_currency": "USD", "fx_rate": 1, "fx_pair": "USD/USD"},
            "source_amount must equal reporting_amount when source_currency equals reporting_currency",
        ),
        ("ending", {"source_amount": 1}, "source_amount multiplied by fx_rate must match reporting_amount"),
        ("beginning", {"fx_rate": "1.099999899"}, "within 0.01 reporting-currency units"),
        ("cash_flow", {"source_amount": 1, "reporting_amount": 0}, "must both be zero"),
        (
            "negative_cash_flow",
            {"source_amount": 5000, "reporting_amount": -5500},
            "source_amount and reporting_amount must have the same sign",
        ),
        (
            "small_sign_cash_flow",
            {"source_amount": "0.001", "reporting_amount": "-0.001", "fx_rate": "1"},
            "source_amount and reporting_amount must have the same sign",
        ),
        ("second_cash_flow", {"source_amount": -1}, r"cash_flows\[1\].source_amount multiplied by fx_rate"),
    ],
)
def test_source_preconverted_mwr_currency_evidence_rejects_inconsistent_components(
    component_target,
    component_override,
    expected_message,
):
    beginning = _market_value("beginning_market_value", 100000.0, 110000.0, "2025-01-01", "fx-begin")
    ending = _market_value("ending_market_value", 115000.0, 126500.0, "2025-12-31", "fx-end")
    cash_flows = [_cash_flow()]
    request_cash_flows = [{"amount": 5500.0, "date": "2025-06-30"}]
    if component_target == "beginning":
        beginning.update(component_override)
    elif component_target == "ending":
        ending.update(component_override)
    elif component_target == "second_cash_flow":
        request_cash_flows.append({"amount": -2200.0, "date": "2025-07-31"})
        second_cash_flow = _cash_flow(
            cash_flow_index=1,
            cash_flow_date="2025-07-31",
            source_amount=-2000,
            reporting_amount=-2200,
            fx_rate_date="2025-07-31",
            conversion_timestamp="2025-07-31T17:00:00Z",
            conversion_fingerprint="fx-cashflow-2",
        )
        second_cash_flow.update(component_override)
        cash_flows.append(second_cash_flow)
    elif component_target == "negative_cash_flow":
        request_cash_flows[0]["amount"] = -5500.0
        cash_flows[0].update(component_override)
    elif component_target == "small_sign_cash_flow":
        request_cash_flows[0]["amount"] = -0.001
        cash_flows[0].update(component_override)
    else:
        if component_override.get("reporting_amount") == 0:
            request_cash_flows[0]["amount"] = 0
        cash_flows[0].update(component_override)
    request = _request_with_evidence(
        cash_flows=request_cash_flows,
        source_preconverted_fx_evidence={
            "market_values": [beginning, ending],
            "cash_flows": cash_flows,
        },
    )

    with pytest.raises(APIError, match=expected_message) as exc:
        build_source_preconverted_mwr_currency_evidence(request)
    assert exc.value.status_code == 422
