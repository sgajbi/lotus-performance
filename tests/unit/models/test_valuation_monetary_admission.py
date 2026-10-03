"""Valuation schedules retain admitted money before analytics and lineage."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.contribution_requests import PositionDailyData
from app.models.requests import DailyInputData
from app.models.workspace_summary_responses import WorkspaceEconomicContext
from core.errors import APIUnprocessableEntityError
from core.monetary_input import validate_calculated_money_model

MONEY_FIELDS = ("begin_mv", "end_mv", "bod_cf", "eod_cf", "mgmt_fees")
VALUATION_MODELS = (DailyInputData, PositionDailyData)


def valuation_payload(field, value):
    return {"perf_date": "2025-01-01", "begin_mv": "100", "end_mv": "100", field: value}


@pytest.mark.parametrize("model", VALUATION_MODELS)
@pytest.mark.parametrize("field", MONEY_FIELDS)
def test_valuation_money_retains_exact_decimal_and_serialized_evidence(model, field):
    amount = "9007199254740993.01"
    point = model.model_validate(valuation_payload(field, amount))
    assert isinstance(getattr(point, field), Decimal)
    assert getattr(point, field) == Decimal(amount)
    assert point.model_dump(mode="json")[field] == amount


@pytest.mark.parametrize("model", VALUATION_MODELS)
@pytest.mark.parametrize("field", MONEY_FIELDS)
@pytest.mark.parametrize("amount", [True, False, "NaN", "Infinity", "-Infinity", None, "0.000000001", float(2**53)])
def test_valuation_money_rejects_nonfinancial_or_unsafe_input(model, field, amount):
    with pytest.raises(ValidationError):
        model.model_validate(valuation_payload(field, amount))


@pytest.mark.parametrize("model", VALUATION_MODELS)
@pytest.mark.parametrize("field", MONEY_FIELDS)
@pytest.mark.parametrize("amount", ["0", "-12.34", 0.1, 1, Decimal("123.4500")])
def test_valuation_money_accepts_zero_signed_and_numeric_compatibility(model, field, amount):
    point = model.model_validate(valuation_payload(field, amount))
    assert isinstance(getattr(point, field), Decimal)
    assert getattr(point, field) == Decimal(str(amount))


@pytest.mark.parametrize("model", VALUATION_MODELS)
def test_default_valuation_flows_and_fees_are_decimal_zero(model):
    point = model.model_validate(valuation_payload("end_mv", "100"))
    for field in ("bod_cf", "eod_cf", "mgmt_fees"):
        assert isinstance(getattr(point, field), Decimal)
        assert getattr(point, field) == Decimal(0)


@pytest.mark.parametrize("model", VALUATION_MODELS)
@pytest.mark.parametrize("field", MONEY_FIELDS)
def test_calculated_source_money_preserves_precision_without_changing_raw_import_policy(model, field):
    payload = valuation_payload(field, "1301897.1085353480000000")
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    with pytest.raises(ValidationError):
        model.model_validate(payload, context="source_calculated_money")
    admitted = validate_calculated_money_model(model, payload)
    assert getattr(admitted, field) == Decimal("1301897.1085353480000000")
    wire = admitted.model_dump(mode="json")
    assert wire[field] == "1301897.1085353480000000"
    assert validate_calculated_money_model(model, wire) == admitted


@pytest.mark.parametrize("model", VALUATION_MODELS)
@pytest.mark.parametrize("amount", [True, False, None, "NaN", "Infinity", float(2**53)])
def test_calculated_source_money_retains_typed_finite_and_unsafe_input_refusals(model, amount):
    with pytest.raises(APIUnprocessableEntityError) as failure:
        validate_calculated_money_model(model, valuation_payload("end_mv", amount))
    assert failure.value.status_code == 422
    assert failure.value.error_code == "CALCULATED_FINANCIAL_INPUT_INVALID"
    assert "end_mv" not in str(failure.value)


@pytest.mark.parametrize("model", VALUATION_MODELS)
def test_end_day_deposit_cancellation_retains_independent_cent_profit(model):
    point = model.model_validate(
        {
            "perf_date": "2025-01-01",
            "begin_mv": "100",
            "end_mv": "9007199254741093.02",
            "eod_cf": "9007199254740993.01",
        }
    )
    assert point.end_mv - point.eod_cf - point.begin_mv == Decimal("0.01")


def test_workspace_economic_evidence_retains_decimal_money_on_the_wire():
    fields = (
        "begin_market_value",
        "end_market_value",
        "beginning_cash_flow",
        "ending_cash_flow",
        "fees",
        "net_cash_flow",
        "flow_adjusted_end_market_value",
    )
    amount = Decimal("9007199254740993.01")
    evidence = WorkspaceEconomicContext.model_validate(dict.fromkeys(fields, amount))
    assert evidence.model_dump(mode="python") == dict.fromkeys(fields, amount)
    assert evidence.model_dump(mode="json") == dict.fromkeys(fields, str(amount))
