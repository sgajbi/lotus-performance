"""Fee-drag contract and refusal controls; no approval or financial source claims."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.composite_fee_drag import CompositeFeeDragRequest
from app.services.composite_fee_drag.application import _original_gross_facts, _paired_periods
from core.errors import APIUnprocessableEntityError


def request_wire():
    return {
        "metric_id": "MODEL_FEE_DRAG",
        "composite_id": "synthetic.fee-drag",
        "period_start": "2026-01-05",
        "period_end": "2026-01-06",
        "materialization_ids": ["06090000-0000-4000-8000-000000000001"],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("return_view", "GROSS"),
        ("return_view", "NET_ACTUAL"),
        ("method", "GEOMETRIC"),
        ("materialization_ids", []),
        ("materialization_ids", None),
        ("restatement_sequence", 1),
    ],
)
def test_fee_drag_requires_explicit_model_vector_and_additive_method(field, value):
    assert CompositeFeeDragRequest.model_validate(request_wire()).return_view == "NET_MODEL_FEE"
    with pytest.raises(ValidationError):
        CompositeFeeDragRequest.model_validate({**request_wire(), field: value})


def period(value):
    return SimpleNamespace(
        period_start=date(2026, 1, 5),
        period_end=date(2026, 1, 5),
        member_count=2,
        excluded_member_count=1,
        return_value=Decimal(value),
    )


def test_additive_return_difference_is_not_percentage_or_monetary_charge():
    gross, model = period(".02"), period(".015")
    result = _paired_periods(SimpleNamespace(period_results=[gross]), SimpleNamespace(period_results=[model]))[0]
    assert result.fee_drag == Decimal(".005")
    assert result.model_dump(mode="json")["fee_drag"] == "0.005"
    assert result.member_count == 2 and result.excluded_member_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_count", 3),
        ("excluded_member_count", 0),
        ("period_end", date(2026, 1, 6)),
        ("return_value", None),
    ],
)
def test_fee_drag_refuses_incomparable_or_unavailable_period(field, value):
    gross, model = period(".02"), period(".015")
    setattr(model, field, value)
    with pytest.raises(APIUnprocessableEntityError) as error:
        _paired_periods(SimpleNamespace(period_results=[gross]), SimpleNamespace(period_results=[model]))
    assert error.value.error_code == "COMPOSITE_FEE_DRAG_POPULATION_MISMATCH"


def test_fee_drag_requires_retained_gross_receipt_for_ready_member():
    record = SimpleNamespace(
        outcomes=[
            SimpleNamespace(
                state="READY",
                fact=SimpleNamespace(),
                source_evidence=None,
            )
        ]
    )
    with pytest.raises(APIUnprocessableEntityError) as error:
        _original_gross_facts([record])
    assert error.value.error_code == "COMPOSITE_FEE_DRAG_GROSS_RECEIPT_REQUIRED"


def test_fee_drag_refuses_missing_gross_period_instead_of_partial_horizon():
    with pytest.raises(APIUnprocessableEntityError) as error:
        _paired_periods(SimpleNamespace(period_results=[]), SimpleNamespace(period_results=[period(".01")]))
    assert error.value.error_code == "COMPOSITE_FEE_DRAG_POPULATION_MISMATCH"
