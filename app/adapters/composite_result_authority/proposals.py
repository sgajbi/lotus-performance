"""Immutable proposal and exact-content checker approval persistence."""

from sqlalchemy import select

from app.adapters.composite_result_authority.codec import approval_response, digest, proposal_response, wire
from app.adapters.composite_result_authority.context import (
    current_selection,
    dependency_digest,
    fence_scopes,
    overlapping_selections,
    require_retained_vectors,
)
from app.adapters.composite_result_authority.records import ApprovalRow, ProposalRow, ProposalScopeRow, RevisionRow
from app.adapters.composite_result_authority.vector import absent, captured_vector, require_vector_budget
from app.models.composite_result_authority import (
    AuthorityAction,
    AuthorityActor,
    AuthorityImpact,
    AuthorityProposalResponse,
)
from app.services.composite_result_authority.policy import (
    conflict,
    denied,
    require_current_verification,
    validate_transition,
)


def get_proposal(session, principal, proposal_id):
    row = session.get(ProposalRow, (principal.tenant_id, str(proposal_id)))
    if row is None:
        absent()
    result = proposal_response(row)
    require_retained_vectors(session, principal, result)
    return result


def propose(session, principal, request, now):
    request_digest = digest(request)
    existing = _existing_proposal(session, principal, request, request_digest)
    if existing is not None:
        return existing
    require_vector_budget(session, principal, request.targets)
    vectors = [captured_vector(session, principal, target.candidate_id) for target in request.targets]
    if len({vector.scope.scope_id for vector in vectors}) != len(vectors):
        conflict("An atomic bundle cannot select two originals for the same scope.")
    fence_scopes(session, principal, vectors)
    existing = _existing_proposal(session, principal, request, request_digest)
    if existing is not None:
        return existing
    expected = _admit_targets(session, principal, request, vectors)
    overlaps = overlapping_selections(session, principal, vectors)
    result = _new_proposal(request, principal, vectors, expected, overlaps, now)
    session.add(
        ProposalRow(
            tenant_id=principal.tenant_id,
            proposal_id=str(request.proposal_id),
            request_digest=request_digest,
            content_digest=result.proposal_digest,
            response_json=wire(result),
        )
    )
    session.flush()
    observed = {selection.scope.scope_id: selection.revision for selection in overlaps}
    for scope_id, revision in {**expected, **observed}.items():
        session.add(
            ProposalScopeRow(
                tenant_id=principal.tenant_id,
                proposal_id=str(request.proposal_id),
                scope_id=scope_id,
                observed_revision=revision,
            )
        )
    session.flush()
    return result


def _existing_proposal(session, principal, request, request_digest):
    row = session.get(ProposalRow, (principal.tenant_id, str(request.proposal_id)))
    if row is None:
        return None
    if row.request_digest != request_digest:
        conflict("Proposal retry content changed.")
    return get_proposal(session, principal, request.proposal_id)


def _admit_targets(session, principal, request, vectors):
    expected = {}
    for target, vector in zip(request.targets, vectors, strict=True):
        previous = current_selection(session, principal.tenant_id, vector.scope.scope_id)
        validate_transition(request.action, vector, target.expected_revision, previous, applying=False)
        expected[vector.scope.scope_id] = target.expected_revision
        if request.action == AuthorityAction.RESTORE_PRIOR:
            known = session.scalar(
                select(RevisionRow.revision)
                .where(
                    RevisionRow.tenant_id == principal.tenant_id,
                    RevisionRow.scope_id == vector.scope.scope_id,
                    RevisionRow.candidate_id == str(vector.candidate_id),
                )
                .limit(1)
            )
            if known is None:
                conflict("Restore requires an exact previously selected original.")
    return expected


def _new_proposal(request, principal, vectors, expected, overlaps, now):
    result = AuthorityProposalResponse(
        proposal_id=request.proposal_id,
        proposal_digest="sha256:" + "0" * 64,
        maker_subject=principal.subject,
        maker=actor_receipt(principal),
        action=request.action,
        targets=vectors,
        expected_revisions=expected,
        bundle_id=request.bundle_id,
        reason=request.reason,
        evidence_refs=request.evidence_refs,
        created_at_utc=now,
        impact=AuthorityImpact(
            affected_scope_ids=[selection.scope.scope_id for selection in overlaps],
            dependency_revision_digest=dependency_digest(overlaps),
        ),
    )
    return result.model_copy(
        update={"proposal_digest": digest(result.model_dump(mode="json", exclude={"proposal_digest"}))}
    )


def get_approval(session, principal, approval_id):
    row = session.get(ApprovalRow, (principal.tenant_id, str(approval_id)))
    if row is None:
        absent()
    receipt = approval_response(row)
    proposal = get_proposal(session, principal, row.proposal_id)
    if receipt.proposal_digest != proposal.proposal_digest:
        denied()
    return row, receipt, proposal


def existing_approval(session, principal, proposal_id, request):
    row = session.get(ApprovalRow, (principal.tenant_id, str(request.approval_id)))
    if row is None:
        return None
    content = digest({"request": request.model_dump(mode="json"), "checker": principal.subject})
    if row.request_digest != content or row.proposal_id != str(proposal_id):
        conflict("Approval retry content changed.")
    return get_approval(session, principal, request.approval_id)[1]


def approve(session, principal, proposal_id, request, verification, now):
    existing = existing_approval(session, principal, proposal_id, request)
    if existing is not None:
        return existing
    proposal = get_proposal(session, principal, proposal_id)
    fence_scopes(session, principal, proposal.targets)
    existing = existing_approval(session, principal, proposal_id, request)
    if existing is not None:
        return existing
    if (
        session.scalar(
            select(ApprovalRow.approval_id).where(
                ApprovalRow.tenant_id == principal.tenant_id,
                ApprovalRow.proposal_id == str(proposal_id),
            )
        )
        is not None
    ):
        conflict("The proposal already has its immutable approval.")
    for vector in proposal.targets:
        validate_transition(
            proposal.action,
            vector,
            proposal.expected_revisions[vector.scope.scope_id],
            current_selection(session, principal.tenant_id, vector.scope.scope_id),
            applying=False,
        )
    if (
        dependency_digest(overlapping_selections(session, principal, proposal.targets))
        != proposal.impact.dependency_revision_digest
    ):
        conflict("Impact preview changed; obtain a new exact proposal.")
    require_current_verification(verification, proposal.proposal_digest, now)
    if verification.receipt.checker_subject != principal.subject:
        denied()
    checker = {
        "principal_kind": principal.principal_kind,
        "subject": principal.subject,
        "tenant_id": principal.tenant_id,
        "capabilities": sorted(principal.capabilities),
        "portfolio_scope": sorted(principal.portfolio_scope),
        "credential_id": principal.credential_id,
        "delegated_actor": principal.delegated_actor,
    }
    session.add(
        ApprovalRow(
            tenant_id=principal.tenant_id,
            approval_id=str(request.approval_id),
            proposal_id=str(proposal_id),
            request_digest=digest({"request": request.model_dump(mode="json"), "checker": principal.subject}),
            response_json=wire(verification.receipt),
            financial_evidence=request.financial_evidence,
            checker_json=wire(checker),
        )
    )
    session.flush()
    return verification.receipt


def actor_receipt(principal):
    return AuthorityActor(
        subject=principal.subject,
        principal_kind=principal.principal_kind,
        credential_id=principal.credential_id,
        delegated_actor=principal.delegated_actor,
    )
