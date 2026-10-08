import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.models import composite_eligibility_evidence as models
from app.models.composite_authority import authority_digest
from app.ports import composite_external_evidence as ports
from tests.composite_eligibility_helpers import (
    producer_fixture,
    receipt_wire,
    rehash_lifecycle,
    resolved_fixture,
    verification_expectation,
)


def test_pinned_r2_roundtrip_preserves_strings_nested_hashes_and_noncertifying_posture():
    fixture = producer_fixture()
    assert fixture["producer_snapshot_sha256"] == "af64f94e52ff4876f21df7ca8706bd1b32271cf753a300756d793c3130f93122"
    decoded = models.decode_eligibility_receipt(json.dumps(fixture["receipt"]))
    assert decoded.model_dump() == fixture["receipt"]
    assert decoded.content_hash == "sha256:817ffbd1b6c1b53215909bd48fd36550517f8b683124e020cd156af26a6a1478"
    approval = decoded.finalization.evaluation_approval
    assert approval.publication_posture == "NOT_PUBLISHED"
    assert approval.official_activation == decoded.finalization.official_activation == "UNAVAILABLE"
    assert decoded.completeness == "UNVERIFIED"
    assert approval.proposal.observations.portfolios[0].flows[0].amount == "150"
    assert approval.proposal.evaluation.resolved_policy.flow_threshold == "0.10"
    assert approval.approved_at == "2026-10-02T00:00:00.000000Z"


@pytest.mark.parametrize("invalid", producer_fixture()["invalid_fixtures"], ids=lambda item: item["model"])
def test_source_owned_negative_fixtures_refuse_the_producer_reason(invalid):
    model = getattr(models, invalid["model"])
    with pytest.raises(ValidationError, match=invalid["expected_refusal"]):
        model.model_validate(invalid["wire"])


@pytest.mark.parametrize(
    "product,digest",
    [
        ("CompositeEligibilitySubject", "7c32edf32f77bef988c96d6e9e5d013dde50f7a62b9a31d834aea1b2358bba7a"),
        ("CompositeSubjectPolicyProposal", "fc86b26dc33abe12cc1b6d73a9651fcb88bdfea94ea046ea718b580fcff78f41"),
        ("CompositeSubjectPolicyApproval", "119981c87c448ea32a58298a028c79a100830d47243169a958dfb50430f8a63b"),
        ("CompositeSubjectEvaluationProposal", "fd8b1f17efeecf173043f7de87f5b36477b5dd36d7ba272d39e3f2bcfe44c1c1"),
        ("CompositeSubjectEvaluationApproval", "7f290d451ba1a94a5f0110d66b60b5a341c88ea7d04e10cd8d52a88161cc2251"),
        ("CompositeDefinition", "43898c82cdb4256126aabc642d68ddd9a51b4fa47643fcc8af7947af74ca786d"),
        ("CompositeEligibilityFinalization", "2887278a70adb94b0dcb84ca23d6c1e1808b15bfbe5d2ce684fae7cf71e9a53e"),
        ("CompositeEligibilityFinalizationReceipt", "817ffbd1b6c1b53215909bd48fd36550517f8b683124e020cd156af26a6a1478"),
    ],
)
def test_eight_pinned_outer_only_hash_vectors(product, digest):
    receipt = receipt_wire()
    finalization = receipt["finalization"]
    evaluation = finalization["evaluation_approval"]
    policy = evaluation["proposal"]["policy_approval"]
    artifacts = [
        receipt,
        finalization,
        finalization["definition"],
        evaluation,
        evaluation["proposal"],
        policy,
        policy["proposal"],
        finalization["subject"],
    ]
    artifact = next(item for item in artifacts if item["product_name"] == product)
    assert artifact["content_hash"] == "sha256:" + digest
    assert (
        authority_digest({key: value for key, value in artifact.items() if key != "content_hash"})
        == artifact["content_hash"]
    )


@pytest.mark.parametrize(
    "wire",
    [
        '{"product_name":"x","product_name":"y"}',
        '{"value":0.10}',
        '{"value":NaN}',
        '{"value":Infinity}',
        "[]",
    ],
)
def test_strict_decoder_refuses_ambiguous_json(wire):
    with pytest.raises(ValueError):
        models.decode_eligibility_receipt(wire)


@pytest.mark.parametrize(
    "path,value",
    [
        (("publication_sequence",), True),
        (("finalization", "subject", "created_at"), "2026-08-20T00:00:00Z"),
        (
            ("finalization", "evaluation_approval", "proposal", "observations", "portfolios", 0, "month_end_assets"),
            1000,
        ),
        (("unexpected",), "extra"),
    ],
)
def test_strict_projection_refuses_coercion_timestamp_rewriting_and_extra_fields(path, value):
    wire = receipt_wire()
    cursor = wire
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError):
        models.decode_eligibility_receipt(json.dumps(wire))


def test_rehashing_outer_envelopes_cannot_hide_nested_hash_tampering():
    wire = receipt_wire()
    wire["finalization"]["evaluation_approval"]["proposal"]["evaluation"]["resolved_policy"]["flow_threshold"] = "0.20"
    wire["finalization"]["content_hash"] = authority_digest(
        {key: value for key, value in wire["finalization"].items() if key != "content_hash"}
    )
    wire["content_hash"] = authority_digest({key: value for key, value in wire.items() if key != "content_hash"})
    with pytest.raises(ValidationError, match="COMPOSITE_ELIGIBILITY_CONTENT_HASH_MISMATCH"):
        models.decode_eligibility_receipt(json.dumps(wire))


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("purpose", "RETURN_METHOD_CALENDAR", "PURPOSE"),
        ("tenant_id", "foreign-tenant", "SCOPE"),
        ("subject_content_hash", "sha256:" + "a" * 64, "SUBJECT"),
        ("effective_to", "2026-10-01", "WINDOW"),
        ("claims_digest", "sha256:" + "b" * 64, "CLAIMS"),
    ],
)
def test_rehashed_evaluation_receipt_cannot_change_its_verification_request(field, value, code):
    wire = receipt_wire()["finalization"]["evaluation_approval"]
    wire["verification"]["request"][field] = value
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_VERIFICATION_" + code + "_MISMATCH"):
        models.SubjectEvaluationApproval.model_validate(wire)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_cut_id", "wrong-cut"),
        ("source_revision", "wrong-revision"),
        ("expected_portfolio_ids", ["wrong-member"]),
    ],
)
def test_rehashed_observations_cannot_change_source_binding_or_member_population(field, value):
    wire = receipt_wire()["finalization"]["evaluation_approval"]["proposal"]
    wire["observations"][field] = value
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_SUBJECT_(SOURCE_BINDING|MEMBER_MAP)_MISMATCH"):
        models.SubjectEvaluationProposal.model_validate(wire)


def test_ports_default_unavailable_and_boolean_or_staged_receipts_never_prove_custody():
    request, result = resolved_fixture()
    unavailable = ports.composite_eligibility_resolver().resolve(request)
    for candidate in (unavailable, True, result.receipt, result.receipt.finalization.evaluation_approval):
        with pytest.raises(ValueError, match="PUBLISHED_CUSTODY_UNAVAILABLE"):
            ports.admit_resolved_eligibility(request, candidate)
    expectation = verification_expectation(result.receipt.finalization.verifications[0])
    unavailable = ports.composite_receipt_verifier().verify(expectation)
    for candidate in (unavailable, True, result.receipt.finalization.verifications[0]):
        with pytest.raises(ValueError, match="VERIFICATION_UNAVAILABLE"):
            ports.admit_verified_receipt(expectation, candidate, allow_synthetic=True)


def test_synthetic_published_test_port_result_is_explicitly_noncertifying():
    request, result = resolved_fixture()
    receipt = ports.admit_resolved_eligibility(request, result)
    assert receipt.finalization.official_activation == "UNAVAILABLE"
    for verification in receipt.finalization.verifications:
        expectation = verification_expectation(verification)
        verified = ports.VerifiedCompositeEvidence(verification)
        with pytest.raises(ValueError, match="QUALIFIED_VERIFICATION_UNAVAILABLE"):
            ports.admit_verified_receipt(expectation, verified)
        admitted = ports.admit_verified_receipt(expectation, verified, allow_synthetic=True)
        assert admitted.posture == "SYNTHETIC_NON_CERTIFYING"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("tenant_id", "wrong-tenant", "SCOPE"),
        ("composite_id", "wrong-composite", "SCOPE"),
        ("definition_version", "wrong-definition", "SCOPE"),
        ("effective_from", "2026-09-02", "WINDOW"),
        ("source_cut_id", "wrong-cut", "PUBLICATION_CUT"),
        ("member_identities", (), "PUBLICATION_MEMBER"),
    ],
)
def test_resolution_requires_exact_consumer_scope_window_cut_and_full_identity_map(field, value, code):
    request, result = resolved_fixture()
    request = replace(request, **{field: value})
    with pytest.raises(ValueError, match=code + "_MISMATCH"):
        ports.admit_resolved_eligibility(request, result)


@pytest.mark.parametrize(
    "binding_name,field,value",
    [
        ("evaluation_binding", "revision", "wrong-revision"),
        ("evaluation_binding", "digest", "sha256:" + "a" * 64),
        ("membership_binding", "revision", "wrong-revision"),
        ("membership_binding", "digest", "sha256:" + "a" * 64),
        ("universe_binding", "revision", "wrong-revision"),
        ("universe_binding", "digest", "sha256:" + "a" * 64),
    ],
)
def test_resolution_refuses_reselected_revision_or_digest(binding_name, field, value):
    request, result = resolved_fixture()
    binding = getattr(request, binding_name).model_copy(update={field: value})
    request = replace(request, **{binding_name: binding})
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        ports.admit_resolved_eligibility(request, result)


@pytest.mark.parametrize("sequence", [True, 0, 2])
def test_published_custody_sequence_is_an_exact_integer_join(sequence):
    request, result = resolved_fixture()
    with pytest.raises(ValueError, match="PUBLICATION_SEQUENCE_MISMATCH"):
        ports.admit_resolved_eligibility(request, replace(result, publication_sequence=sequence))


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer_id", "wrong-issuer"),
        ("verifier_id", "wrong-verifier"),
        ("artifact_revision", "wrong-revision"),
        ("artifact_digest", "sha256:" + "a" * 64),
    ],
)
def test_receipt_body_cannot_select_its_own_trust_metadata(field, value):
    _, result = resolved_fixture()
    receipt = result.receipt.finalization.verifications[0]
    expectation = replace(verification_expectation(receipt), **{field: value})
    with pytest.raises(ValueError, match="VERIFICATION_ARTIFACT_MISMATCH"):
        ports.admit_verified_receipt(expectation, ports.VerifiedCompositeEvidence(receipt), allow_synthetic=True)


def test_fabricated_qualified_receipt_is_not_a_configured_qualified_verifier():
    _, result = resolved_fixture()
    wire = result.receipt.finalization.verifications[0].model_dump()
    wire["posture"] = "QUALIFIED_RECEIPT"
    rehash_lifecycle(wire)
    receipt = models.VerificationReceipt.model_validate(wire)
    with pytest.raises(ValueError, match="QUALIFIED_VERIFICATION_UNAVAILABLE"):
        ports.admit_verified_receipt(
            verification_expectation(receipt), ports.VerifiedCompositeEvidence(receipt), allow_synthetic=True
        )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("included_count", 0, "DECISION_COUNT"),
        ("observed_count", 0, "MEMBER_MAP"),
    ],
)
def test_rehashed_evaluation_counters_must_describe_the_returned_member_decisions(field, value, code):
    wire = receipt_wire()["finalization"]["evaluation_approval"]["proposal"]
    wire["evaluation"][field] = value
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_SUBJECT_" + code + "_MISMATCH"):
        models.SubjectEvaluationProposal.model_validate(wire)


def test_rehashed_evaluation_cannot_duplicate_a_rule_and_omit_another():
    wire = receipt_wire()["finalization"]["evaluation_approval"]["proposal"]
    wire["evaluation"]["portfolios"][0]["assessments"][1]["rule"] = "SIGNIFICANT_FLOW"
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_SUBJECT_RULE_SET_MISMATCH"):
        models.SubjectEvaluationProposal.model_validate(wire)


def test_full_member_map_requires_namespace_and_source_identity_not_just_member_id():
    request, result = resolved_fixture()
    identity = request.member_identities[0].model_copy(update={"namespace": "other-namespace"})
    with pytest.raises(ValueError, match="PUBLICATION_MEMBER_MISMATCH"):
        ports.admit_resolved_eligibility(replace(request, member_identities=(identity,)), result)


def test_duplicate_finalization_purpose_receipts_are_not_additional_authority():
    wire = receipt_wire()["finalization"]
    wire["verifications"].append(wire["verifications"][0].copy())
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_VERIFICATION_DUPLICATE_PURPOSE"):
        models.SubjectFinalization.model_validate(wire)


def test_rehashed_provider_receipt_cannot_select_an_unregistered_revision():
    wire = receipt_wire()["finalization"]
    wire["verifications"][2]["request"]["binding"]["revision"] = "other-registration"
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="COMPOSITE_VERIFICATION_PROVIDER_BINDING_MISMATCH"):
        models.SubjectFinalization.model_validate(wire)


def test_date_shaped_identifier_is_preserved_without_treating_it_as_a_calendar_field():
    wire = receipt_wire()["finalization"]["subject"]
    wire["subject_revision"] = "2026-02-31"
    rehash_lifecycle(wire)
    assert models.EligibilitySubject.model_validate(wire).subject_revision == "2026-02-31"


def test_calendar_timestamp_requires_a_real_date_without_rewriting_valid_wire():
    wire = receipt_wire()["finalization"]["subject"]
    wire["created_at"] = "2026-02-31T00:00:00.000000Z"
    rehash_lifecycle(wire)
    with pytest.raises(ValidationError, match="day is out of range"):
        models.EligibilitySubject.model_validate(wire)
