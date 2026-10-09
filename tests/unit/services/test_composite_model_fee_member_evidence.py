"""Retained gross receipt, untouched assets, independent rates and release refusals."""

from copy import deepcopy
from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, Rounded, localcontext
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
from tests.composite_scheduled_model_fee_helpers import scheduled_source_inputs


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


@pytest.fixture
def scheduled_gross_case(gross_case, monkeypatch):
    original, gross, _ = gross_case
    _, wire, command, source = scheduled_source_inputs()
    command = command.model_copy(update={"member_calculations": original.member_calculations})
    gross = gross.model_copy(
        update={"fact": gross.fact.model_copy(update={"restatement_version": str(command.materialization_id)})}
    )
    monkeypatch.setattr(approvals, "method_approval_verifier", lambda: SyntheticModelFeeApproval(wire, source))
    admitted = admit_model_fee_source(source, command, tenant_id=source.definition.tenant_id, retained_wire=wire)
    return command, gross, admitted


def test_scheduled_v5_retains_original_gross_assets_and_exact_derived_ratio(scheduled_gross_case):
    command, gross, admitted = scheduled_gross_case
    wrapped = apply_model_fee_to_outcome(command, gross, admitted)
    require(command, wrapped, admitted)
    expected = Fraction(11, 10) * (1 - Fraction(3, 91250)) - 1
    assert abs(Fraction(wrapped.fact.return_value) - expected) < Fraction("1e-75")
    assert wrapped.source_evidence.contract_version == "composite-member-source.v5"
    assert wrapped.source_evidence.gross_evidence == gross.source_evidence
    assert wrapped.source_evidence.fee_entry.fee_base_amount == "100"
    assert wrapped.fact.beginning_market_value == gross.fact.beginning_market_value == Decimal(100)
    assert wrapped.fact.ending_market_value == gross.fact.ending_market_value == Decimal(110)
    restored = CompositeMemberMaterializationOutcome.model_validate(wrapped.model_dump(mode="json"))
    require(command, restored, admitted)
    assert restored == wrapped


@pytest.mark.parametrize("fault", ["missing_gross_receipt", "net_basis_receipt"])
def test_scheduled_fee_refuses_missing_or_net_receipt_without_mutating_gross(scheduled_gross_case, fault):
    command, gross, admitted = scheduled_gross_case
    original = gross.model_dump(mode="json")
    accepted = apply_model_fee_to_outcome(command, gross, admitted)
    require(command, accepted, admitted)
    corrupted = deepcopy(gross)
    if fault == "missing_gross_receipt":
        corrupted.source_evidence = None
    else:
        native = corrupted.source_evidence
        native.calculation_request.portfolio.metric_basis = "NET"
        native.input_fingerprint, native.calculation_hash = generate_value_fingerprint(
            native.calculation_request, native.engine_version
        )
        corrupted.fact.source_fingerprint = native.calculation_hash
        corrupted.fact.source_snapshot_id = generate_value_fingerprint(native, "composite-member-source.v1")[0]
    with pytest.raises(APIConflictError) as refused:
        apply_model_fee_to_outcome(command, corrupted, admitted)
    assert refused.value.error_code == "COMPOSITE_MODEL_FEE_MEMBER_EVIDENCE_REFUSED"
    assert gross.model_dump(mode="json") == original


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
@pytest.mark.parametrize("precision", [9, 150])
def test_scheduled_actual_member_boundary_numbers_and_pins_ignore_ambient_context(
    scheduled_gross_case, rounding, precision
):
    command, gross, admitted = scheduled_gross_case
    reference = apply_model_fee_to_outcome(command, gross, admitted)
    with localcontext() as context:
        context.prec, context.rounding = precision, rounding
        context.Emin, context.Emax = -9, 9
        context.traps[Inexact] = context.traps[Rounded] = True
        flags = context.flags.copy()
        result = apply_model_fee_to_outcome(command, gross, admitted)
        require(command, result, admitted)
        assert result.model_dump(mode="json") == reference.model_dump(mode="json")
        assert context.prec == precision and context.rounding == rounding
        assert context.Emin == -9 and context.Emax == 9
        assert dict(context.flags) == flags and context.traps[Inexact] and context.traps[Rounded]


@pytest.mark.parametrize("fault", ["rate", "base", "derived_fraction", "version", "fact_base"])
def test_scheduled_rehashed_entry_fraction_namespace_or_original_base_tamper_refuses(scheduled_gross_case, fault):
    command, gross, admitted = scheduled_gross_case
    wrapped = deepcopy(apply_model_fee_to_outcome(command, gross, admitted))
    evidence = wrapped.source_evidence
    if fault == "rate":
        evidence.fee_entry.schedule_rule.annual_model_wealth_rate = "0.02"
    elif fault == "base":
        evidence.fee_entry.fee_base_amount = "101"
    elif fault == "derived_fraction":
        evidence.derived_period_fee_fraction = "0.0001"
    elif fault == "version":
        evidence.contract_version = "composite-member-source.v4"
    else:
        wrapped.fact.beginning_market_value = Decimal(101)
    wrapped.fact.source_snapshot_id = generate_value_fingerprint(evidence, evidence.contract_version)[0]
    with pytest.raises(APIConflictError):
        require(command, wrapped, admitted)


def test_scheduled_profile_base_cannot_replace_genuine_original_asset_observation(scheduled_gross_case):
    command, gross, admitted = scheduled_gross_case
    admitted.period.member_rates[0].fee_base_amount = "101"
    result = apply_model_fee_or_refuse(command, gross, admitted)
    assert result.state == "BLOCKED" and result.fact is None and result.source_evidence is None


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
