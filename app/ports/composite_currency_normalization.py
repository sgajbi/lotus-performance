"""Configured source and independent verification seams; no qualified default."""

from dataclasses import dataclass
from typing import Any, Protocol

from app.models.composite_authority import EvidenceBinding
from app.models.composite_currency_normalization import CompositeFXNormalizationSource, CompositeFXVerificationReceipt
from app.ports.composite_external_evidence import UnavailableCompositeEvidence


@dataclass(frozen=True)
class CompositeFXResolutionRequest:
    tenant_id: str
    composite_id: str
    binding: EvidenceBinding
    definition_content_hash: str
    membership_content_hash: str
    attestation_content_hash: str
    source_cut_id: str
    period_start: str
    period_end: str
    reporting_currency: str
    return_view: str
    expected_members: tuple[str, ...]


@dataclass(frozen=True)
class CompositeFXVerificationRequest:
    resolution: CompositeFXResolutionRequest
    source: CompositeFXNormalizationSource
    source_digest: str
    method_digest: str


@dataclass(frozen=True)
class CompositeFXVerificationExpectation:
    """Exact trusted pins returned by verifier configuration, never caller fields."""

    request: CompositeFXVerificationRequest
    verifier_id: str
    issuer_id: str
    artifact_revision: str
    artifact_digest: str


@dataclass(frozen=True)
class VerifiedCompositeFXEvidence:
    expectation: CompositeFXVerificationExpectation
    verification_receipt: CompositeFXVerificationReceipt


class CompositeFXSourceResolutionPort(Protocol):
    def resolve(self, request: CompositeFXResolutionRequest) -> dict[str, Any] | UnavailableCompositeEvidence: ...


class CompositeFXReceiptVerificationPort(Protocol):
    def verify(
        self, request: CompositeFXVerificationRequest
    ) -> VerifiedCompositeFXEvidence | UnavailableCompositeEvidence: ...


class UnavailableCompositeFXSource:
    def resolve(self, request: CompositeFXResolutionRequest) -> UnavailableCompositeEvidence:
        return UnavailableCompositeEvidence()


class UnavailableCompositeFXVerification:
    def verify(self, request: CompositeFXVerificationRequest) -> UnavailableCompositeEvidence:
        return UnavailableCompositeEvidence()


def composite_fx_source_resolver() -> CompositeFXSourceResolutionPort:
    return UnavailableCompositeFXSource()


def composite_fx_receipt_verifier() -> CompositeFXReceiptVerificationPort:
    return UnavailableCompositeFXVerification()
