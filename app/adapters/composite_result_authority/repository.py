"""Owning Composite transaction facade; verification never runs inside its sessions."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.composite_principal_credentials import VerifiedCompositePrincipal
from app.adapters.composite_result_authority.context import owner_session
from app.adapters.composite_result_authority.proposals import (
    approve,
    existing_approval,
    get_approval,
    get_proposal,
    propose,
)
from app.adapters.composite_result_authority.reads import read_authority
from app.adapters.composite_result_authority.transitions import apply_decision, existing_decision
from app.adapters.composite_result_authority.vector import custody_refused

RetainedIdentifier = Annotated[str, Field(strict=True, min_length=1, max_length=128)]


class CheckerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    principal_kind: Literal["user", "service", "delegated"]
    subject: RetainedIdentifier
    tenant_id: RetainedIdentifier
    credential_id: RetainedIdentifier
    delegated_actor: RetainedIdentifier | None
    capabilities: list[RetainedIdentifier]
    portfolio_scope: list[RetainedIdentifier]


def _retained_checker(row, receipt, tenant):
    try:
        value = CheckerSnapshot.model_validate_json(row.checker_json).model_dump()
        value["capabilities"] = frozenset(value["capabilities"])
        value["portfolio_scope"] = frozenset(value["portfolio_scope"])
        checker = VerifiedCompositePrincipal(**value)
        if checker.subject != receipt.checker_subject or checker.tenant_id != tenant:
            custody_refused()
        return checker
    except (TypeError, ValueError, KeyError):
        custody_refused()


@dataclass(frozen=True)
class CompositeAuthorityRepository:
    owner: object
    results: object

    def propose(self, principal, request, now):
        with owner_session(self.owner, self.results, principal, write=True) as session:
            return propose(session, principal, request, now)

    def proposal(self, principal, proposal_id):
        with owner_session(self.owner, self.results, principal, write=False) as session:
            return get_proposal(session, principal, proposal_id)

    def existing_approval(self, principal, proposal_id, request):
        with owner_session(self.owner, self.results, principal, write=False) as session:
            return existing_approval(session, principal, proposal_id, request)

    def approve(self, principal, proposal_id, request, verification, now):
        with owner_session(self.owner, self.results, principal, write=True) as session:
            return approve(session, principal, proposal_id, request, verification, now)

    def existing_decision(self, principal, proposal_id, request):
        with owner_session(self.owner, self.results, principal, write=False) as session:
            return existing_decision(session, principal, proposal_id, request)

    def approval_material(self, principal, approval_id):
        with owner_session(self.owner, self.results, principal, write=False) as session:
            row, receipt, proposal = get_approval(session, principal, approval_id)
            return proposal, receipt, row.financial_evidence, _retained_checker(row, receipt, principal.tenant_id)

    def apply(self, principal, proposal_id, request, verification, now):
        with owner_session(self.owner, self.results, principal, write=True) as session:
            return apply_decision(session, principal, proposal_id, request, verification, now)

    def read(self, principal, scope_id, **selector):
        with owner_session(self.owner, self.results, principal, write=False) as session:
            return read_authority(session, principal, scope_id, **selector)
