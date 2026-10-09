"""Pooled contracts preserve dated source money and reject fabricated precision."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.composite_pooled_mwr import (
    CompositePooledMWRRequest,
    PooledCashFlow,
    PooledValuation,
)
from tests.unit.services.test_composite_pooled_mwr_admission import _flow


def request_payload():
    return {
        "composite_id": "CONTROLLED_POOL",
        "period_start": "2025-01-01",
        "period_end": "2026-01-01",
        "reporting_currency": "USD",
        "return_view": "GROSS",
        "source_manifest_id": "controlled-original-v1",
        "policy_binding_id": "controlled-xirr-policy-v1",
    }


def test_pooled_request_requires_explicit_pinned_sources_and_preserves_solver_work_guard():
    request = CompositePooledMWRRequest.model_validate(request_payload())
    assert request.metric_id == "POOLED_MONEY_WEIGHTED_RETURN"
    assert request.method == "XIRR:v1"
    assert request.annualization.basis == "ACT/365"
    assert request.fallback_policy == "REQUIRE_XIRR"
    for field in ("source_manifest_id", "policy_binding_id"):
        payload = request_payload()
        del payload[field]
        with pytest.raises(ValidationError):
            CompositePooledMWRRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        CompositePooledMWRRequest.model_validate(
            {**request_payload(), "solver": {"rate_lower_bound": 1, "rate_upper_bound": 0}}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"period_end": "2024-12-31"},
        {"reporting_currency": "usd"},
        {"source_manifest_id": ""},
        {"method": "TWR"},
        {"bank_approved": True},
    ],
)
def test_pooled_request_refuses_invalid_window_currency_and_client_approval(change):
    with pytest.raises(ValidationError):
        CompositePooledMWRRequest.model_validate({**request_payload(), **change})


def valuation_payload():
    return {
        "portfolio_id": "member-a",
        "economic_date": "2025-01-01",
        "role": "OPENING",
        "amount": "100000000000000000000.1234567890123456789",
        "currency": "USD",
        "source_pin_id": "valuation-pin-v1",
        "source_row_id": "opening-a",
        "timing": "BOD",
    }


def test_pooled_valuation_retains_source_decimal_without_import_quantization():
    payload = valuation_payload()
    valuation = PooledValuation.model_validate(payload)
    assert valuation.amount == Decimal(payload["amount"])
    assert valuation.economic_date == date(2025, 1, 1)
    assert PooledValuation.model_validate_json(valuation.model_dump_json()) == valuation


@pytest.mark.parametrize("amount", [True, 0.1, "NaN", "Infinity", "invalid", None])
def test_pooled_source_money_rejects_boolean_float_and_nonfinite_evidence(amount):
    with pytest.raises(ValidationError):
        PooledValuation.model_validate({**valuation_payload(), "amount": amount})


def test_dated_flow_requires_identity_classification_and_original_date():
    payload = {
        "portfolio_id": "member-a",
        "economic_date": "2025-07-01",
        "source_date": "2025-07-01",
        "amount": "100.000000000000000001",
        "currency": "USD",
        "timing": "BOD",
        "classification": "EXTERNAL",
        "flow_scope": "PORTFOLIO",
        "source_pin_id": "flows-v1",
        "identity_namespace": "source-portfolio",
        "identity_scope": "PORTFOLIO",
        "event_id": "flow-a",
        "revision": "v1",
        "lifecycle_status": "ACTIVE",
    }
    flow = PooledCashFlow.model_validate(payload)
    assert flow.amount == Decimal(payload["amount"])
    for field in ("event_id", "identity_namespace", "identity_scope", "flow_scope", "classification", "source_date"):
        incomplete = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            PooledCashFlow.model_validate(incomplete)


@pytest.mark.parametrize("divisor", [366, float("inf"), float("nan")])
def test_named_day_basis_cannot_be_silently_overridden_without_policy(divisor):
    with pytest.raises(ValidationError, match="custom divisors"):
        CompositePooledMWRRequest.model_validate(
            {**request_payload(), "annualization": {"basis": "ACT/365", "periods_per_year": divisor}}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"predecessor_event_id": "previous-event"},
        {"predecessor_revision": "previous-revision"},
        {"predecessor_event_id": "flow-a", "predecessor_revision": "v1"},
    ],
)
def test_flow_predecessor_cannot_be_partial_or_self_referential(change):
    with pytest.raises(ValidationError, match="predecessor"):
        PooledCashFlow.model_validate(_flow(**change))


def test_correction_requires_distinct_calculation_identity():
    calculation_id = "74e8d4d9-7ee8-4cb8-aa31-4d92b186b840"
    with pytest.raises(ValidationError, match="new calculation identity"):
        CompositePooledMWRRequest.model_validate(
            {**request_payload(), "calculation_id": calculation_id, "correction_of_calculation_id": calculation_id}
        )
