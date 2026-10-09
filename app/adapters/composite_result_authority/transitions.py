"""Atomic whole-vector transitions and dependent projection invalidation."""

from sqlalchemy import select, update

from app.adapters.composite_result_authority.codec import decision_response, digest, snapshot_token, wire
from app.adapters.composite_result_authority.context import (
    current_selection,
    dependency_digest,
    fence_scopes,
    overlapping_selections,
    require_retained_vectors,
)
from app.adapters.composite_result_authority.proposals import actor_receipt, get_approval, get_proposal
from app.adapters.composite_result_authority.records import DecisionRow, RevisionRow, ScopeRow
from app.adapters.composite_result_authority.vector import captured_vector
from app.models.composite_result_authority import AuthorityAction, AuthorityDecisionResponse
from app.services.composite_result_authority.policy import (
    REPLACEMENTS,
    changed_dependency,
    conflict,
    next_selection,
    require_current_verification,
    validate_transition,
)


def existing_decision(session, principal, proposal_id, request):
    row = session.get(DecisionRow, (principal.tenant_id, str(request.decision_id)))
    if row is None:
        return None
    if row.request_digest != digest(request) or row.proposal_id != str(proposal_id):
        conflict("Decision retry content changed.")
    require_retained_vectors(session, principal, get_proposal(session, principal, proposal_id))
    return decision_response(row)


def apply_decision(session, principal, proposal_id, request, verification, now):
    proposal = get_proposal(session, principal, proposal_id)
    fence_scopes(session, principal, proposal.targets)
    previous_receipt = existing_decision(session, principal, proposal_id, request)
    if previous_receipt is not None:
        return previous_receipt
    if (
        session.scalar(
            select(DecisionRow.decision_id).where(
                DecisionRow.tenant_id == principal.tenant_id,
                DecisionRow.proposal_id == str(proposal_id),
            )
        )
        is not None
    ):
        conflict("The proposal already has its immutable decision.")
    _, approval, approved_proposal = get_approval(session, principal, request.approval_id)
    if approved_proposal != proposal or approval != verification.receipt:
        conflict("Approval does not bind this exact proposal.")
    require_current_verification(verification, proposal.proposal_digest, now)
    overlaps = overlapping_selections(session, principal, proposal.targets)
    if dependency_digest(overlaps) != proposal.impact.dependency_revision_digest:
        conflict("Impact preview changed; obtain a new exact proposal and approval.")
    _require_bundle_closure(session, principal, proposal, overlaps)
    selections, prior = _target_transitions(session, principal, proposal)
    propagated = _dependent_transitions(session, principal, proposal, overlaps)
    selections.extend(propagated)
    prior.update({selection.scope.scope_id: selection.revision - 1 for selection in propagated})
    receipt = _receipt(request, principal, proposal, selections, propagated, now)
    _persist_decision(session, principal, proposal, request, receipt, prior)
    return receipt


def _require_bundle_closure(session, principal, proposal, overlaps):
    target_ids = {target.scope.scope_id for target in proposal.targets}
    ids = {str(selection.bundle_id) for selection in overlaps if selection.bundle_id is not None}
    if proposal.bundle_id is not None:
        ids.add(str(proposal.bundle_id))
    for bundle_id in ids:
        members = set(
            session.scalars(
                select(ScopeRow.scope_id).where(
                    ScopeRow.tenant_id == principal.tenant_id,
                    ScopeRow.bundle_id == bundle_id,
                )
            )
        )
        if not members:
            continue
        _validate_bundle_members(target_ids, members, str(proposal.bundle_id), bundle_id)


def _validate_bundle_members(target_ids, members, requested_bundle, existing_bundle):
    if target_ids & members and (not members <= target_ids or requested_bundle != existing_bundle):
        conflict("An atomic bundle requires its exact complete member closure.")
    if requested_bundle == existing_bundle and members != target_ids:
        conflict("An existing atomic bundle cannot silently change membership.")


def _target_transitions(session, principal, proposal):
    selections, prior = [], {}
    for vector in proposal.targets:
        scope_id = vector.scope.scope_id
        previous = current_selection(session, principal.tenant_id, scope_id)
        expected = proposal.expected_revisions[scope_id]
        validate_transition(proposal.action, vector, expected, previous)
        selections.append(next_selection(proposal.action, vector, previous, proposal.bundle_id))
        prior[scope_id] = expected
    for index, left in enumerate(proposal.targets):
        for right in proposal.targets[index + 1 :]:
            if left.scope.base_id == right.scope.base_id and changed_dependency(left, right):
                conflict("An atomic bundle contains inconsistent overlapping dependencies.")
    return selections, prior


def _dependent_transitions(session, principal, proposal, overlaps):
    target_ids = {vector.scope.scope_id for vector in proposal.targets}
    propagated = []
    for previous in overlaps:
        if previous.scope.scope_id in target_ids:
            continue
        old = captured_vector(session, principal, previous.candidate_id)
        changed = _dependency_changed(old, proposal.targets)
        result = _propagate_dependency(previous, proposal.action, changed)
        if result is not None:
            propagated.append(result)
    return propagated


def _dependency_changed(old, targets):
    return any(vector.scope.base_id == old.scope.base_id and changed_dependency(old, vector) for vector in targets)


def _propagate_dependency(previous, action, changed):
    withdrawing = action == AuthorityAction.WITHDRAW_CURRENT_USE
    if not changed and not withdrawing:
        return None
    _require_dependency_mutable(previous, action, changed)
    state = "WITHDRAWN" if withdrawing else "STALE"
    return previous.model_copy(update={"revision": previous.revision + 1, "current_use": state})


def _require_dependency_mutable(previous, action, changed):
    if previous.bundle_id is not None:
        conflict("A dependent atomic bundle requires complete approved replacement.")
    if changed and previous.frozen:
        conflict("An overlapping frozen dependency requires its exact approved reopen.")
    if changed and action not in REPLACEMENTS:
        conflict("Protection cannot change an overlapping financial dependency.")


def _receipt(request, principal, proposal, selections, propagated, now):
    receipt = AuthorityDecisionResponse(
        decision_id=request.decision_id,
        proposal_id=proposal.proposal_id,
        approval_id=request.approval_id,
        action=proposal.action,
        actor=actor_receipt(principal),
        selections=sorted(selections, key=lambda selection: selection.scope.scope_id),
        stale_scope_ids=sorted(
            selection.scope.scope_id for selection in propagated if selection.current_use == "STALE"
        ),
        snapshot_token=str(request.decision_id),
        recorded_at_utc=now,
    )
    return receipt.model_copy(update={"snapshot_token": snapshot_token(receipt)})


def _persist_decision(session, principal, proposal, request, receipt, prior):
    tenant = principal.tenant_id
    session.add(
        DecisionRow(
            tenant_id=tenant,
            decision_id=str(request.decision_id),
            proposal_id=str(proposal.proposal_id),
            approval_id=str(request.approval_id),
            request_digest=digest(request),
            receipt_digest=digest(receipt),
            response_json=wire(receipt),
        )
    )
    session.flush()
    for selection in receipt.selections:
        session.add(
            RevisionRow(
                tenant_id=tenant,
                scope_id=selection.scope.scope_id,
                revision=selection.revision,
                decision_id=str(request.decision_id),
                candidate_id=str(selection.candidate_id),
                selection_json=wire(selection),
            )
        )
    session.flush()
    for selection in receipt.selections:
        _move_pointer(session, tenant, selection, prior[selection.scope.scope_id])
    session.flush()


def _move_pointer(session, tenant, selection, expected):
    bundle_id = str(selection.bundle_id) if selection.bundle_id else None
    if expected == 0:
        session.add(
            ScopeRow(
                tenant_id=tenant,
                scope_id=selection.scope.scope_id,
                base_id=selection.scope.base_id,
                period_start=selection.scope.period_start,
                period_end=selection.scope.period_end,
                revision=selection.revision,
                bundle_id=bundle_id,
            )
        )
        return
    result = session.execute(
        update(ScopeRow)
        .where(
            ScopeRow.tenant_id == tenant,
            ScopeRow.scope_id == selection.scope.scope_id,
            ScopeRow.revision == expected,
        )
        .values(revision=selection.revision, bundle_id=bundle_id)
    )
    if result.rowcount != 1:
        conflict("Authority compare-and-swap lost its expected revision.")
