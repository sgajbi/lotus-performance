"""Retained gross receipt, untouched assets, independent rates and release refusals."""

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest

from app.models.composite_materialization import (
    CompositeMemberCalculationReference,
    CompositeMemberMaterializationOutcome,
)
from app.ports import composite_external_evidence as approvals
from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
from app.services.composite_materialization.model_fee_member_evidence import (
    apply_model_fee_or_refuse,
    apply_model_fee_to_outcome,
)
from app.services.composite_materialization.model_fee_source_admission import admit_model_fee_source
from app.services.reproducibility_service import generate_value_fingerprint
from core.errors import APIConflictError
from tests.composite_materialization_helpers import MemberSource, command_for
from tests.composite_model_fee_helpers import SyntheticModelFeeApproval, model_fee_source_inputs


@pytest.fixture
def gross_case(monkeypatch):
    _, wire, command, source = model_fee_source_inputs()
    original = command_for()
    outcome = MemberSource().read_member(
        original,
        original.member_calculations[0],
        tenant_id="tenant-a",
        membership_snapshot_id=original.membership_content_hash,
        request_headers={},
    )
    native = deepcopy(outcome.source_evidence)
    native.calculation_request.portfolio.metric_basis = "GROSS"
    native.membership_snapshot_id = command.membership_content_hash
    native.input_fingerprint, native.calculation_hash = generate_value_fingerprint(
        native.calculation_request, native.engine_version
    )
    reference = CompositeMemberCalculationReference(
        portfolio_id="A",
        calculation_id=native.calculation_request.portfolio.calculation_id,
        input_fingerprint=native.input_fingerprint,
        calculation_hash=native.calculation_hash,
    )
    command = command.model_copy(update={"member_calculations": [reference]})
    fact = outcome.fact.model_copy(
        update={
            "composite_id": command.composite_id,
            "return_view": command.return_view,
            "source_fingerprint": reference.calculation_hash,
            "restatement_version": str(command.materialization_id),
            "source_snapshot_id": generate_value_fingerprint(native, "composite-member-source.v1")[0],
        }
    )
    gross = outcome.model_copy(update={"fact": fact, "source_evidence": native})
    monkeypatch.setattr(approvals, "method_approval_verifier", lambda: SyntheticModelFeeApproval(wire, source))
    admitted = admit_model_fee_source(source, command, tenant_id=source.definition.tenant_id, retained_wire=wire)
    return command, gross, admitted


def require(command, outcome, admitted):
    return require_member_source_evidence(command, outcome, admitted_model_fee_source=admitted)


def test_model_fact_has_distinct_source_and_preserves_original_gross_assets(gross_case):
    command, gross, admitted = gross_case
    wrapped = apply_model_fee_to_outcome(command, gross, admitted)
    require(command, wrapped, admitted)
    assert Fraction(wrapped.fact.return_value) == Fraction(989, 10000)
    assert wrapped.fact.return_view == "NET_MODEL_FEE"
    assert wrapped.fact.source_snapshot_id != gross.fact.source_snapshot_id
    assert wrapped.source_evidence.gross_evidence == gross.source_evidence
    assert wrapped.source_evidence.gross_receipt_digest == gross.fact.source_snapshot_id
    assert (wrapped.fact.beginning_market_value, wrapped.fact.ending_market_value) == (Decimal("100"), Decimal("110"))
    assert gross.fact.return_value == Decimal("0.10")
    restored = CompositeMemberMaterializationOutcome.model_validate(wrapped.model_dump(mode="json"))
    require(command, restored, admitted)
    assert restored == wrapped


def test_valid_gross_receipt_cannot_release_as_unwrapped_model_fact(gross_case):
    command, gross, admitted = gross_case
    with pytest.raises(APIConflictError) as refused:
        require(command, gross, admitted)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED"


@pytest.mark.parametrize("fault", ["rate", "entry", "binding", "gross", "receipt", "model", "assets", "native"])
def test_rehashed_wrapper_tampering_cannot_release(gross_case, fault):
    command, gross, admitted = gross_case
    wrapped = apply_model_fee_to_outcome(command, gross, admitted)
    require(command, wrapped, admitted)
    changed = deepcopy(wrapped)
    evidence = changed.source_evidence
    if fault == "rate":
        evidence.fee_entry.period_fee_fraction = "0.005"
    elif fault == "entry":
        evidence.fee_entry.entry_id = "different-entry"
    elif fault == "binding":
        evidence.model_fee_binding.revision = "different-revision"
    elif fault == "gross":
        evidence.gross_return += Decimal("0.01")
    elif fault == "receipt":
        evidence.gross_receipt_digest = "sha256:" + "8" * 64
    elif fault == "model":
        changed.fact.return_value += Decimal("0.01")
    elif fault == "assets":
        changed.fact.ending_market_value -= Decimal("1")
    else:
        evidence.gross_evidence.calculation_request.portfolio.valuation_points[0].end_mv += Decimal("1")
    changed.fact.source_snapshot_id = generate_value_fingerprint(evidence, "composite-member-source.v4")[0]
    with pytest.raises(APIConflictError):
        require(command, changed, admitted)


def test_actual_net_source_cannot_be_relabelled_as_gross(gross_case):
    command, gross, admitted = gross_case
    changed = deepcopy(gross)
    changed.source_evidence.calculation_request.portfolio.metric_basis = "NET"
    with pytest.raises(APIConflictError) as refused:
        apply_model_fee_to_outcome(command, changed, admitted)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED"
    blocked = apply_model_fee_or_refuse(command, changed, admitted)
    assert blocked.state == "BLOCKED" and blocked.fact is None and blocked.source_evidence is None


def test_model_wrapper_requires_independently_admitted_source(gross_case):
    command, gross, admitted = gross_case
    wrapped = apply_model_fee_to_outcome(command, gross, admitted)
    with pytest.raises(APIConflictError) as refused:
        require_member_source_evidence(command, wrapped)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED"


def test_model_wrapper_cannot_be_used_as_actual_net_evidence(gross_case):
    command, gross, admitted = gross_case
    wrapped = apply_model_fee_to_outcome(command, gross, admitted)
    actual = command.model_copy(update={"return_view": "NET_ACTUAL", "model_fee_binding": None})
    with pytest.raises(APIConflictError):
        require_member_source_evidence(actual, wrapped)


@pytest.mark.parametrize("fault", ["gross_fact", "missing_member_rate", "invalid_period_fraction"])
def test_unusable_gross_or_period_input_blocks_without_model_fact(gross_case, fault):
    command, gross, admitted = deepcopy(gross_case)
    if fault == "gross_fact":
        gross.fact.return_value += Decimal("0.01")
    elif fault == "missing_member_rate":
        admitted.period.member_rates[:] = [entry for entry in admitted.period.member_rates if entry.member_id != "A"]
    else:
        # Fault injection beneath model validation proves the worker's refusal
        # boundary if an admitted port supplies a non-executable period rate.
        admitted.period.member_rates[0].period_fee_fraction = "1"
    result = apply_model_fee_or_refuse(command, gross, admitted)
    assert result.state == "BLOCKED"
    assert result.reason_code == "COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED"
    assert result.fact is None and result.source_evidence is None
