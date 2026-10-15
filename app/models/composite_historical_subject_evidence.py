"""Additive historical staged graphs; decoding never grants source authority."""

import base64
import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, model_serializer, model_validator

from app.models.composite_authority import (
    Digest,
    EvidenceBinding,
    Identifier,
    Instant,
    ManageCompositeDefinitionV2,
    authority_digest,
)
from app.models.composite_eligibility_evidence import (
    DpmCompositeUniverseSourceProduct,
    EligibilitySubject,
    EligibilityWire,
    HashedEligibilityWire,
    MonthlyEligibilityEvaluation,
    MonthlyEligibilityObservations,
    MonthlyPolicyScope,
    ResolvedMonthlyPolicy,
    SubjectEvaluationProposal,
    VerificationReceipt,
    VerifiedMonthlySourceAssembly,
    _equal,
    _month_window,
    _require,
    _verification_subject,
    require_subject_evaluation,
    require_subject_evaluation_approval,
    require_subject_finalization,
)


class HistoricalPolicyReference(EligibilityWire):
    issuer_id: Identifier
    artifact_id: Identifier
    revision: Identifier
    raw_digest: Digest
    signing_contract: Identifier


class HistoricalPolicyMapping(HashedEligibilityWire):
    reference: HistoricalPolicyReference
    raw_original_base64: str = Field(min_length=4, max_length=2800000)
    original_credential: str = Field(min_length=1, max_length=16384)
    policy: ResolvedMonthlyPolicy
    eligibility_policy_version: Identifier
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    attachments: list[EvidenceBinding] = Field(min_length=1, max_length=20)
    original_proposed_by: Identifier
    original_proposed_at: Instant
    original_approved_by: Identifier
    original_approved_at: Instant

    @model_validator(mode="after")
    def original_mapping(self) -> Self:
        raw = base64.b64decode(self.raw_original_base64, validate=True)
        _require(
            0 < len(raw) <= 2000000 and base64.b64encode(raw).decode() == self.raw_original_base64,
            "COMPOSITE_HISTORICAL_POLICY_RAW_INVALID",
        )
        _require(
            "sha256:" + hashlib.sha256(raw).hexdigest() == self.reference.raw_digest,
            "COMPOSITE_HISTORICAL_POLICY_RAW_MISMATCH",
        )
        _require(
            self.original_proposed_at <= self.original_approved_at < _month_window(self.policy.month)[0],
            "COMPOSITE_HISTORICAL_POLICY_ORIGINAL_CLOCK_INVALID",
        )
        _require(
            self.original_proposed_by != self.original_approved_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN"
        )
        keys = [(item.product_name, item.product_version, item.revision) for item in self.attachments]
        _require(keys == sorted(set(keys)), "COMPOSITE_ELIGIBILITY_ATTACHMENTS_NONCANONICAL")
        return self


class HistoricalPolicyVerificationRequest(EligibilityWire):
    product_name: Literal["CompositeHistoricalPolicyVerificationRequest"]
    product_version: Literal["v1"]
    purpose: Literal["COMPOSITE_HISTORICAL_MONTHLY_POLICY_ADMISSION"]
    operation: Literal["POLICY_PROPOSAL", "POLICY_APPROVAL", "EVALUATION_PROPOSAL", "EVALUATION_APPROVAL"]
    reference: HistoricalPolicyReference
    scope: MonthlyPolicyScope
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    eligibility_policy_version: Identifier
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    revision: Identifier
    actor_id: Identifier
    requested_at: Instant
    intent_digest: Digest


class HistoricalPolicyVerification(HashedEligibilityWire):
    product_name: Literal["CompositeHistoricalPolicyVerification"]
    product_version: Literal["v1"]
    posture: Literal["SYNTHETIC_NON_CERTIFYING"]
    original_signature_status: Literal["VERIFIED_AT_ORIGINAL_APPROVAL"]
    current_revocation_status: Literal["CLEAR"]
    request: HistoricalPolicyVerificationRequest
    mapping: HistoricalPolicyMapping
    verifier_id: Identifier
    signer_principal_id: Identifier
    verifier_principal_id: Identifier
    configuration_digest: Digest
    signer_key_digest: Digest
    verifier_key_digest: Digest
    verifier_public_key_base64: str = Field(min_length=44, max_length=44)
    revocation_revision: Identifier
    revocation_digest: Digest
    checked_at: Instant
    expires_at: Instant
    admitted_at: Instant
    verifier_credential: str = Field(min_length=1, max_length=16384)

    @model_validator(mode="after")
    def exact_admission(self) -> Self:
        request, mapping = self.request, self.mapping
        actual = (
            request.reference,
            request.scope,
            request.month,
            request.eligibility_policy_version,
            request.reporting_currency,
        )
        expected = (
            mapping.reference,
            mapping.policy.scope,
            mapping.policy.month,
            mapping.eligibility_policy_version,
            mapping.reporting_currency,
        )
        _require(actual == expected, "COMPOSITE_HISTORICAL_POLICY_MAPPING_MISMATCH")
        _require(
            self.signer_principal_id != self.verifier_principal_id
            and self.signer_key_digest != self.verifier_key_digest,
            "COMPOSITE_HISTORICAL_POLICY_INDEPENDENCE_REQUIRED",
        )
        _historical_admission_window(self)
        _historical_signature(self)
        return self


def _historical_admission_window(proof):
    checked, admitted, expiry = map(datetime.fromisoformat, (proof.checked_at, proof.admitted_at, proof.expires_at))
    requested = datetime.fromisoformat(proof.request.requested_at)
    _require(
        requested >= datetime.fromisoformat(proof.mapping.original_approved_at),
        "COMPOSITE_HISTORICAL_POLICY_ORIGINAL_CLOCK_INVALID",
    )
    _require(
        checked <= requested <= admitted < expiry <= checked + timedelta(minutes=5),
        "COMPOSITE_HISTORICAL_POLICY_ADMISSION_WINDOW_INVALID",
    )


def _historical_signature(proof):
    try:
        key = base64.b64decode(proof.verifier_public_key_base64, validate=True)
        _require(
            "sha256:" + hashlib.sha256(key).hexdigest() == proof.verifier_key_digest,
            "COMPOSITE_HISTORICAL_POLICY_VERIFIER_SIGNATURE_INVALID",
        )
        signature = base64.b64decode(proof.verifier_credential, validate=True)
        unsigned = proof.model_dump(mode="json", exclude={"content_hash", "verifier_credential"})
        Ed25519PublicKey.from_public_bytes(key).verify(signature, authority_digest(unsigned).encode())
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("COMPOSITE_HISTORICAL_POLICY_VERIFIER_SIGNATURE_INVALID") from exc


def _operation_binding(proof, *, operation, revision, actor, instant, intent, mapping):
    actual = (
        proof.request.operation,
        proof.request.revision,
        proof.request.actor_id,
        proof.request.requested_at,
        proof.request.intent_digest,
        proof.mapping,
    )
    _require(
        actual == (operation, revision, actor, instant, intent, mapping), "COMPOSITE_HISTORICAL_POLICY_REQUEST_MISMATCH"
    )


class HistoricalMonthlyPolicyProposal(HashedEligibilityWire):
    product_name: Literal["CompositeMonthlyPolicyProposal"]
    product_version: Literal["v2"]
    proposal_revision: Identifier
    eligibility_policy_version: Identifier
    policy: ResolvedMonthlyPolicy
    attachments: list[EvidenceBinding] = Field(min_length=1, max_length=20)
    proposed_by: Identifier
    proposed_at: Instant
    verification: HistoricalPolicyVerification

    @model_validator(mode="after")
    def present_admission(self) -> Self:
        mapping = self.verification.mapping
        _require(
            (self.policy, self.attachments, self.eligibility_policy_version)
            == (mapping.policy, mapping.attachments, mapping.eligibility_policy_version),
            "COMPOSITE_HISTORICAL_POLICY_MAPPING_MISMATCH",
        )
        intent = authority_digest(
            {"reference": mapping.reference.model_dump(mode="json"), "proposal_revision": self.proposal_revision}
        )
        _operation_binding(
            self.verification,
            operation="POLICY_PROPOSAL",
            revision=self.proposal_revision,
            actor=self.proposed_by,
            instant=self.proposed_at,
            intent=intent,
            mapping=mapping,
        )
        return self


class HistoricalMonthlyPolicyApproval(HashedEligibilityWire):
    product_name: Literal["CompositeMonthlyPolicyApproval"]
    product_version: Literal["v2"]
    evidence_kind: Literal["VERIFIED_HISTORICAL_MAPPING"]
    official_activation: Literal["UNAVAILABLE"]
    proposal: HistoricalMonthlyPolicyProposal
    approved_by: Identifier
    approved_at: Instant
    verification: HistoricalPolicyVerification

    @model_validator(mode="after")
    def current_independent_approval(self) -> Self:
        _require(self.approved_by != self.proposal.proposed_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN")
        _require(self.approved_at >= self.proposal.proposed_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")
        _operation_binding(
            self.verification,
            operation="POLICY_APPROVAL",
            revision=self.proposal.proposal_revision,
            actor=self.approved_by,
            instant=self.approved_at,
            intent=self.proposal.content_hash,
            mapping=self.proposal.verification.mapping,
        )
        return self


class HistoricalSubjectPolicyProposal(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectPolicyProposal"]
    product_version: Literal["v2"]
    proposal: HistoricalMonthlyPolicyProposal
    subject: EligibilitySubject
    verification: VerificationReceipt

    @model_validator(mode="after")
    def historical_policy_links(self) -> Self:
        policy = self.proposal.policy
        _equal(
            self.subject,
            policy.scope,
            ("tenant_id", "composite_id", "definition_version", "strategy_code"),
            "COMPOSITE_SUBJECT_POLICY_SCOPE_MISMATCH",
        )
        _require(
            (policy.month, self.proposal.eligibility_policy_version)
            == (self.subject.month, self.subject.eligibility_policy_version),
            "COMPOSITE_SUBJECT_POLICY_SCOPE_MISMATCH",
        )
        _require(
            self.subject.universe.registry_binding in self.proposal.attachments,
            "COMPOSITE_SUBJECT_REGISTRY_BINDING_MISMATCH",
        )
        _require(self.subject.created_at <= self.proposal.proposed_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")
        _require(self.proposal.proposed_by == self.subject.created_by, "COMPOSITE_SUBJECT_MAKER_MISMATCH")
        _require(
            self.proposal.verification.mapping.reporting_currency == self.subject.reporting_currency,
            "COMPOSITE_SUBJECT_POLICY_SCOPE_MISMATCH",
        )
        _outer_policy_verification(self.verification, self.subject, "proposal_content_hash", self.proposal.content_hash)
        return self


def _outer_policy_verification(verification, subject, key, digest):
    _verification_subject(verification.request, subject, "ELIGIBILITY_POLICY")
    _require(
        (verification.posture, verification.request.binding, verification.request.source_product)
        == ("SYNTHETIC_NON_CERTIFYING", None, None),
        "COMPOSITE_VERIFICATION_BINDING_MISMATCH",
    )
    expected = authority_digest({"subject_content_hash": subject.content_hash, key: digest})
    _require(verification.request.claims_digest == expected, "COMPOSITE_VERIFICATION_CLAIMS_MISMATCH")


class HistoricalSubjectPolicyApproval(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectPolicyApproval"]
    product_version: Literal["v2"]
    proposal: HistoricalSubjectPolicyProposal
    approval: HistoricalMonthlyPolicyApproval
    verification: VerificationReceipt

    @model_validator(mode="after")
    def historical_approval_links(self) -> Self:
        _require(self.approval.proposal == self.proposal.proposal, "COMPOSITE_SUBJECT_POLICY_BINDING_MISMATCH")
        _outer_policy_verification(
            self.verification, self.proposal.subject, "approval_content_hash", self.approval.content_hash
        )
        return self


class HistoricalSubjectEvaluationProposal(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectEvaluationProposal"]
    product_version: Literal["v2"]
    evaluation: MonthlyEligibilityEvaluation
    evaluation_kind: Literal["INITIAL"]
    evaluation_revision: Identifier
    observation_binding: DpmCompositeUniverseSourceProduct
    observations: MonthlyEligibilityObservations
    source_assembly_evidence: VerifiedMonthlySourceAssembly | None = None
    policy_approval: HistoricalSubjectPolicyApproval
    operation_verification: HistoricalPolicyVerification
    proposed_at: Instant
    proposed_by: Identifier
    target_membership_revision: Identifier

    @model_serializer(mode="wrap")
    def original_optional_assembly(self, handler):
        payload = handler(self)
        if self.source_assembly_evidence is None:
            payload.pop("source_assembly_evidence", None)
        return payload

    @model_validator(mode="before")
    @classmethod
    def canonical_optional_assembly(cls, value):
        return SubjectEvaluationProposal.canonical_optional_assembly_field(value)

    @model_validator(mode="after")
    def historical_evaluation_links(self) -> Self:
        require_subject_evaluation(self)
        _require(self.proposed_at == self.evaluation.evaluated_at, "COMPOSITE_SUBJECT_EVALUATION_BINDING_MISMATCH")
        _require(self.proposed_at >= self.policy_approval.approval.approved_at, "COMPOSITE_ELIGIBILITY_CLOCK_MISMATCH")
        _require(
            self.observations.evidence_class == "SYNTHETIC_UNQUALIFIED",
            "COMPOSITE_SUBJECT_HISTORICAL_POLICY_POSTURE_UNAVAILABLE",
        )
        intent = authority_digest(self.model_dump(mode="json", exclude={"content_hash", "operation_verification"}))
        _operation_binding(
            self.operation_verification,
            operation="EVALUATION_PROPOSAL",
            revision=self.evaluation_revision,
            actor=self.proposed_by,
            instant=self.proposed_at,
            intent=intent,
            mapping=self.policy_approval.approval.proposal.verification.mapping,
        )
        return self


class HistoricalSubjectEvaluationApproval(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectEvaluationApproval"]
    product_version: Literal["v2"]
    approved_at: Instant
    approved_by: Identifier
    claims_digest: Digest
    evidence_kind: Literal["SYNTHETIC_UNSIGNED"]
    membership_content_hash: Digest
    official_activation: Literal["UNAVAILABLE"]
    proposal: HistoricalSubjectEvaluationProposal
    publication_posture: Literal["NOT_PUBLISHED"]
    universe_content_hash: Digest
    verification: VerificationReceipt
    operation_verification: HistoricalPolicyVerification

    @model_validator(mode="after")
    def historical_evaluation_approval(self) -> Self:
        require_subject_evaluation_approval(self)
        expected_claims = authority_digest(
            {
                "purpose": "ELIGIBILITY_POLICY_EVALUATION",
                "subject_content_hash": self.proposal.policy_approval.proposal.subject.content_hash,
                "proposal_content_hash": self.proposal.content_hash,
                "approved_by": self.approved_by,
                "approved_at": self.approved_at,
            }
        )
        _require(self.claims_digest == expected_claims, "COMPOSITE_SUBJECT_APPROVAL_CLAIMS_MISMATCH")
        _operation_binding(
            self.operation_verification,
            operation="EVALUATION_APPROVAL",
            revision=self.proposal.evaluation_revision,
            actor=self.approved_by,
            instant=self.approved_at,
            intent=self.proposal.content_hash,
            mapping=self.proposal.policy_approval.approval.proposal.verification.mapping,
        )
        return self


class HistoricalSubjectFinalization(HashedEligibilityWire):
    product_name: Literal["CompositeEligibilityFinalization"]
    product_version: Literal["v3"]
    definition: ManageCompositeDefinitionV2
    evaluation_approval: HistoricalSubjectEvaluationApproval
    official_activation: Literal["UNAVAILABLE"]
    subject: EligibilitySubject
    verifications: list[VerificationReceipt] = Field(min_length=3, max_length=258)

    @model_validator(mode="after")
    def historical_finalization(self) -> Self:
        _require(
            self.definition.authority_approval.evidence_kind == "SYNTHETIC_UNSIGNED",
            "COMPOSITE_SUBJECT_HISTORICAL_POLICY_POSTURE_UNAVAILABLE",
        )
        _require(
            all(receipt.posture == "SYNTHETIC_NON_CERTIFYING" for receipt in self.verifications),
            "COMPOSITE_SUBJECT_HISTORICAL_POLICY_POSTURE_UNAVAILABLE",
        )
        require_subject_finalization(self)
        return self


class HistoricalSubjectFinalizationReceipt(HashedEligibilityWire):
    product_name: Literal["CompositeEligibilityFinalizationReceipt"]
    product_version: Literal["v3"]
    completeness: Literal["UNVERIFIED"]
    finalization: HistoricalSubjectFinalization
    membership_content_hash: Digest
    publication_sequence: Annotated[int, Field(ge=1)]
    universe_content_hash: Digest

    @model_validator(mode="after")
    def historical_receipt(self) -> Self:
        _equal(
            self,
            self.finalization.evaluation_approval,
            ("membership_content_hash", "universe_content_hash"),
            "COMPOSITE_SUBJECT_PUBLICATION_HASH_MISMATCH",
        )
        return self
