"""Annual schedules retain independent method authority and native source limits."""

from copy import deepcopy

import pytest

from app.ports import composite_external_evidence as approvals
from app.services.composite_materialization.model_fee_source_admission import admit_model_fee_source
from core.errors import APIUnprocessableEntityError
from tests.composite_model_fee_helpers import SyntheticModelFeeApproval, model_fee_source_inputs
from tests.composite_scheduled_model_fee_helpers import scheduled_source_inputs


def admit(wire, command, source):
    return admit_model_fee_source(source, command, tenant_id=source.definition.tenant_id, retained_wire=wire)


def approve(monkeypatch, wire, source):
    verifier = SyntheticModelFeeApproval(wire, source)
    monkeypatch.setattr(approvals, "method_approval_verifier", lambda: verifier)


def test_scheduled_default_approval_and_resolver_stay_unavailable(monkeypatch):
    _, wire, command, source = scheduled_source_inputs()
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit_model_fee_source(source, command, tenant_id=source.definition.tenant_id)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_SOURCE_UNAVAILABLE"
    retained = admit(wire, command, source)
    assert retained.source_wire == wire
    assert retained.period.model_dump(mode="json") == wire["periods"][0]


@pytest.mark.parametrize("value", ["approved", 1, {}, None, False])
def test_scheduled_nonboolean_verifier_cannot_confer_authority(monkeypatch, value):
    _, wire, command, source = scheduled_source_inputs()

    class InvalidVerifier:
        def verify(self, request):
            return value

    monkeypatch.setattr(approvals, "method_approval_verifier", InvalidVerifier)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


@pytest.mark.parametrize("fault", ["rate", "schedule", "calendar", "base"])
def test_scheduled_rehashed_profile_drift_is_not_approval(monkeypatch, fault):
    _, original, command, source = scheduled_source_inputs()
    approve(monkeypatch, original, source)
    assert admit(original, command, source).source_wire == original
    changed = deepcopy(original)
    if fault == "rate":
        changed["periods"][0]["member_rates"][0]["schedule_rule"]["annual_model_wealth_rate"] = "0.03"
    elif fault == "schedule":
        changed["schedule_id"] = "changed.schedule"
    elif fault == "calendar":
        changed["calendar_binding"]["digest"] = "sha256:" + "b" * 64
    else:
        changed["periods"][0]["member_rates"][0]["fee_base_amount"] = "101"
    _, changed, changed_command, changed_source = model_fee_source_inputs(changed)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(changed, changed_command, changed_source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


def test_scheduled_fx_assets_do_not_silently_enter_native_schedule(monkeypatch):
    _, wire, command, source = scheduled_source_inputs()
    approve(monkeypatch, wire, source)
    source = source.model_copy(update={"currency_normalization_wire": {"unqualified": "foreign asset projection"}})
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_SCHEDULED_MODEL_FEE_NATIVE_ASSETS_REQUIRED"
