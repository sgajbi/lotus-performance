"""Signed, explicitly non-certifying financial-purpose conformance admission."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

from app.adapters.composite_principal_credentials import (
    CredentialTrust,
    PrincipalAuthority,
    PrincipalDenial,
    verify_composite_credential,
)
from app.models.composite_authority import authority_digest
from app.models.composite_result_authority import AuthorityApprovalResponse
from app.ports.composite_result_authority import VerifiedFinancialEvidence
from app.services.composite_result_authority.policy import denied


@dataclass(frozen=True)
class SignedFinancialAuthorityVerifier:
    """No institutional/qualified posture or production activation option exists."""

    trust: CredentialTrust
    principal_authority: PrincipalAuthority
    policy_digest: str
    canonical_identities: Mapping[str, str]
    permitted_actors: frozenset[str]

    def _current_grants(self, principal):
        authority = self.principal_authority
        try:
            admitted = not authority.revoked(principal.subject, principal.credential_id) and authority.tenant_member(
                principal.subject, principal.tenant_id
            )
            grants = authority.grants(principal.subject, principal.tenant_id)
            capabilities, portfolios = grants.capabilities, grants.portfolio_scope
            if principal.delegated_actor is not None:
                application = authority.application_grants(principal.delegated_actor, principal.tenant_id)
                capabilities &= application.capabilities
                portfolios &= application.portfolio_scope
        except Exception:
            denied()
        if (
            not admitted
            or "operations.runtime.manage" not in capabilities
            or not principal.portfolio_scope <= portfolios
        ):
            denied()

    def verify(self, *, proposal, approval_id, financial_evidence, checker, actor, now):
        self._current_grants(checker)
        self._current_grants(actor)
        if actor.subject not in self.permitted_actors or actor.tenant_id != checker.tenant_id:
            denied()
        claims = verify_composite_credential(financial_evidence, trust=self.trust, now=now)
        if isinstance(claims, PrincipalDenial):
            denied()
        makers = {proposal.maker_subject}
        for target in proposal.targets:
            makers.update(target.maker_subjects)
        canonical = self._independent_checker(checker, makers)
        expected = {
            "purpose": "COMPOSITE_FINANCIAL_RESULT_ACTION",
            "qualification": "SYNTHETIC_NON_CERTIFYING",
            "tenant": checker.tenant_id,
            "sub": checker.subject,
            "proposal_digest": proposal.proposal_digest,
            "approval_id": approval_id,
            "action": proposal.action.value,
            "policy_digest": self.policy_digest,
            "canonical_checker": canonical,
            "canonical_makers": sorted({self.canonical_identities[maker] for maker in makers}),
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            denied()
        receipt = AuthorityApprovalResponse(
            approval_id=approval_id,
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.proposal_digest,
            checker_subject=checker.subject,
            canonical_checker=canonical,
            policy_digest=self.policy_digest,
            evidence_digest=authority_digest({"financial_evidence": financial_evidence}),
            valid_until=datetime.fromtimestamp(claims["exp"], UTC),
        )
        return VerifiedFinancialEvidence(receipt, proposal.proposal_digest, now)

    def _independent_checker(self, checker, makers):
        subjects = makers | {checker.subject}
        if not subjects <= self.canonical_identities.keys():
            denied()
        canonical = self.canonical_identities[checker.subject]
        if canonical in {self.canonical_identities[maker] for maker in makers}:
            denied()
        if checker.subject in makers or checker.principal_kind == "service":
            denied()
        return canonical
