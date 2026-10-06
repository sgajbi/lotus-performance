"""Source and approval ports owned independently from provider registration."""

from dataclasses import dataclass
from typing import Any, Protocol

from app.models.composite_authority import AuthoritySelection, EvidenceBinding, ManageCompositeDefinitionV2
from app.models.composite_materialization import CompositeMaterializationCommand


@dataclass(frozen=True)
class CompositeApprovalRequest:
    purpose: str
    tenant_id: str
    composite_id: str
    definition_version: str
    binding: EvidenceBinding
    effective_from: str
    effective_to: str
    definition: ManageCompositeDefinitionV2
    command: CompositeMaterializationCommand
    universe_digest: str
    expected_members: tuple[str, ...]


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
