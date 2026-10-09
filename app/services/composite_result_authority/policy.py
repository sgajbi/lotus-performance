"""One state/overlap policy shared by proposal, application and rehydration."""

from datetime import datetime

from app.models.composite_result_authority import AuthorityAction, AuthoritySelection, AuthorityVector
from core.errors import APIConflictError, APIError

REPLACEMENTS = frozenset({AuthorityAction.SELECT_INITIAL, AuthorityAction.REPLACE, AuthorityAction.RESTORE_PRIOR})


def conflict(detail: str):
    raise APIConflictError(detail, error_code="COMPOSITE_AUTHORITY_CONFLICT")


def denied():
    raise APIError(
        status_code=403, detail="Financial action is refused.", error_code="COMPOSITE_FINANCIAL_ACTION_DENIED"
    )


def validate_selection(selection: AuthoritySelection) -> AuthoritySelection:
    if selection.frozen and selection.current_use == "STALE":
        conflict("A frozen selection cannot be silently staled.")
    return selection


def validate_transition(action, vector, expected_revision, previous, *, applying=True):
    if previous is None:
        if expected_revision != 0 or action != AuthorityAction.SELECT_INITIAL:
            conflict("Initial selection requires an absent scope and revision zero.")
        return
    validate_selection(previous)
    if expected_revision != previous.revision or action == AuthorityAction.SELECT_INITIAL:
        conflict("Authority revision changed; reload and obtain exact approval.")
    if action not in REPLACEMENTS and vector.vector_digest != previous.vector_digest:
        conflict("Protection actions must bind the exact selected original vector.")
    _require_action_state(action, previous, applying)


def _require_action_state(action, previous, applying):
    if applying and action in REPLACEMENTS and previous.frozen:
        conflict("Frozen authority requires an independently approved reopen.")
    _require_protection_state(action, previous)


def _require_protection_state(action, previous):
    if action == AuthorityAction.FREEZE and (previous.frozen or previous.current_use != "SELECTED"):
        conflict("Only an open current selection can be frozen.")
    if action == AuthorityAction.REOPEN and not previous.frozen:
        conflict("Only a frozen selection can be reopened.")
    if action == AuthorityAction.WITHDRAW_CURRENT_USE and previous.current_use == "WITHDRAWN":
        conflict("The selected authority is already withdrawn.")


def changed_dependency(old: AuthorityVector, new: AuthorityVector) -> bool:
    changed = False
    for left in old.windows:
        for right in new.windows:
            overlap = left.period_start <= right.period_end and right.period_start <= left.period_end
            if not overlap:
                continue
            if (left.period_start, left.period_end) != (right.period_start, right.period_end):
                conflict("Overlapping authority uses incompatible period partitions.")
            if left.retained_digest != right.retained_digest:
                changed = True
    return changed


def next_selection(action, vector, previous, bundle_id):
    frozen = previous.frozen if previous else False
    current_use = previous.current_use if previous else "SELECTED"
    if action == AuthorityAction.FREEZE:
        frozen = True
    elif action == AuthorityAction.REOPEN:
        frozen = False
    elif action == AuthorityAction.WITHDRAW_CURRENT_USE:
        current_use = "WITHDRAWN"
    elif action in REPLACEMENTS:
        current_use = "SELECTED"
    return validate_selection(
        AuthoritySelection(
            scope=vector.scope,
            revision=previous.revision + 1 if previous else 1,
            candidate_id=vector.candidate_id,
            vector_digest=vector.vector_digest,
            frozen=frozen,
            current_use=current_use,
            bundle_id=bundle_id,
        )
    )


def require_current_verification(verification, proposal_digest: str, now: datetime):
    if verification.proposal_digest != proposal_digest or verification.receipt.proposal_digest != proposal_digest:
        denied()
    if verification.checked_at > now or verification.receipt.valid_until <= now:
        denied()
