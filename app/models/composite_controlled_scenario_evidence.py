"""Explicit synthetic scenario wires; no historical-signature or bank-authority alias."""

import base64
import hashlib
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import Field, model_serializer, model_validator

from app.models.composite_authority import (
    ControlledScenarioDefinitionV3,
    Digest,
    EvidenceBinding,
    Identifier,
    Instant,
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
    require_subject_finalization,
)
from app.models.composite_historical_subject_evidence import (
    HistoricalPolicyReference,
    _historical_signature,
    _outer_policy_verification,
    require_mapped_policy_approval,
    require_mapped_policy_proposal,
    require_mapped_subject_evaluation,
    require_mapped_subject_evaluation_approval,
    require_mapped_subject_policy,
)


class ControlledScenarioPolicyMapping(HashedEligibilityWire):
    reference: HistoricalPolicyReference
    raw_original_base64: str = Field(min_length=4, max_length=2800000)
    original_credential: str = Field(min_length=1, max_length=16384)
    policy: ResolvedMonthlyPolicy
    eligibility_policy_version: Identifier
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    attachments: list[EvidenceBinding] = Field(min_length=1, max_length=20)
    scenario_proposed_by: Identifier
    scenario_proposed_at: Instant
    scenario_approved_by: Identifier
    scenario_approved_at: Instant
    actual_issued_at: Instant

    @model_validator(mode="after")
    def scenario_declaration(self) -> Self:
        raw = base64.b64decode(self.raw_original_base64, validate=True)
        _require(
            0 < len(raw) <= 2000000 and base64.b64encode(raw).decode() == self.raw_original_base64,
            "COMPOSITE_HISTORICAL_POLICY_RAW_INVALID",
        )
        _require(
            "sha256:" + hashlib.sha256(raw).hexdigest() == self.reference.raw_digest,
            "COMPOSITE_HISTORICAL_POLICY_RAW_MISMATCH",
        )
        for instant in (self.scenario_proposed_at, self.scenario_approved_at, self.actual_issued_at):
            datetime.strptime(instant, "%Y-%m-%dT%H:%M:%S.%fZ")
        _require(
            self.scenario_proposed_at <= self.scenario_approved_at < _month_window(self.policy.month)[0]
            and self.actual_issued_at >= self.scenario_approved_at,
            "COMPOSITE_CONTROLLED_SCENARIO_CLOCK_INVALID",
        )
        _require(
            self.scenario_proposed_by != self.scenario_approved_by, "COMPOSITE_ELIGIBILITY_SELF_APPROVAL_FORBIDDEN"
        )
        keys = [(item.product_name, item.product_version, item.revision) for item in self.attachments]
        _require(keys == sorted(set(keys)), "COMPOSITE_ELIGIBILITY_ATTACHMENTS_NONCANONICAL")
        return self


class ControlledScenarioVerificationRequest(EligibilityWire):
    product_name: Literal["CompositeHistoricalPolicyVerificationRequest"]
    product_version: Literal["v2"]
    purpose: Literal["COMPOSITE_CONTROLLED_SCENARIO_POLICY_ADMISSION"]
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


class ControlledScenarioVerification(HashedEligibilityWire):
    product_name: Literal["CompositeHistoricalPolicyVerification"]
    product_version: Literal["v2"]
    posture: Literal["SYNTHETIC_NON_CERTIFYING"]
    original_signature_status: Literal["VERIFIED_AT_ACTUAL_ISSUANCE"]
    signature_semantics: Literal["SCENARIO_DECLARATION_AT_ACTUAL_ISSUANCE"]
    current_revocation_status: Literal["CLEAR"]
    request: ControlledScenarioVerificationRequest
    mapping: ControlledScenarioPolicyMapping
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
    def exact_scenario_admission(self) -> Self:
        request, mapping = self.request, self.mapping
        _require(
            (
                request.reference,
                request.scope,
                request.month,
                request.eligibility_policy_version,
                request.reporting_currency,
            )
            == (
                mapping.reference,
                mapping.policy.scope,
                mapping.policy.month,
                mapping.eligibility_policy_version,
                mapping.reporting_currency,
            ),
            "COMPOSITE_HISTORICAL_POLICY_MAPPING_MISMATCH",
        )
        _require(
            self.signer_principal_id != self.verifier_principal_id
            and self.signer_key_digest != self.verifier_key_digest,
            "COMPOSITE_HISTORICAL_POLICY_INDEPENDENCE_REQUIRED",
        )
        _scenario_admission_window(self)
        # The existing algorithm verifies the full proof excluding only its two
        # declared top-level fields. Version/status/semantics remain signed.
        _historical_signature(self)
        return self


def _scenario_admission_window(proof):
    checked, admitted, expiry = map(datetime.fromisoformat, (proof.checked_at, proof.admitted_at, proof.expires_at))
    requested = datetime.fromisoformat(proof.request.requested_at)
    issued = datetime.fromisoformat(proof.mapping.actual_issued_at)
    _require(issued <= requested, "COMPOSITE_CONTROLLED_SCENARIO_CLOCK_INVALID")
    _require(
        checked <= requested <= admitted < expiry <= checked + timedelta(minutes=5),
        "COMPOSITE_HISTORICAL_POLICY_ADMISSION_WINDOW_INVALID",
    )


class ControlledScenarioMonthlyPolicyProposal(HashedEligibilityWire):
    product_name: Literal["CompositeMonthlyPolicyProposal"]
    product_version: Literal["v3"]
    proposal_revision: Identifier
    eligibility_policy_version: Identifier
    policy: ResolvedMonthlyPolicy
    attachments: list[EvidenceBinding] = Field(min_length=1, max_length=20)
    proposed_by: Identifier
    proposed_at: Instant
    verification: ControlledScenarioVerification

    @model_validator(mode="after")
    def exact_mapping(self) -> Self:
        require_mapped_policy_proposal(self)
        return self


class ControlledScenarioMonthlyPolicyApproval(HashedEligibilityWire):
    product_name: Literal["CompositeMonthlyPolicyApproval"]
    product_version: Literal["v3"]
    evidence_kind: Literal["VERIFIED_CONTROLLED_SCENARIO_MAPPING"]
    official_activation: Literal["UNAVAILABLE"]
    proposal: ControlledScenarioMonthlyPolicyProposal
    approved_by: Identifier
    approved_at: Instant
    verification: ControlledScenarioVerification

    @model_validator(mode="after")
    def independent_approval(self) -> Self:
        require_mapped_policy_approval(self)
        return self


class ControlledScenarioSubjectPolicyProposal(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectPolicyProposal"]
    product_version: Literal["v3"]
    proposal: ControlledScenarioMonthlyPolicyProposal
    subject: EligibilitySubject
    verification: VerificationReceipt

    @model_validator(mode="after")
    def subject_policy_links(self) -> Self:
        require_mapped_subject_policy(self)
        return self


class ControlledScenarioSubjectPolicyApproval(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectPolicyApproval"]
    product_version: Literal["v3"]
    proposal: ControlledScenarioSubjectPolicyProposal
    approval: ControlledScenarioMonthlyPolicyApproval
    verification: VerificationReceipt

    @model_validator(mode="after")
    def subject_approval_links(self) -> Self:
        _require(self.approval.proposal == self.proposal.proposal, "COMPOSITE_SUBJECT_POLICY_BINDING_MISMATCH")
        _outer_policy_verification(
            self.verification, self.proposal.subject, "approval_content_hash", self.approval.content_hash
        )
        return self


class ControlledScenarioSubjectEvaluationProposal(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectEvaluationProposal"]
    product_version: Literal["v3"]
    evaluation: MonthlyEligibilityEvaluation
    evaluation_kind: Literal["INITIAL"]
    evaluation_revision: Identifier
    observation_binding: DpmCompositeUniverseSourceProduct
    observations: MonthlyEligibilityObservations
    source_assembly_evidence: VerifiedMonthlySourceAssembly | None = None
    policy_approval: ControlledScenarioSubjectPolicyApproval
    operation_verification: ControlledScenarioVerification
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
    def evaluation_links(self) -> Self:
        require_mapped_subject_evaluation(self)
        return self


class ControlledScenarioSubjectEvaluationApproval(HashedEligibilityWire):
    product_name: Literal["CompositeSubjectEvaluationApproval"]
    product_version: Literal["v3"]
    approved_at: Instant
    approved_by: Identifier
    claims_digest: Digest
    evidence_kind: Literal["SYNTHETIC_UNSIGNED"]
    membership_content_hash: Digest
    official_activation: Literal["UNAVAILABLE"]
    proposal: ControlledScenarioSubjectEvaluationProposal
    publication_posture: Literal["NOT_PUBLISHED"]
    universe_content_hash: Digest
    verification: VerificationReceipt
    operation_verification: ControlledScenarioVerification

    @model_validator(mode="after")
    def evaluation_approval(self) -> Self:
        require_mapped_subject_evaluation_approval(self)
        return self


class ControlledScenarioSubjectFinalization(HashedEligibilityWire):
    product_name: Literal["CompositeEligibilityFinalization"]
    product_version: Literal["v4"]
    definition: ControlledScenarioDefinitionV3
    evaluation_approval: ControlledScenarioSubjectEvaluationApproval
    official_activation: Literal["UNAVAILABLE"]
    subject: EligibilitySubject
    verifications: list[VerificationReceipt] = Field(min_length=3, max_length=258)

    @model_validator(mode="after")
    def controlled_finalization(self) -> Self:
        _require(
            all(receipt.posture == "SYNTHETIC_NON_CERTIFYING" for receipt in self.verifications),
            "COMPOSITE_SUBJECT_HISTORICAL_POLICY_POSTURE_UNAVAILABLE",
        )
        require_subject_finalization(self)
        return self


class ControlledScenarioSubjectFinalizationReceipt(HashedEligibilityWire):
    product_name: Literal["CompositeEligibilityFinalizationReceipt"]
    product_version: Literal["v4"]
    completeness: Literal["UNVERIFIED"]
    finalization: ControlledScenarioSubjectFinalization
    membership_content_hash: Digest
    publication_sequence: int = Field(strict=True, ge=1)
    universe_content_hash: Digest

    @model_validator(mode="after")
    def publication_hashes(self) -> Self:
        _equal(
            self,
            self.finalization.evaluation_approval,
            ("membership_content_hash", "universe_content_hash"),
            "COMPOSITE_SUBJECT_PUBLICATION_HASH_MISMATCH",
        )
        return self
