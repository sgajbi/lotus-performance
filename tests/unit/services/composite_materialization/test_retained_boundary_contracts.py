"""Source-owned evidence cannot be inferred from incompatible or absent receipts."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.models.composite_authority import authority_digest
from app.models.composite_scheduled_model_fees import CompositeScheduledMemberFee, CompositeScheduledModelFeeProfile
from app.services.composite_materialization import (
    authority_policy,
    component_cost_admission,
    component_model_fee_evidence,
    currency_source_admission,
    internal_authority_policy,
    internal_return_method,
    member_evidence_policy,
    model_fee_schedule_rates,
    model_fee_source_admission,
    progress_policy,
    provider_evidence_policy,
    window_currency_authority,
)
from core.errors import APIError
from tests.composite_materialization_helpers import MemberSource, admitted, command_for
from tests.composite_scheduled_model_fee_helpers import scheduled_profile_wire


@pytest.fixture
def retained_member():
    command = command_for()
    source = admitted(command)
    reference = command.member_calculations[0]
    outcome = MemberSource().read_member(
        command,
        reference,
        tenant_id="tenant-a",
        membership_snapshot_id=command.membership_content_hash,
        request_headers={},
    )
    return command, source, reference, outcome


def test_internal_method_requires_pinned_internal_window_and_ready_members(retained_member):
    command, source, _, outcome = retained_member
    record = SimpleNamespace(command=command, source=source, outcomes=[outcome])
    method = internal_return_method.retained_internal_return_method(record)
    assert method["reporting_currency"] == "USD"
    record.source = None
    with pytest.raises(APIError) as error:
        internal_return_method.retained_internal_return_method(record)
    assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_UNAVAILABLE"
    record.source = source
    record.outcomes = [outcome.model_copy(update={"state": "WAITING"})]
    with pytest.raises(APIError) as error:
        internal_return_method.retained_internal_return_method(record)
    assert error.value.error_code == "COMPOSITE_VECTOR_METHOD_UNAVAILABLE"


def test_internal_authority_reference_cannot_substitute_source_fingerprints(retained_member):
    command, source, reference, outcome = retained_member
    for ref, evidence, code in [
        (None, outcome.source_evidence, "COMPOSITE_INTERNAL_RECEIPT_REQUIRED"),
        (reference, None, "COMPOSITE_INTERNAL_RECEIPT_REQUIRED"),
        (
            reference,
            outcome.source_evidence.model_copy(update={"input_fingerprint": "changed"}),
            "COMPOSITE_INTERNAL_RECEIPT_BINDING_MISMATCH",
        ),
    ]:
        with pytest.raises(APIError) as error:
            internal_authority_policy.require_internal_selection_bindings(
                source.definition, command, ref, evidence, facts=("MEMBER_RETURN",)
            )
        assert error.value.error_code == code
    with pytest.raises(APIError):
        member_evidence_policy._require_native_receipt(
            command, outcome.source_evidence.model_copy(update={"membership_snapshot_id": "changed"})
        )


def test_provider_observation_duplicates_and_unavailable_internal_evidence_refuse():
    wire = {"original": "source-evidence"}
    with pytest.raises(APIError):
        provider_evidence_policy.RetainedProviderObservations([wire, wire])
    retained = provider_evidence_policy.RetainedProviderObservations([wire])
    assert retained.read(tenant_id="tenant", selection=SimpleNamespace(source_digest=authority_digest(wire))) == wire
    internal = provider_evidence_policy.RetainedInternalMemberSource(
        None, SimpleNamespace(source_evidence=SimpleNamespace(internal_member_evidence=None))
    )
    with pytest.raises(APIError):
        internal.read_member()
    with pytest.raises(APIError):
        provider_evidence_policy.require_provider_member_evidence(
            SimpleNamespace(definition=None), None, SimpleNamespace(source_evidence=None, fact=None)
        )


def test_unbound_currency_or_fee_evidence_cannot_change_native_source_method():
    command = SimpleNamespace(currency_normalization_binding=None, model_fee_binding=None)
    with pytest.raises(APIError) as error:
        currency_source_admission.fx_resolution_for_command(command, tenant_id="tenant")
    assert error.value.error_code == "COMPOSITE_FX_SOURCE_BINDING_REQUIRED"
    with pytest.raises(APIError) as error:
        progress_policy._require_currency_source(
            SimpleNamespace(currency_normalization_wire={}),
            command=command,
            tenant_id="tenant",
            outcomes=[],
            state="WAITING",
        )
    assert error.value.error_code == "COMPOSITE_FX_SOURCE_BINDING_REQUIRED"
    with pytest.raises(APIError) as error:
        progress_policy._require_model_fee_source(
            SimpleNamespace(model_fee_wire={}, gross_component_wire=None),
            command=command,
            tenant_id="tenant",
            outcomes=[],
            state="WAITING",
        )
    assert error.value.error_code == "COMPOSITE_MODEL_FEE_BINDING_REQUIRED"
    with pytest.raises(APIError) as error:
        window_currency_authority.retained_currency_authority(SimpleNamespace(source=None))
    assert error.value.error_code == "REQUIRED_PERIOD_UNAVAILABLE"


def test_component_evidence_requires_complete_costs_and_exact_reference_wealth():
    with pytest.raises(APIError):
        component_cost_admission.require_component_costs_before_facts(SimpleNamespace(gross_cost_source=None))
    with pytest.raises(ValueError, match="admitted component"):
        component_model_fee_evidence.component_member_evidence(
            gross_evidence=None,
            gross_return=None,
            gross_digest=None,
            beginning_assets=None,
            member_id="member",
            admitted=SimpleNamespace(gross_cost_source=object(), profile=None),
        )
    component_model_fee_evidence._require_reference_wealth(
        SimpleNamespace(reference_wealth_amount="110"), Decimal(100), Decimal("0.1")
    )
    with pytest.raises(ValueError, match="wealth denominator"):
        component_model_fee_evidence._require_reference_wealth(
            SimpleNamespace(reference_wealth_amount="100"), Decimal(100), Decimal("0.1")
        )


def test_component_preflight_preserves_source_refusal_and_converts_binding_refusal(retained_member, monkeypatch):
    command, source, reference, outcome = retained_member
    record = SimpleNamespace(command=command, source=source)
    refusal = outcome.model_copy(update={"fact": None})
    assert component_model_fee_evidence._preflight_member(record, reference, refusal, None) is refusal

    def deny(*args, **kwargs):
        raise APIError(status_code=409, detail="wrong source", error_code="COMPOSITE_INTERNAL_RECEIPT_BINDING_MISMATCH")

    monkeypatch.setattr(internal_authority_policy, "require_internal_selection_bindings", deny)
    result = component_model_fee_evidence._preflight_member(record, reference, outcome, None)
    assert result.state != "READY"
    assert result.reason_code == "COMPOSITE_INTERNAL_RECEIPT_BINDING_MISMATCH"


def test_inverted_schedule_and_nonexecutable_rate_are_refused(monkeypatch):
    period = SimpleNamespace(period_start="2026-01-31", period_end="2026-01-01", member_rates=[object()])
    with pytest.raises(ValueError, match="non-inverted"):
        model_fee_schedule_rates.scheduled_period_fee_fraction(
            CompositeScheduledMemberFee(
                entry_id="entry",
                member_id="member",
                fee_base_amount="100",
                schedule_rule={"algorithm": "FLAT_ANNUAL", "annual_model_wealth_rate": "0.01"},
            ),
            period,
        )
    monkeypatch.setattr(
        model_fee_source_admission, "scheduled_period_fee_fraction", Mock(side_effect=ValueError("invalid rate"))
    )
    with pytest.raises(APIError) as error:
        model_fee_source_admission._require_scheduled_method_scope(
            SimpleNamespace(currency_normalization_wire=None),
            CompositeScheduledModelFeeProfile.model_validate(scheduled_profile_wire()),
            period,
        )
    assert error.value.error_code == "COMPOSITE_SCHEDULED_MODEL_FEE_RATE_NOT_EXECUTABLE"


def test_model_fee_and_lifecycle_approval_cannot_be_inferred_from_absent_published_evidence():
    with pytest.raises(APIError) as error:
        model_fee_source_admission._require_published_method_approval(
            SimpleNamespace(published_eligibility=SimpleNamespace(receipt=None)), None
        )
    assert error.value.error_code == "COMPOSITE_MODEL_FEE_METHOD_APPROVAL_UNAVAILABLE"
    with pytest.raises(APIError) as error:
        authority_policy._verify_lifecycle_approvals(None)
    assert error.value.error_code == "COMPOSITE_ELIGIBILITY_PUBLISHED_CUSTODY_UNAVAILABLE"
