"""Admit only explicit, complete periodic rates; no inferred annual conversion."""

import copy

import pytest
from pydantic import ValidationError

from app.models.composite_materialization import CompositeMaterializationCommand
from app.models.composite_model_fees import CompositePeriodicMemberFee, CompositePeriodicModelFeeProfile
from tests.composite_model_fee_helpers import model_fee_source_inputs, profile_wire


def test_profile_canonical_utf8_byte_bound_accepts_boundary_and_refuses_excess(monkeypatch):
    from app.models import composite_model_fees

    wire = profile_wire()
    canonical = composite_model_fees.model_fee_profile_json(wire)
    size = len(canonical.encode("utf-8"))
    monkeypatch.setattr(composite_model_fees, "MODEL_FEE_PROFILE_MAX_BYTES", size)
    assert CompositePeriodicModelFeeProfile.model_validate(wire).model_dump(mode="json") == wire
    monkeypatch.setattr(composite_model_fees, "MODEL_FEE_PROFILE_MAX_BYTES", size - 1)
    with pytest.raises(ValidationError, match="two-MiB"):
        CompositePeriodicModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("rate", ["0", "0.001", "0.9999999999999999999999999999"])
def test_explicit_finite_rate_and_waiver_roundtrip(rate):
    wire = {"entry_id": "fee.member-a", "member_id": "MEMBER_A", "period_fee_fraction": rate}
    assert CompositePeriodicMemberFee.model_validate(wire).model_dump(mode="json") == wire


@pytest.mark.parametrize("rate", ["-0.001", "1", "1.01", "NaN", "Infinity", "0.001e0", ".001", 0.001, True, None])
def test_invalid_or_inferred_rate_refused(rate):
    with pytest.raises(ValidationError):
        CompositePeriodicMemberFee.model_validate(
            {"entry_id": "fee.member-a", "member_id": "MEMBER_A", "period_fee_fraction": rate}
        )


def test_complete_profile_preserves_explicit_method_schedule_calendar():
    wire = profile_wire()
    assert CompositePeriodicModelFeeProfile.model_validate(wire).model_dump(mode="json") == wire


@pytest.mark.parametrize(
    "fault", ["gap", "overlap", "inverted", "missing", "end", "duplicate_member", "duplicate_entry", "date"]
)
def test_incomplete_or_ambiguous_profile_refused(fault):
    wire = profile_wire()
    first, last = wire["periods"]
    if fault == "gap":
        last["period_start"] = "2026-02-02"
    elif fault == "overlap":
        last["period_start"] = "2026-01-31"
    elif fault == "inverted":
        last["period_end"] = "2026-01-30"
    elif fault == "missing":
        wire["periods"].pop(0)
    elif fault == "end":
        wire["effective_to"] = "2026-03-01"
    elif fault == "duplicate_member":
        first["member_rates"].append(copy.deepcopy(first["member_rates"][0]))
    elif fault == "duplicate_entry":
        last["member_rates"][0]["entry_id"] = first["member_rates"][0]["entry_id"]
    else:
        last["period_end"] = "2026-02-30"
    with pytest.raises(ValidationError):
        CompositePeriodicModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gross_source_basis", "NET_ACTUAL"),
        ("fee_component", "PERFORMANCE_FEE"),
        ("transaction_cost_treatment", "CHARGE_TRANSACTION_COST_AGAIN"),
        ("bundled_fee_context", "WRAP"),
        ("rate_basis", "ANNUAL_RATE_DIVIDED_BY_TWELVE"),
        ("timing", "BEGINNING_OF_PERIOD"),
        ("transformation", "ANNUAL_PERCENT_SUBTRACTION"),
        ("asset_treatment", "DEDUCT_FEE_FROM_ASSETS"),
        ("standards_applicability", "GIPS_QUALIFIED"),
        ("approved_by", "CALLER_STRING"),
    ],
)
def test_unsupported_method_and_caller_approval_fields_refused(field, value):
    wire = profile_wire()
    wire[field] = value
    with pytest.raises(ValidationError):
        CompositePeriodicModelFeeProfile.model_validate(wire)


@pytest.mark.parametrize("view,binding_present", [("NET_MODEL_FEE", False), ("GROSS", True), ("NET_ACTUAL", True)])
def test_materialization_view_and_binding_must_form_one_supported_state(view, binding_present):
    _, _, command, _ = model_fee_source_inputs()
    wire = command.model_dump(mode="json")
    wire["return_view"] = view
    if not binding_present:
        wire.pop("model_fee_binding")
    with pytest.raises(ValidationError, match="requires its own model-fee binding"):
        CompositeMaterializationCommand.model_validate(wire)


@pytest.mark.parametrize("view", ["GROSS", "NET_ACTUAL"])
def test_absent_fee_binding_preserves_legacy_immutable_payload(view):
    _, _, command, _ = model_fee_source_inputs()
    wire = command.model_dump(mode="json")
    wire["return_view"] = view
    wire.pop("model_fee_binding")
    restored = CompositeMaterializationCommand.model_validate(wire)
    assert "model_fee_binding" not in restored.immutable_payload()
    expected = {
        key: value for key, value in wire.items() if key not in {"calculation_id", "currency_normalization_binding"}
    }
    assert restored.immutable_payload() == expected
