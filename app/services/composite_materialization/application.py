from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from uuid import UUID

from app.adapters.composite_materialization_stores import (
    materialization_admission_transaction,
    materialization_ledger,
    member_facts,
)
from app.adapters.composite_member_result_source import RetainedCompositeMemberResultSource, member_outcome
from app.adapters.composite_membership_source import ManageCompositeMembershipSource
from app.adapters.composite_provider_member_source import AuthorityCompositeMemberResultSource
from app.core.application_responses import ApplicationHttpResponse
from app.enterprise_authorization import authorize_privileged_read_request, authorize_write_request
from app.models.composite_authority import ManageCompositeDefinitionV2
from app.models.composite_materialization import (
    CompositeMaterializationAcceptedResponse,
    CompositeMaterializationCommand,
    CompositeMaterializationProgress,
    CompositeMaterializationState,
    CompositeMemberMaterializationOutcome,
    CompositeMemberOutcomeState,
)
from app.observability import tenant_id_var
from app.ports.composite_materialization import (
    CompositeComputeLeaseReader,
    CompositeFactsRepository,
    CompositeMaterializationRepository,
    CompositeMemberResultSource,
    CompositeMembershipSource,
    ComputeJobLeaseOwnershipError,
    ComputeJobRecord,
    ComputeJobStatus,
    MaterializationRecord,
)
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_COMPOSITE_MATERIALIZATION
from app.services.async_observability_context import async_observability_request_payload
from app.services.composite_materialization.source_contract import PinnedCompositeSource, membership_decision_for_window
from app.services.core_tenant_authority import (
    admitted_tenant_authority,
    admitted_tenant_authority_from_header_values,
    require_composite_tenant_authority,
)
from app.services.reproducibility_service import generate_value_fingerprint
from app.services.submission_fencing_service import register_async_submission_or_raise
from core.errors import APIConflictError, APIError

_READ_AUTHORITY_HEADERS = (
    "x-tenant-id",
    "x-actor-id",
    "x-role",
    "x-user-id",
    "x-service-id",
    "x-service-identity",
    "x-correlation-id",
    "x-request-id",
    "x-capabilities",
    "x-portfolio-id",
)
_MAX_MEMBERS_PER_ATTEMPT = 32


def admit_materialization_tenant(header_values: list[str]) -> str:
    return require_composite_tenant_authority(admitted_tenant_authority_from_header_values(header_values)).tenant_id


def admit_materialization_identity(header_values: list[str]) -> str:
    if len(header_values) != 1 or not header_values[0].strip() or len(header_values[0].strip()) > 128:
        raise APIError(
            status_code=400,
            detail="Composite caller identity is malformed.",
            error_code="COMPOSITE_CALLER_IDENTITY_MALFORMED",
        )
    return header_values[0].strip()


def accepted_materialization(command: CompositeMaterializationCommand) -> CompositeMaterializationAcceptedResponse:
    return CompositeMaterializationAcceptedResponse(
        calculation_id=command.calculation_id,
        materialization_id=command.materialization_id,
        poll_path=f"/performance/executions/{command.calculation_id}",
        result_path=f"/performance/composites/materializations/{command.materialization_id}",
    )


def submit_materialization(
    command: CompositeMaterializationCommand,
    *,
    tenant_id: str,
    actor_id: str,
    role: str,
    request_headers: Mapping[str, str],
) -> ApplicationHttpResponse:
    tenant_id = require_composite_tenant_authority(admitted_tenant_authority(tenant_id)).tenant_id
    authority = {key: value for key, value in request_headers.items() if key.lower() in _READ_AUTHORITY_HEADERS}
    authority["x-tenant-id"] = tenant_id
    _require_durable_caller_authority(authority)
    payload = async_observability_request_payload(
        {
            "command": command.model_dump(mode="json"),
            "actor_id": actor_id,
            "role": role,
            "authority": authority,
        }
    )
    input_fingerprint, calculation_hash = generate_value_fingerprint(
        command.immutable_payload(), "composite-materialization.v1"
    )
    token = tenant_id_var.set(tenant_id)
    try:
        with materialization_admission_transaction() as (ledger, stores):
            ledger.register(command, tenant_id=tenant_id, actor_id=actor_id)
            return register_async_submission_or_raise(
                calculation_id=command.calculation_id,
                analytics_type=ANALYTICS_WORKFLOW_COMPOSITE_MATERIALIZATION,
                portfolio_id=None,
                requested_window={"start_date": str(command.period_start), "end_date": str(command.period_end)},
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                request_payload=payload,
                offload_reason="governed_composite_materialization",
                requires_tenant_authority=True,
                accepted_response_factory=lambda _: accepted_materialization(command),
                stores=stores,
            )
    finally:
        tenant_id_var.reset(token)


def _require_durable_caller_authority(authority: dict[str, str]) -> None:
    path = "/performance/composites/materializations"
    can_write, _ = authorize_write_request("POST", path, authority)
    can_read, _ = authorize_privileged_read_request("GET", path, authority)
    if not can_write or not can_read:
        raise APIError(
            status_code=403,
            detail="Composite materialization requires durable caller authority for submission and member-result reads.",
            error_code="COMPOSITE_MATERIALIZATION_AUTHORITY_REFUSED",
        )


def inspect_materialization(
    materialization_id: UUID,
    *,
    tenant_id: str,
    offset: int = 0,
    limit: int = 100,
    expected_revision: int | None = None,
    ledger: CompositeMaterializationRepository = materialization_ledger,
) -> CompositeMaterializationProgress:
    record = ledger.get(materialization_id, tenant_id=tenant_id)
    if (offset > 0 and expected_revision is None) or (
        expected_revision is not None and record.revision != expected_revision
    ):
        raise APIConflictError(
            "Materialization inspection changed; restart paging from its first page.",
            error_code="COMPOSITE_MATERIALIZATION_PAGE_EVIDENCE_CHANGED",
        )
    return progress(record, offset=offset, limit=limit)


def progress(record: MaterializationRecord, *, offset: int = 0, limit: int = 100) -> CompositeMaterializationProgress:
    members = sorted(record.outcomes, key=lambda item: item.portfolio_id)
    counts = {state: sum(item.state == state for item in members) for state in CompositeMemberOutcomeState}
    selected = members[offset : offset + limit]
    return CompositeMaterializationProgress(
        materialization_id=record.command.materialization_id,
        composite_id=record.command.composite_id,
        state=record.state,
        revision=record.revision,
        source_cut_id=record.command.source_cut_id,
        expected_count=len(record.source.attestation.expected_portfolio_ids) if record.source else 0,
        ready_count=counts[CompositeMemberOutcomeState.READY],
        excluded_count=counts[CompositeMemberOutcomeState.EXCLUDED],
        blocked_count=counts[CompositeMemberOutcomeState.BLOCKED],
        waiting_count=counts[CompositeMemberOutcomeState.WAITING],
        retryable=record.state == CompositeMaterializationState.WAITING,
        reason_code=record.reason_code,
        restatement_sequence=record.command.restatement_sequence,
        reporting_currency=record.command.reporting_currency,
        returned_count=len(selected),
        next_offset=offset + len(selected) if offset + len(selected) < len(members) else None,
        members=selected,
    )


def run_materialization_attempt(
    job: ComputeJobRecord,
    *,
    job_store: CompositeComputeLeaseReader,
    membership_source: CompositeMembershipSource | None = None,
    member_source: CompositeMemberResultSource | None = None,
    ledger: CompositeMaterializationRepository = materialization_ledger,
    facts: CompositeFactsRepository = member_facts,
) -> CompositeMaterializationProgress:
    tenant_id = _required_job_tenant(job)
    command = CompositeMaterializationCommand.model_validate(job.request_payload["command"])

    def fence() -> None:
        _require_attempt_lease(job, job_store=job_store, tenant_id=tenant_id)

    fence()
    record = ledger.register(command, tenant_id=tenant_id, actor_id=job.request_payload["actor_id"])
    if record.state in {CompositeMaterializationState.COMPLETE, CompositeMaterializationState.BLOCKED}:
        return progress(record)
    if record.source is None:
        source = _read_membership_source(
            job,
            record,
            tenant_id=tenant_id,
            ledger=ledger,
            membership_source=membership_source
            or ManageCompositeMembershipSource(request_headers=job.request_payload["authority"]),
            fence=fence,
        )
        fence()
        record = ledger.save(
            command.materialization_id,
            tenant_id=tenant_id,
            expected_revision=record.revision,
            source=source,
            outcomes=_initial_outcomes(source, command),
            state=CompositeMaterializationState.WAITING,
            reason_code="COMPOSITE_MEMBERS_PENDING",
        )
    if record.state == CompositeMaterializationState.WAITING:
        record = _resolve_members(
            record,
            tenant_id=tenant_id,
            request_headers=job.request_payload["authority"],
            member_source=member_source or _default_member_source(record.source),
            ledger=ledger,
            fence=fence,
        )
    if record.state == CompositeMaterializationState.PUBLISHING:
        record = _publish(record, tenant_id=tenant_id, ledger=ledger, facts=facts, fence=fence)
    if record.state == CompositeMaterializationState.WAITING:
        raise APIError(
            status_code=503,
            detail="Composite member evidence is pending; durable progress is retained.",
            error_code="COMPOSITE_MEMBERS_PENDING",
            retryable=True,
        )
    return progress(record)


def _default_member_source(source):
    if source is not None and isinstance(source.definition, ManageCompositeDefinitionV2):
        return AuthorityCompositeMemberResultSource(source.definition, admitted_source=source)
    return RetainedCompositeMemberResultSource()


def _read_membership_source(
    job: ComputeJobRecord,
    record: MaterializationRecord,
    *,
    tenant_id: str,
    ledger: CompositeMaterializationRepository,
    membership_source: CompositeMembershipSource,
    fence: Callable[[], None],
) -> PinnedCompositeSource:
    try:
        return asyncio.run(
            membership_source.read_pinned(
                record.command,
                tenant_id=tenant_id,
                actor_id=job.request_payload["actor_id"],
                role=job.request_payload["role"],
            )
        )
    except APIError as exc:
        fence()
        ledger.save(
            record.command.materialization_id,
            tenant_id=tenant_id,
            expected_revision=record.revision,
            source=None,
            outcomes=[],
            state=CompositeMaterializationState.WAITING if exc.retryable else CompositeMaterializationState.BLOCKED,
            reason_code="COMPOSITE_SOURCE_UNAVAILABLE" if exc.retryable else "COMPOSITE_SOURCE_REFUSED",
        )
        raise


def _required_job_tenant(job: ComputeJobRecord) -> str:
    return require_composite_tenant_authority(admitted_tenant_authority(job.tenant_id or "")).tenant_id


def _require_attempt_lease(
    job: ComputeJobRecord,
    *,
    job_store: CompositeComputeLeaseReader,
    tenant_id: str,
) -> None:
    if job.worker_id is None:
        raise ComputeJobLeaseOwnershipError("Materialization attempt has no acquired lease owner.")
    job_store.ensure_active_lease_owner(job.calculation_id, worker_id=job.worker_id)
    current = job_store.get_job_for_tenant(job.calculation_id, tenant_id=tenant_id)
    if current is None or current.job_status != ComputeJobStatus.RUNNING or current.attempt_count != job.attempt_count:
        raise ComputeJobLeaseOwnershipError("Materialization attempt no longer owns its compute lease.")


def _initial_outcomes(
    source: PinnedCompositeSource, command: CompositeMaterializationCommand
) -> list[CompositeMemberMaterializationOutcome]:
    outcomes = []
    for portfolio_id in sorted(source.attestation.expected_portfolio_ids):
        decision = membership_decision_for_window(source, command=command, portfolio_id=portfolio_id)
        if decision.status == "EXCLUDED":
            outcomes.append(
                CompositeMemberMaterializationOutcome(
                    portfolio_id=portfolio_id,
                    state=CompositeMemberOutcomeState.EXCLUDED,
                    reason_code="MANAGE_MEMBER_EXCLUDED",
                    retryable=False,
                )
            )
        elif decision.status == "PENDING_REVIEW" or not decision.discretionary:
            outcomes.append(member_outcome(portfolio_id, code="MANAGE_ELIGIBILITY_NOT_SUPPORTABLE"))
        else:
            outcomes.append(member_outcome(portfolio_id, code="PINNED_MEMBER_RESULT_PENDING", retryable=True))
    return outcomes


def _resolve_members(
    record: MaterializationRecord,
    *,
    tenant_id: str,
    request_headers: Mapping[str, str],
    member_source: CompositeMemberResultSource,
    ledger: CompositeMaterializationRepository,
    fence: Callable[[], None],
) -> MaterializationRecord:
    if record.source is None:
        raise ValueError("Pinned source admission must precede member resolution")
    command = record.command
    references = {item.portfolio_id: item for item in command.member_calculations}
    candidates = sorted(
        (
            (index, outcome)
            for index, outcome in enumerate(record.outcomes)
            if outcome.state == CompositeMemberOutcomeState.WAITING
        ),
        key=lambda item: (item[1].inspection_attempts, item[1].portfolio_id),
    )
    for index, outcome in candidates[:_MAX_MEMBERS_PER_ATTEMPT]:
        fence()
        reference = references.get(outcome.portfolio_id)
        if isinstance(member_source, AuthorityCompositeMemberResultSource):
            resolved = member_source.read_member(
                command,
                reference,
                tenant_id=tenant_id,
                membership_snapshot_id=command.membership_content_hash,
                request_headers=request_headers,
                member_id=outcome.portfolio_id,
            )
        elif reference is None:
            resolved = member_outcome(outcome.portfolio_id, code="MEMBER_CALCULATION_REFERENCE_REQUIRED")
        else:
            resolved = member_source.read_member(
                command,
                reference,
                tenant_id=tenant_id,
                membership_snapshot_id=command.membership_content_hash,
                request_headers=request_headers,
            )
        fence()
        outcomes = list(record.outcomes)
        outcomes[index] = resolved.model_copy(update={"inspection_attempts": outcome.inspection_attempts + 1})
        record = ledger.save(
            command.materialization_id,
            tenant_id=tenant_id,
            expected_revision=record.revision,
            source=record.source,
            outcomes=outcomes,
            state=CompositeMaterializationState.WAITING,
            reason_code="COMPOSITE_MEMBERS_PENDING",
        )
    state, reason = _release_state(record.outcomes)
    fence()
    return ledger.save(
        command.materialization_id,
        tenant_id=tenant_id,
        expected_revision=record.revision,
        source=record.source,
        outcomes=record.outcomes,
        state=state,
        reason_code=reason,
    )


def _release_state(
    outcomes: list[CompositeMemberMaterializationOutcome],
) -> tuple[CompositeMaterializationState, str | None]:
    if any(item.state == CompositeMemberOutcomeState.BLOCKED for item in outcomes):
        return CompositeMaterializationState.BLOCKED, "COMPOSITE_MEMBER_EVIDENCE_REFUSED"
    if any(item.state == CompositeMemberOutcomeState.WAITING for item in outcomes):
        return CompositeMaterializationState.WAITING, "COMPOSITE_MEMBERS_PENDING"
    if not any(item.state == CompositeMemberOutcomeState.READY for item in outcomes):
        return CompositeMaterializationState.BLOCKED, "COMPOSITE_NO_ELIGIBLE_MEMBERS"
    return CompositeMaterializationState.PUBLISHING, "COMPOSITE_PUBLICATION_PENDING"


def _publish(
    record: MaterializationRecord,
    *,
    tenant_id: str,
    ledger: CompositeMaterializationRepository,
    facts: CompositeFactsRepository,
    fence: Callable[[], None],
) -> MaterializationRecord:
    if record.source is None:
        raise ValueError("Publication requires pinned source evidence")
    command = record.command
    fence()
    facts.upsert_definition(record.source.definition.performance_definition(), tenant_id=tenant_id)
    expected_families = set()
    for outcome in record.outcomes:
        if outcome.fact is not None:
            fence()
            facts.upsert_member_return_fact(outcome.fact, tenant_id=tenant_id)
            expected_families.add((outcome.portfolio_id, command.period_start, command.period_end))
    fence()
    facts.complete_member_return_fact_publication(
        tenant_id=tenant_id,
        composite_id=command.composite_id,
        return_view=command.return_view,
        reporting_currency=command.reporting_currency,
        restatement_sequence=command.restatement_sequence,
        period_start=command.period_start,
        period_end=command.period_end,
        expected_families=expected_families,
        source_fingerprint=command.attestation_content_hash,
    )
    fence()
    return ledger.save(
        command.materialization_id,
        tenant_id=tenant_id,
        expected_revision=record.revision,
        source=record.source,
        outcomes=record.outcomes,
        state=CompositeMaterializationState.COMPLETE,
        reason_code=None,
    )
