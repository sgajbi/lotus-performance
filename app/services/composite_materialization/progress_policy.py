"""Fail-closed durable transitions for composite-materialization.v1."""

from __future__ import annotations

from typing import NoReturn

from app.models.composite_authority import ManageCompositeDefinitionV2
from app.models.composite_materialization import (
    CompositeMaterializationCommand,
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
    CompositeProviderMemberEvidence,
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
    _require_source_progress(command, prior_source, source, prior_outcomes, prior_state)
    if source is None:
        if outcomes or state not in {CompositeMaterializationState.WAITING, CompositeMaterializationState.BLOCKED}:
            _refuse("COMPOSITE_MATERIALIZATION_SOURCE_REQUIRED")
        return
    require_pinned_source_scope(source, command=command, tenant_id=tenant_id)
    admitted_fx_source = _require_currency_source(
        source, command=command, tenant_id=tenant_id, outcomes=outcomes, state=state
    )
    _require_full_universe(source, outcomes)
    _require_retained_outcomes(prior_outcomes, outcomes)
    for outcome in outcomes:
        _require_member_outcome(source, command, outcome, admitted_fx_source=admitted_fx_source)
    _require_release_state(outcomes, state)


def _pending_currency_upgrade(command, prior_source, source, prior_state):
    return (
        command.currency_normalization_binding is not None
        and prior_state == CompositeMaterializationState.WAITING
        and prior_source.currency_normalization_wire is None
        and source.currency_normalization_wire is not None
    )


def _require_source_progress(command, prior_source, source, prior_outcomes, prior_state):
    if prior_source is None or source == prior_source:
        return
    if source is None or not _pending_currency_upgrade(command, prior_source, source, prior_state):
        _refuse("COMPOSITE_MATERIALIZATION_SOURCE_IMMUTABLE")
    if source.model_dump(exclude={"currency_normalization_wire"}) != prior_source.model_dump(
        exclude={"currency_normalization_wire"}
    ):
        _refuse("COMPOSITE_MATERIALIZATION_SOURCE_IMMUTABLE")
    _require_pending_currency_outcomes(prior_outcomes, prior_state)


def _require_pending_currency_outcomes(outcomes, state):
    if state not in {CompositeMaterializationState.WAITING, CompositeMaterializationState.BLOCKED}:
        _refuse("COMPOSITE_FX_SOURCE_UNAVAILABLE")
    if any(
        row.fact is not None or row.source_evidence is not None or row.state == CompositeMemberOutcomeState.READY
        for row in outcomes
    ):
        _refuse("COMPOSITE_FX_SOURCE_UNAVAILABLE")


def _require_currency_source(source, *, command, tenant_id, outcomes, state):
    if command.currency_normalization_binding is None:
        if source.currency_normalization_wire is not None:
            _refuse("COMPOSITE_FX_SOURCE_BINDING_REQUIRED")
        return
    from app.services.composite_materialization.currency_source_admission import (
        admit_composite_fx_source,
        fx_resolution_for_command,
        require_composite_native_currency,
        require_fx_normalization_route,
    )

    if source.currency_normalization_wire is None:
        _require_pending_currency_outcomes(outcomes, state)
        return
    require_fx_normalization_route(source.definition)
    admitted = admit_composite_fx_source(
        fx_resolution_for_command(command, tenant_id=tenant_id), retained_wire=source.currency_normalization_wire
    )
    require_composite_native_currency(admitted, source.definition)
    return admitted


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
    *,
    admitted_fx_source=None,
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
        _require_outcome_evidence(source, command, outcome, admitted_fx_source=admitted_fx_source)


def _require_outcome_evidence(source, command, outcome, *, admitted_fx_source=None):
    if isinstance(outcome.source_evidence, CompositeProviderMemberEvidence):
        from app.services.composite_materialization.provider_evidence_policy import require_provider_member_evidence

        require_provider_member_evidence(source, command, outcome)
        return
    if isinstance(source.definition, ManageCompositeDefinitionV2):
        from app.services.composite_materialization.internal_authority_policy import require_internal_selection_bindings

        reference = next((ref for ref in command.member_calculations if ref.portfolio_id == outcome.portfolio_id), None)
        require_internal_selection_bindings(
            source.definition,
            command,
            reference,
            outcome.source_evidence,
            facts=["MEMBER_RETURN", "BEGINNING_ASSETS", "ENDING_ASSETS"],
        )
    _require_fact_scope(
        command,
        outcome,
        outcome.fact,
        tenant_id=source.definition.tenant_id,
        currency_normalization_wire=source.currency_normalization_wire,
        admitted_fx_source=admitted_fx_source,
    )


def _require_fact_scope(
    command: CompositeMaterializationCommand,
    outcome: CompositeMemberMaterializationOutcome,
    fact: CompositeMemberReturnFact,
    *,
    tenant_id: str | None = None,
    currency_normalization_wire: dict | None = None,
    admitted_fx_source=None,
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
    require_member_source_evidence(
        command,
        outcome,
        tenant_id=tenant_id,
        currency_normalization_wire=currency_normalization_wire,
        admitted_fx_source=admitted_fx_source,
    )


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
