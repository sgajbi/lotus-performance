"""Pinned synthetic producer material; never certifying or production evidence."""

import json
from copy import deepcopy
from pathlib import Path

from app.models.composite_authority import EvidenceBinding, authority_digest
from app.models.composite_eligibility_evidence import decode_eligibility_receipt
from app.ports.composite_external_evidence import (
    CompositeVerificationExpectation,
    EligibilityResolutionRequest,
    PublishedEligibilityEvidence,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "composite_eligibility_r2.json"
_HASHED_PRODUCTS = {
    "CompositeEligibilityFinalizationReceipt",
    "CompositeEligibilityFinalization",
    "CompositeSubjectEvaluationApproval",
    "CompositeSubjectEvaluationProposal",
    "CompositeMonthlyEligibilityEvaluation",
    "CompositeMonthlyEligibilityPolicy",
    "CompositeSubjectPolicyApproval",
    "CompositeMonthlyPolicyApproval",
    "CompositeMonthlyPolicyProposal",
    "CompositeSubjectPolicyProposal",
    "CompositeEligibilitySubject",
    "CompositeEligibilityCandidateUniverse",
    "CompositeEvidenceVerificationReceipt",
}


def producer_fixture():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def receipt_wire():
    return deepcopy(producer_fixture()["receipt"])


def source_packet():
    fixture = producer_fixture()
    return {
        "definition": fixture["receipt"]["finalization"]["definition"],
        "membership": fixture["membership"],
        "attestation": fixture["universe"],
    }


def install_lifecycle_test_verifier(monkeypatch):
    """Independent fixed synthetic verifier records; no body-selected issuer configuration."""
    from app.ports import composite_external_evidence as ports
    from app.services.composite_materialization import authority_policy

    _, resolved = resolved_fixture()
    finalization = resolved.receipt.finalization
    receipts = [
        finalization.evaluation_approval.proposal.policy_approval.verification,
        finalization.evaluation_approval.verification,
        *finalization.verifications,
    ]

    class FixedSyntheticVerifier:
        def verify(self, request):
            for receipt in receipts:
                if receipt.request == request:
                    return ports.VerifiedCompositeEvidence(receipt, verification_expectation(receipt))
            return ports.UnavailableCompositeEvidence()

    class FixedSyntheticRegistration:
        def resolve(self, request):
            profile = finalization.definition.source_authority.payload
            provider = profile.providers[0]
            valid = (
                request.tenant_id,
                request.provider_id,
                request.registry_revision,
                request.registry_digest,
                request.effective_from,
                request.effective_to,
            ) == (
                finalization.subject.tenant_id,
                provider.provider_id,
                provider.registry_revision,
                provider.registry_digest,
                profile.effective_from,
                profile.effective_to,
            )
            products = {selection.source_product for selection in profile.selections}
            if valid and request.source_product in products:
                return authority_policy.ProviderTrustResolution(
                    "SYNTHETIC_TEST_ONLY", "NON_CERTIFYING_R2_TEST_RECORD", provider.registry_digest
                )
            return authority_policy.ProviderTrustResolution("UNAVAILABLE", "COMPOSITE_PROVIDER_TRUST_UNAVAILABLE")

    monkeypatch.setattr(ports, "composite_receipt_verifier", FixedSyntheticVerifier)
    monkeypatch.setattr(authority_policy, "provider_trust_resolver", FixedSyntheticRegistration)


def rehash_lifecycle(value):
    """Refresh only producer outer envelope hashes; retain all source bindings."""
    if isinstance(value, list):
        for item in value:
            rehash_lifecycle(item)
    if isinstance(value, dict):
        for item in value.values():
            rehash_lifecycle(item)
        if value.get("product_name") in _HASHED_PRODUCTS and "content_hash" in value:
            value["content_hash"] = authority_digest(
                {key: item for key, item in value.items() if key != "content_hash"}
            )
    return value


def resolved_fixture():
    receipt = decode_eligibility_receipt(json.dumps(receipt_wire()))
    finalization = receipt.finalization
    approval = finalization.evaluation_approval
    subject = finalization.subject
    membership = EvidenceBinding(
        product_name="CompositeMembership",
        product_version="v1",
        revision=approval.proposal.target_membership_revision,
        digest=receipt.membership_content_hash,
    )
    universe = EvidenceBinding(
        product_name="CompositeUniverseAttestation",
        product_version="v1",
        revision=approval.proposal.evaluation_revision,
        digest=receipt.universe_content_hash,
    )
    identities = tuple(subject.universe.members)
    request = EligibilityResolutionRequest(
        tenant_id=subject.tenant_id,
        composite_id=subject.composite_id,
        definition_version=subject.definition_version,
        evaluation_binding=finalization.definition.source_authority.payload.eligibility_evaluation_binding,
        membership_binding=membership,
        universe_binding=universe,
        source_cut_id=subject.universe.source_cut_id,
        effective_from=subject.universe.coverage_from,
        effective_to=subject.universe.coverage_to,
        member_identities=identities,
    )
    result = PublishedEligibilityEvidence(
        receipt=receipt,
        membership_binding=membership,
        universe_binding=universe,
        source_cut_id=subject.universe.source_cut_id,
        publication_sequence=receipt.publication_sequence,
        member_identities=identities,
    )
    return request, result


def verification_expectation(receipt):
    return CompositeVerificationExpectation(
        request=receipt.request,
        verifier_id=receipt.verifier_id,
        issuer_id=receipt.issuer_id,
        artifact_revision=receipt.artifact_revision,
        artifact_digest=receipt.artifact_digest,
    )
