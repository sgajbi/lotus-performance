"""Actual retained producer wire compatibility, never institutional qualification."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import composite_eligibility_evidence as models
from app.models.composite_authority import authority_digest
from tests.composite_eligibility_helpers import receipt_wire

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "composite_eligibility_66aec9d2_retained.json"


def producer_receipt():
    # Genuine registered producer candidate66aec9d2 full response; original
    # output bytes SHA256 b0de75f648d65aeb29d614b69a8a4f01d040db3be8eb59f5700eeef740cc4721.
    # Fixture preserves every JSON value/hash; repository LF spelling is not
    # a claim about producer HTTP whitespace or byte framing.
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def retained_assembly():
    return producer_receipt()["finalization"]["evaluation_approval"]["proposal"]["source_assembly_evidence"]


def rehash_receipt(receipt):
    receipt["content_hash"] = authority_digest({key: value for key, value in receipt.items() if key != "content_hash"})


def test_complete_genuine_retained_producer_receipt_roundtrips_without_dropping_evidence():
    wire = producer_receipt()
    result = models.decode_eligibility_receipt(json.dumps(wire))
    assert result.model_dump() == wire
    assert result.completeness == "UNVERIFIED"
    evidence = result.finalization.evaluation_approval.proposal.source_assembly_evidence
    assert evidence.verification.posture == "SYNTHETIC_NON_CERTIFYING"
    assert evidence.verification.request.purpose == "COMPOSITE_MONTHLY_SOURCE_CUT"
    assert len(evidence.assembly.inputs) == 5
    assert (
        result.finalization.definition.authority_approval.claims.approved_at
        >= result.finalization.evaluation_approval.approved_at
    )


def test_legacy_absent_assembly_preserves_original_wire_and_all_nested_hashes():
    wire = receipt_wire()
    result = models.decode_eligibility_receipt(json.dumps(wire))
    assert result.model_dump() == wire
    assert "source_assembly_evidence" not in result.finalization.evaluation_approval.proposal.model_dump()


def test_explicit_null_assembly_is_not_silently_removed_from_hashed_wire():
    wire = receipt_wire()["finalization"]["evaluation_approval"]["proposal"]
    wire["source_assembly_evidence"] = None
    with pytest.raises(ValidationError, match="COMPOSITE_SOURCE_ASSEMBLY_NONCANONICAL_NULL"):
        models.SubjectEvaluationProposal.model_validate(wire)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unsorted", "changed_digest"])
def test_incomplete_noncanonical_or_unbound_input_population_refuses(fault):
    wire = retained_assembly()
    inputs = wire["assembly"]["inputs"]
    if fault == "missing":
        inputs.pop()
    elif fault == "duplicate":
        inputs[0]["kind"] = inputs[1]["kind"]
    elif fault == "unsorted":
        inputs.reverse()
    else:
        inputs[0]["evidence"]["digest"] = "sha256:" + "a" * 64
    with pytest.raises(ValidationError):
        models.VerifiedMonthlySourceAssembly.model_validate(wire)


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "ELIGIBILITY_POLICY_EVALUATION"),
        ("tenant_id", "other-tenant"),
        ("composite_id", "other-composite"),
        ("definition_version", "other-definition"),
        ("effective_from", "2026-09-02"),
        ("effective_to", "2026-09-29"),
        ("claims_digest", "sha256:" + "a" * 64),
        ("subject_content_hash", "sha256:" + "a" * 64),
        ("source_product", "OtherSourceProduct"),
    ],
)
def test_rehashed_verification_must_bind_the_whole_exact_monthly_assembly(field, value):
    wire = retained_assembly()
    wire["verification"]["request"][field] = value
    rehash_receipt(wire["verification"])
    with pytest.raises(ValidationError, match="COMPOSITE_SOURCE_ASSEMBLY_VERIFICATION_MISMATCH"):
        models.VerifiedMonthlySourceAssembly.model_validate(wire)


@pytest.mark.parametrize("fault", ["binding", "qualified", "extra"])
def test_rehashed_binding_posture_or_unknown_authority_refuses(fault):
    wire = retained_assembly()
    if fault == "binding":
        wire["verification"]["request"]["binding"]["revision"] = "other-revision"
    elif fault == "qualified":
        wire["verification"]["posture"] = "QUALIFIED_RECEIPT"
    else:
        wire["unrecognized_authority"] = True
    rehash_receipt(wire["verification"])
    with pytest.raises(ValidationError):
        models.VerifiedMonthlySourceAssembly.model_validate(wire)


def test_fully_rehashed_foreign_observations_cannot_replace_proposal_observations():
    proposal = producer_receipt()["finalization"]["evaluation_approval"]["proposal"]
    wire = proposal["source_assembly_evidence"]
    assembly, verification = wire["assembly"], wire["verification"]
    assembly["observations"]["source_revision"] = "other-source-revision"
    assembly["compatibility_binding"]["digest"] = authority_digest(
        {"observations": assembly["observations"], "inputs": assembly["inputs"]}
    )
    request = verification["request"]
    request["binding"] = deepcopy(assembly["compatibility_binding"])
    request["subject_content_hash"] = authority_digest(assembly["observations"])
    request["claims_digest"] = authority_digest(assembly)
    rehash_receipt(verification)
    rehash_receipt(proposal)
    assert models.VerifiedMonthlySourceAssembly.model_validate(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_SOURCE_ASSEMBLY_OBSERVATIONS_MISMATCH"):
        models.SubjectEvaluationProposal.model_validate(proposal)
