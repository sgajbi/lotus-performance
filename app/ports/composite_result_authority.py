"""Purpose-specific financial verification; no source receipt grants this purpose."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.models.composite_result_authority import AuthorityApprovalResponse, AuthorityProposalResponse
from core.errors import APIError


@dataclass(frozen=True)
class VerifiedFinancialEvidence:
    receipt: AuthorityApprovalResponse
    proposal_digest: str
    checked_at: datetime


class FinancialAuthorityVerifier(Protocol):
    def verify(
        self,
        *,
        proposal: AuthorityProposalResponse,
        approval_id: str,
        financial_evidence: str,
        checker: VerifiedCompositePrincipal,
        actor: VerifiedCompositePrincipal,
        now: datetime,
    ) -> VerifiedFinancialEvidence: ...


class AuthorityRepository(Protocol):
    def propose(self, principal, request, now): ...
    def proposal(self, principal, proposal_id): ...
    def existing_approval(self, principal, proposal_id, request): ...
    def approve(self, principal, proposal_id, request, verification, now): ...
    def existing_decision(self, principal, proposal_id, request): ...
    def approval_material(self, principal, approval_id): ...
    def apply(self, principal, proposal_id, request, verification, now): ...
    def read(self, principal, scope_id, **selector): ...


class UnavailableFinancialAuthority:
    def verify(self, **kwargs) -> VerifiedFinancialEvidence:
        raise APIError(
            status_code=503,
            detail="Financial-result authority is unavailable.",
            error_code="COMPOSITE_FINANCIAL_AUTHORITY_UNAVAILABLE",
        )
