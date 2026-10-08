"""Independent configured approval, exact source scope and immutable schedule refusals."""

from copy import deepcopy

import pytest

from app.ports import composite_external_evidence as approvals
from app.services.composite_materialization.model_fee_source_admission import admit_model_fee_source
from core.errors import APIUnprocessableEntityError
from tests.composite_model_fee_helpers import SyntheticModelFeeApproval, model_fee_source_inputs


def test_first_native_profile_refuses_missing_asset_endpoint_authority_before_member_write(monkeypatch):
    from app.models.composite_authority import ManageCompositeDefinitionV2
    from tests.composite_authority_helpers import rehash_definition

    packet, wire, command, source = model_fee_source_inputs()
    definition = packet["definition"]
    profile = definition["source_authority"]["payload"]
    profile["selections"] = [row for row in profile["selections"] if row["fact"] != "ENDING_ASSETS"]
    rehash_definition(definition)
    source = source.model_copy(update={"definition": ManageCompositeDefinitionV2.model_validate(definition)})
    command = command.model_copy(update={"definition_content_hash": definition["content_hash"]})
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_NATIVE_ASSET_AUTHORITY_REQUIRED"


def approve(monkeypatch, wire, source):
    verifier = SyntheticModelFeeApproval(wire, source)
    monkeypatch.setattr(approvals, "method_approval_verifier", lambda: verifier)


def admit(wire, command, source):
    return admit_model_fee_source(source, command, tenant_id=source.definition.tenant_id, retained_wire=wire)


def test_known_method_approval_retains_exact_schedule_without_resolving_latest(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    approve(monkeypatch, wire, source)
    admitted = admit(wire, command, source)
    assert admitted.source_wire == wire
    assert admitted.period.model_dump(mode="json") == wire["periods"][0]
    assert admitted.profile.schedule_revision == "schedule.1"


def test_default_method_verifier_cannot_bless_known_profile():
    _, wire, command, source = model_fee_source_inputs()
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


def test_default_source_resolver_is_unavailable_even_with_known_method(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit_model_fee_source(source, command, tenant_id=source.definition.tenant_id)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("value", ["approved", 1, {}, None, False])
def test_truthy_strings_or_nonboolean_verifier_results_refused(monkeypatch, value):
    _, wire, command, source = model_fee_source_inputs()

    class InvalidVerifier:
        def verify(self, request):
            return value

    monkeypatch.setattr(approvals, "method_approval_verifier", InvalidVerifier)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


@pytest.mark.parametrize("fault", ["rate", "schedule", "calendar"])
def test_rehashed_drift_under_known_immutable_method_refused(monkeypatch, fault):
    _, original, original_command, original_source = model_fee_source_inputs()
    approve(monkeypatch, original, original_source)
    assert admit(original, original_command, original_source).profile.revision == "profile.1"
    changed = deepcopy(original)
    if fault == "rate":
        changed["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.003"
    elif fault == "schedule":
        changed["schedule_id"] = "different.schedule"
    else:
        changed["calendar_binding"]["digest"] = "sha256:" + "b" * 64
    _, changed, command, source = model_fee_source_inputs(changed)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(changed, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"


def test_unrehashed_schedule_drift_refused_before_independent_approval(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    approve(monkeypatch, wire, source)
    wire["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.003"
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_SOURCE_DIGEST_MISMATCH"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "different-tenant"),
        ("composite_id", "different-composite"),
        ("reporting_currency", "EUR"),
    ],
)
def test_rehashed_profile_scope_drift_refused(monkeypatch, field, value):
    _, wire, _, _ = model_fee_source_inputs()
    wire[field] = value
    _, wire, command, source = model_fee_source_inputs(wire)
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_SOURCE_SCOPE_MISMATCH"


@pytest.mark.parametrize("fault", ["missing", "extra"])
def test_rehashed_member_coverage_mismatch_refused(monkeypatch, fault):
    _, wire, _, _ = model_fee_source_inputs()
    rates = wire["periods"][0]["member_rates"]
    if fault == "missing":
        rates.pop()
    else:
        rates.append({"entry_id": "day.D", "member_id": "D", "period_fee_fraction": "0"})
    _, wire, command, source = model_fee_source_inputs(wire)
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_MEMBER_COVERAGE_MISMATCH"


def test_partial_period_is_not_prorated(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    wire["effective_to"] = wire["periods"][0]["period_end"] = "2026-01-06"
    _, wire, command, source = model_fee_source_inputs(wire)
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_COMPLETE_PERIOD_REQUIRED"


def test_command_binding_must_match_pinned_manage_method(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    approve(monkeypatch, wire, source)
    changed = command.model_copy(
        update={"model_fee_binding": command.model_fee_binding.model_copy(update={"revision": "other"})}
    )
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, changed, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "field,value",
    [
        ("membership_content_hash", "sha256:" + "b" * 64),
        ("source_cut_id", "different-cut"),
    ],
)
def test_source_scope_must_match_immutable_command(monkeypatch, field, value):
    _, wire, command, source = model_fee_source_inputs()
    approve(monkeypatch, wire, source)
    changed = command.model_copy(update={field: value})
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, changed, source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_SOURCE_SCOPE_MISMATCH"


def test_method_verifier_cannot_mutate_retained_profile_wire(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()

    class MutatingVerifier:
        def verify(self, request):
            request.method_evidence_wire["periods"][0]["member_rates"][0]["period_fee_fraction"] = "0.5"
            return True

    monkeypatch.setattr(approvals, "method_approval_verifier", MutatingVerifier)
    assert admit(wire, command, source).source_wire == wire


def test_profile_cannot_be_reused_for_unbound_gross_view(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    approve(monkeypatch, wire, source)
    with pytest.raises(APIUnprocessableEntityError) as refused:
        admit(wire, command.model_copy(update={"return_view": "GROSS"}), source)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_BINDING_REQUIRED"
