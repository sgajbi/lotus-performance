"""Fail-closed durable transitions for composite-materialization.v1."""

from __future__ import annotations

from typing import NoReturn

from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
)
from app.models.composites import CompositeMemberReturnFact
from app.services.composite_materialization.member_evidence_policy import require_member_source_evidence
from app.services.composite_materialization.source_contract import (
    PinnedCompositeSource,
    membership_decision_for_window,
    require_pinned_source_scope,
)
from core.errors import APIConflictError

_TRANSITIONS = {
    CompositeMaterializationState.WAITING: {
        CompositeMaterializationState.WAITING,
        CompositeMaterializationState.PUBLISHING,
        CompositeMaterializationState.BLOCKED,
    },
    CompositeMaterializationState.PUBLISHING: {
        CompositeMaterializationState.PUBLISHING,
        CompositeMaterializationState.COMPLETE,
    },
    CompositeMaterializationState.COMPLETE: set(),
    CompositeMaterializationState.BLOCKED: set(),
}


def _refuse(code: str) -> NoReturn:
    raise APIConflictError("Materialization progress violates its pinned release contract.", error_code=code)


def require_progress_transition(
    *,
    command: CompositeMaterializationCommand,
    tenant_id: str,
    prior_source: PinnedCompositeSource | None,
    prior_outcomes: list[CompositeMemberMaterializationOutcome],
    prior_state: CompositeMaterializationState,
    source: PinnedCompositeSource | None,
    outcomes: list[CompositeMemberMaterializationOutcome],
    state: CompositeMaterializationState,
) -> None:
    if state not in _TRANSITIONS[prior_state]:
        _refuse("COMPOSITE_MATERIALIZATION_TRANSITION_REFUSED")
    if prior_source is not None and source != prior_source:
        _refuse("COMPOSITE_MATERIALIZATION_SOURCE_IMMUTABLE")
    if source is None:
        if outcomes or state not in {CompositeMaterializationState.WAITING, CompositeMaterializationState.BLOCKED}:
            _refuse("COMPOSITE_MATERIALIZATION_SOURCE_REQUIRED")
        return
    require_pinned_source_scope(source, command=command, tenant_id=tenant_id)
    _require_full_universe(source, outcomes)
    _require_retained_outcomes(prior_outcomes, outcomes)
    for outcome in outcomes:
        _require_member_outcome(source, command, outcome)
    _require_release_state(outcomes, state)


def require_retained_progress(
    *,
    command: CompositeMaterializationCommand,
    tenant_id: str,
    source: PinnedCompositeSource | None,
    outcomes: list[CompositeMemberMaterializationOutcome],
    state: CompositeMaterializationState,
) -> None:
    """Reapply source/member invariants to restored snapshots, not only writes."""
    require_progress_transition(
        command=command,
        tenant_id=tenant_id,
        prior_source=None,
        prior_outcomes=[],
        prior_state=CompositeMaterializationState.WAITING,
        source=source,
        outcomes=outcomes,
        state=CompositeMaterializationState.PUBLISHING if state == CompositeMaterializationState.COMPLETE else state,
    )


def _require_full_universe(
    source: PinnedCompositeSource, outcomes: list[CompositeMemberMaterializationOutcome]
) -> None:
    identities = [item.portfolio_id for item in outcomes]
    if len(identities) != len(set(identities)) or set(identities) != set(source.attestation.expected_portfolio_ids):
        _refuse("COMPOSITE_MATERIALIZATION_UNIVERSE_INCOMPLETE")


def _require_retained_outcomes(
    previous: list[CompositeMemberMaterializationOutcome], current: list[CompositeMemberMaterializationOutcome]
) -> None:
    by_identity = {item.portfolio_id: item for item in current}
    for item in previous:
        retained = by_identity.get(item.portfolio_id)
        if item.state != CompositeMemberOutcomeState.WAITING and retained != item:
            _refuse("COMPOSITE_MATERIALIZATION_OUTCOME_IMMUTABLE")
        if retained is not None and retained.inspection_attempts not in {
            item.inspection_attempts,
            item.inspection_attempts + 1,
        }:
            _refuse("COMPOSITE_MATERIALIZATION_INSPECTION_COUNT_REFUSED")


def _require_member_outcome(
    source: PinnedCompositeSource,
    command: CompositeMaterializationCommand,
    outcome: CompositeMemberMaterializationOutcome,
) -> None:
    decision = membership_decision_for_window(source, command=command, portfolio_id=outcome.portfolio_id)
    if decision.status == "EXCLUDED":
        if outcome.state != CompositeMemberOutcomeState.EXCLUDED:
            _refuse("COMPOSITE_MATERIALIZATION_ELIGIBILITY_MISMATCH")
        return
    if decision.status == "PENDING_REVIEW" or not decision.discretionary:
        if outcome.state != CompositeMemberOutcomeState.BLOCKED:
            _refuse("COMPOSITE_MATERIALIZATION_ELIGIBILITY_MISMATCH")
        return
    if outcome.state == CompositeMemberOutcomeState.EXCLUDED:
        _refuse("COMPOSITE_MATERIALIZATION_ELIGIBILITY_MISMATCH")
    if outcome.fact is not None:
        _require_fact_scope(command, outcome, outcome.fact)


def _require_fact_scope(
    command: CompositeMaterializationCommand,
    outcome: CompositeMemberMaterializationOutcome,
    fact: CompositeMemberReturnFact,
) -> None:
    reference = next((item for item in command.member_calculations if item.portfolio_id == outcome.portfolio_id), None)
    if reference is None:
        _refuse("COMPOSITE_MATERIALIZATION_FACT_SCOPE_MISMATCH")
    actual = (
        fact.composite_id,
        fact.period_start,
        fact.period_end,
        fact.return_view,
        fact.reporting_currency,
        fact.restatement_sequence,
        fact.restatement_version,
        fact.calculation_id,
        fact.source_fingerprint,
        fact.status.value,
    )
    expected = (
        command.composite_id,
        command.period_start,
        command.period_end,
        command.return_view,
        command.reporting_currency,
        command.restatement_sequence,
        str(command.materialization_id),
        str(reference.calculation_id),
        reference.calculation_hash,
        "READY",
    )
    if actual != expected:
        _refuse("COMPOSITE_MATERIALIZATION_FACT_SCOPE_MISMATCH")
    require_member_source_evidence(command, outcome)


def _require_release_state(
    outcomes: list[CompositeMemberMaterializationOutcome], state: CompositeMaterializationState
) -> None:
    if state not in {CompositeMaterializationState.PUBLISHING, CompositeMaterializationState.COMPLETE}:
        return
    if any(
        item.state not in {CompositeMemberOutcomeState.READY, CompositeMemberOutcomeState.EXCLUDED} for item in outcomes
    ):
        _refuse("COMPOSITE_MATERIALIZATION_RELEASE_INCOMPLETE")
    if not any(item.state == CompositeMemberOutcomeState.READY for item in outcomes):
        _refuse("COMPOSITE_MATERIALIZATION_RELEASE_EMPTY")
