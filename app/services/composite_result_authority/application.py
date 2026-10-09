"""Verify financial purpose outside owning metadata transactions, then fenced CAS."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from app.ports.composite_result_authority import (
    AuthorityRepository,
    FinancialAuthorityVerifier,
    UnavailableFinancialAuthority,
)
from app.services.composite_result_authority.policy import conflict


def utc_now():
    return datetime.now(UTC)


@dataclass(frozen=True)
class CompositeAuthorityApplication:
    repository: AuthorityRepository
    verifier: FinancialAuthorityVerifier = field(default_factory=UnavailableFinancialAuthority)
    clock: Callable[[], datetime] = utc_now

    def propose(self, principal, request):
        return self.repository.propose(principal, request, self.clock())

    def approve(self, principal, proposal_id, request):
        original = self.repository.existing_approval(principal, proposal_id, request)
        if original is not None:
            return original
        proposal = self.repository.proposal(principal, proposal_id)
        verification = self.verifier.verify(
            proposal=proposal,
            approval_id=str(request.approval_id),
            financial_evidence=request.financial_evidence,
            checker=principal,
            actor=principal,
            now=self.clock(),
        )
        return self.repository.approve(principal, proposal_id, request, verification, self.clock())

    def apply(self, principal, proposal_id, request):
        original = self.repository.existing_decision(principal, proposal_id, request)
        if original is not None:
            return original
        proposal, receipt, evidence, checker = self.repository.approval_material(principal, request.approval_id)
        if str(proposal.proposal_id) != str(proposal_id):
            conflict("Approval does not bind this proposal.")
        verification = self.verifier.verify(
            proposal=proposal,
            approval_id=str(request.approval_id),
            financial_evidence=evidence,
            checker=checker,
            actor=principal,
            now=self.clock(),
        )
        if verification.receipt != receipt:
            conflict("Financial approval content changed.")
        return self.repository.apply(principal, proposal_id, request, verification, self.clock())

    def read(self, principal, scope_id, **selector):
        return self.repository.read(principal, scope_id, **selector)
