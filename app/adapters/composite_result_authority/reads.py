"""Snapshot-consistent authority reads preserve exact original financial bytes."""

from uuid import UUID

from sqlalchemy import func, select

from app.adapters.composite_result_authority.codec import decision_response, selection_response
from app.adapters.composite_result_authority.context import current_selection
from app.adapters.composite_result_authority.records import DecisionRow, ProposalScopeRow, RevisionRow
from app.adapters.composite_result_authority.vector import absent, captured_vector, custody_refused, original_candidate
from app.models.composite_result_authority import AuthorityReadResponse
from core.errors import APIError


def read_authority(session, principal, scope_id, *, mode, decision_id=None, token=None):
    current = current_selection(session, principal.tenant_id, scope_id)
    if current is None:
        absent()
    decision_id = _resolve_selector(session, principal.tenant_id, current, mode, decision_id, token)
    decision = _decision(session, principal.tenant_id, decision_id, mode, token)
    selection = _selection(session, principal.tenant_id, scope_id, decision)
    retained = captured_vector(session, principal, selection.candidate_id)
    if retained.scope != selection.scope or retained.vector_digest != selection.vector_digest:
        custody_refused()
    return AuthorityReadResponse(
        selection_mode=mode,
        decision=decision,
        selection=selection,
        original=original_candidate(session, principal, selection.candidate_id),
        current_use=current.current_use,
        pending_impact_count=_pending_count(session, principal.tenant_id, scope_id),
    )


def _resolve_selector(session, tenant, current, mode, decision_id, token):
    if mode == "LATEST_APPROVED":
        if decision_id is not None or token is not None:
            unsupported()
        history = session.get(RevisionRow, (tenant, current.scope.scope_id, current.revision))
        return history.decision_id
    if mode == "COMMITTED_TOKEN":
        return _token_decision(token, decision_id)
    _require_exact_selector(mode, decision_id, token)
    return decision_id


def _require_exact_selector(mode, decision_id, token):
    if mode in {"EXACT", "AS_REPORTED"}:
        if decision_id is None or token is not None:
            unsupported()
    else:
        unsupported()


def _decision(session, tenant, decision_id, mode, token):
    row = session.get(DecisionRow, (tenant, str(decision_id)))
    if row is None:
        absent()
    decision = decision_response(row)
    if mode == "COMMITTED_TOKEN" and decision.snapshot_token != token:
        unsupported()
    return decision


def _selection(session, tenant, scope_id, decision):
    matches = [selection for selection in decision.selections if selection.scope.scope_id == scope_id]
    if len(matches) != 1:
        absent()
    selection = matches[0]
    history = session.get(RevisionRow, (tenant, scope_id, selection.revision))
    if history is None or history.decision_id != str(decision.decision_id) or selection_response(history) != selection:
        custody_refused()
    return selection


def unsupported():
    raise APIError(
        status_code=422, detail="Authority selector is unsupported.", error_code="COMPOSITE_AUTHORITY_UNSUPPORTED"
    )


def _token_decision(token, decision_id):
    if decision_id is not None or token is None:
        unsupported()
    parts = token.split(":")
    try:
        if len(parts) != 4 or parts[:2] != ["authority", "v1"] or len(parts[3]) != 64:
            unsupported()
        return UUID(parts[2])
    except ValueError:
        unsupported()


def _pending_count(session, tenant, scope_id):
    return session.scalar(
        select(func.count())
        .select_from(ProposalScopeRow)
        .outerjoin(
            DecisionRow,
            (DecisionRow.tenant_id == ProposalScopeRow.tenant_id)
            & (DecisionRow.proposal_id == ProposalScopeRow.proposal_id),
        )
        .where(
            ProposalScopeRow.tenant_id == tenant,
            ProposalScopeRow.scope_id == scope_id,
            DecisionRow.decision_id.is_(None),
        )
    )
