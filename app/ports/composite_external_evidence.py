"""Source and approval ports owned independently from provider registration."""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import StrictInt

from app.models.composite_authority import (
    AuthoritySelection,
    EvidenceBinding,
    ManageCompositeDefinitionV2,
    MemberIdentity,
)
from app.models.composite_eligibility_evidence import (
    SubjectFinalizationReceipt,
    VerificationReceipt,
    VerificationRequest,
    decode_eligibility_receipt,
)
from app.models.composite_materialization import CompositeMaterializationCommand
from app.models.composite_monthly_eligibility_evidence import CompositeMonthlyEligibilityPublicationReceipt


@dataclass(frozen=True)
class CompositeApprovalRequest:
    purpose: str
    tenant_id: str
    composite_id: str
    definition_version: str
    binding: EvidenceBinding | None
    effective_from: str
    effective_to: str
    definition: ManageCompositeDefinitionV2
    command: CompositeMaterializationCommand
    universe_digest: str
    expected_members: tuple[str, ...]
    method_evidence_wire: dict[str, Any] | None = None
    eligibility_evidence_wire: dict[str, Any] | None = None
    authority_claims_digest: str | None = None


class CompositeApprovalVerificationPort(Protocol):
    def verify(self, request: CompositeApprovalRequest) -> bool: ...


class CompositeProviderObservationPort(Protocol):
    def read(self, *, tenant_id: str, selection: AuthoritySelection) -> dict[str, Any]: ...


class UnavailableApprovalVerification:
    def verify(self, request: CompositeApprovalRequest) -> bool:
        return False


def authority_approval_verifier() -> CompositeApprovalVerificationPort:
    return UnavailableApprovalVerification()


def eligibility_approval_verifier() -> CompositeApprovalVerificationPort:
    return UnavailableApprovalVerification()


def method_approval_verifier() -> CompositeApprovalVerificationPort:
    return UnavailableApprovalVerification()


# Additive preparation ports. Legacy runtime callers above remain unchanged.


@dataclass(frozen=True)
class UnavailableCompositeEvidence:
    """No independently resolved or verified evidence exists."""


@dataclass(frozen=True)
class EligibilityResolutionRequest:
    tenant_id: str
    composite_id: str
    definition_version: str
    evaluation_binding: EvidenceBinding
    membership_binding: EvidenceBinding
    universe_binding: EvidenceBinding
    source_cut_id: str
    effective_from: str
    effective_to: str
    member_identities: tuple[MemberIdentity, ...]


@dataclass(frozen=True)
class PublishedEligibilityEvidence:
    """A resolver-owned published graph join, never a staged approval or boolean.

    The configured adapter obtains the producer's transactional publication join
    and digest-checks separately read canonical products before returning these pins.
    This port result is not an additional persisted lifecycle product.
    """

    receipt: SubjectFinalizationReceipt | CompositeMonthlyEligibilityPublicationReceipt
    membership_binding: EvidenceBinding
    universe_binding: EvidenceBinding
    source_cut_id: str
    publication_sequence: StrictInt
    member_identities: tuple[MemberIdentity, ...]


class CompositeEligibilityResolutionPort(Protocol):
    def resolve(
        self, request: EligibilityResolutionRequest
    ) -> PublishedEligibilityEvidence | UnavailableCompositeEvidence: ...


@dataclass(frozen=True)
class CompositeVerificationExpectation:
    """Expected trust metadata supplied by the verifier's admitted configuration."""

    request: VerificationRequest
    verifier_id: str
    issuer_id: str
    artifact_revision: str
    artifact_digest: str


@dataclass(frozen=True)
class VerifiedCompositeEvidence:
    """Return only after independent verifier admission; decoding is insufficient."""

    receipt: VerificationReceipt
    expectation: CompositeVerificationExpectation | None = None


class CompositeReceiptVerificationPort(Protocol):
    def verify(self, request: VerificationRequest) -> VerifiedCompositeEvidence | UnavailableCompositeEvidence: ...


class UnavailableEligibilityResolution:
    def resolve(self, request: EligibilityResolutionRequest) -> UnavailableCompositeEvidence:
        return UnavailableCompositeEvidence()


class UnavailableReceiptVerification:
    def verify(self, request: VerificationRequest) -> UnavailableCompositeEvidence:
        return UnavailableCompositeEvidence()


def composite_eligibility_resolver() -> CompositeEligibilityResolutionPort:
    return UnavailableEligibilityResolution()


def composite_receipt_verifier() -> CompositeReceiptVerificationPort:
    from app.core.config import get_settings

    wire = get_settings().COMPOSITE_RECEIPT_VERIFIER_CONFIG_JSON
    if wire:
        from app.adapters.composite_receipt_verification.configuration import decode_receipt_verifier_configuration
        from app.adapters.composite_receipt_verification.transport import ConfiguredCompositeReceiptVerifier

        try:
            return ConfiguredCompositeReceiptVerifier(decode_receipt_verifier_configuration(wire))
        except (ValueError, TypeError):
            return UnavailableReceiptVerification()
    return UnavailableReceiptVerification()


def _evidence_require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def admit_resolved_eligibility(
    request: EligibilityResolutionRequest,
    result: PublishedEligibilityEvidence | UnavailableCompositeEvidence,
) -> SubjectFinalizationReceipt | CompositeMonthlyEligibilityPublicationReceipt:
    """Validate a typed resolver result against consumer-owned immutable pins."""
    if not isinstance(result, PublishedEligibilityEvidence):
        raise ValueError("COMPOSITE_ELIGIBILITY_PUBLISHED_CUSTODY_UNAVAILABLE")
    receipt = decode_eligibility_receipt(result.receipt.model_dump_json())
    if isinstance(receipt, CompositeMonthlyEligibilityPublicationReceipt):
        _admit_monthly_resolution(request, result, receipt)
        return receipt
    subject = receipt.finalization.subject
    _evidence_require(
        (subject.tenant_id, subject.composite_id, subject.definition_version)
        == (request.tenant_id, request.composite_id, request.definition_version),
        "COMPOSITE_ELIGIBILITY_RESOLUTION_SCOPE_MISMATCH",
    )
    _evidence_require(
        (subject.universe.coverage_from, subject.universe.coverage_to)
        == (request.effective_from, request.effective_to),
        "COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH",
    )
    _evidence_require(
        receipt.finalization.definition.source_authority.payload.eligibility_evaluation_binding
        == request.evaluation_binding,
        "COMPOSITE_ELIGIBILITY_RESOLUTION_BINDING_MISMATCH",
    )
    _published_pins(request, result, receipt)
    return receipt


def _admit_monthly_resolution(request, result, receipt: CompositeMonthlyEligibilityPublicationReceipt) -> None:
    definition = receipt.definition
    approval = receipt.approval
    proposal = approval.proposal
    from app.models.composite_eligibility_evidence import _month_window

    _evidence_require(
        (definition.tenant_id, definition.composite_id, definition.definition_version)
        == (request.tenant_id, request.composite_id, request.definition_version),
        "COMPOSITE_ELIGIBILITY_RESOLUTION_SCOPE_MISMATCH",
    )
    _evidence_require(
        _month_window(proposal.observations.month) == (request.effective_from, request.effective_to),
        "COMPOSITE_ELIGIBILITY_RESOLUTION_WINDOW_MISMATCH",
    )
    _evidence_require(
        request.evaluation_binding
        == EvidenceBinding(
            product_name=approval.product_name,
            product_version=approval.product_version,
            revision=proposal.evaluation_revision,
            digest=approval.content_hash,
        ),
        "COMPOSITE_ELIGIBILITY_RESOLUTION_BINDING_MISMATCH",
    )
    _evidence_require(
        (result.membership_binding, result.universe_binding)
        == (request.membership_binding, request.universe_binding)
        == (receipt.membership_binding, receipt.universe_binding),
        "COMPOSITE_ELIGIBILITY_PUBLICATION_BINDING_MISMATCH",
    )
    _evidence_require(
        result.source_cut_id == request.source_cut_id == receipt.source_cut_id,
        "COMPOSITE_ELIGIBILITY_PUBLICATION_CUT_MISMATCH",
    )
    _evidence_require(
        result.member_identities
        == request.member_identities
        == tuple(definition.source_authority.payload.member_identities),
        "COMPOSITE_ELIGIBILITY_PUBLICATION_MEMBER_MISMATCH",
    )
    _evidence_require(
        type(result.publication_sequence) is int and result.publication_sequence == receipt.publication_sequence,
        "COMPOSITE_ELIGIBILITY_PUBLICATION_SEQUENCE_MISMATCH",
    )


def _published_pins(
    request: EligibilityResolutionRequest,
    result: PublishedEligibilityEvidence,
    receipt: SubjectFinalizationReceipt,
) -> None:
    approval = receipt.finalization.evaluation_approval
    _evidence_require(
        (result.membership_binding, result.universe_binding) == (request.membership_binding, request.universe_binding),
        "COMPOSITE_ELIGIBILITY_PUBLICATION_BINDING_MISMATCH",
    )
    _evidence_require(
        (
            result.membership_binding.product_name,
            result.membership_binding.revision,
            result.membership_binding.digest,
            result.universe_binding.product_name,
            result.universe_binding.revision,
            result.universe_binding.digest,
        )
        == (
            "CompositeMembership",
            approval.proposal.target_membership_revision,
            receipt.membership_content_hash,
            "CompositeUniverseAttestation",
            approval.proposal.evaluation_revision,
            receipt.universe_content_hash,
        ),
        "COMPOSITE_ELIGIBILITY_PUBLICATION_BINDING_MISMATCH",
    )
    _evidence_require(
        result.source_cut_id == request.source_cut_id == receipt.finalization.subject.universe.source_cut_id,
        "COMPOSITE_ELIGIBILITY_PUBLICATION_CUT_MISMATCH",
    )
    _evidence_require(
        result.member_identities == request.member_identities == tuple(receipt.finalization.subject.universe.members),
        "COMPOSITE_ELIGIBILITY_PUBLICATION_MEMBER_MISMATCH",
    )
    _evidence_require(
        type(result.publication_sequence) is int and result.publication_sequence == receipt.publication_sequence,
        "COMPOSITE_ELIGIBILITY_PUBLICATION_SEQUENCE_MISMATCH",
    )


def admit_verified_receipt(
    expectation: CompositeVerificationExpectation,
    result: VerifiedCompositeEvidence | UnavailableCompositeEvidence,
    *,
    allow_synthetic: bool = False,
) -> VerificationReceipt:
    """Match independently verified evidence; synthetic success is non-certifying."""
    if not isinstance(result, VerifiedCompositeEvidence):
        raise ValueError("COMPOSITE_RECEIPT_VERIFICATION_UNAVAILABLE")
    receipt = VerificationReceipt.model_validate(result.receipt.model_dump())
    _evidence_require(receipt.request == expectation.request, "COMPOSITE_RECEIPT_VERIFICATION_REQUEST_MISMATCH")
    _evidence_require(
        (receipt.verifier_id, receipt.issuer_id, receipt.artifact_revision, receipt.artifact_digest)
        == (expectation.verifier_id, expectation.issuer_id, expectation.artifact_revision, expectation.artifact_digest),
        "COMPOSITE_RECEIPT_VERIFICATION_ARTIFACT_MISMATCH",
    )
    # This source-preparation slice implements no qualified trust configuration.
    _evidence_require(
        allow_synthetic and receipt.posture == "SYNTHETIC_NON_CERTIFYING",
        "COMPOSITE_RECEIPT_QUALIFIED_VERIFICATION_UNAVAILABLE",
    )
    return receipt
