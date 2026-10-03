from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.application_responses import ApplicationHttpResponse, accepted_application_response
from app.observability import record_idempotent_submission, tenant_id_var
from app.services.compute_job_store import (
    ComputeJobRegistrationResult,
    ComputeJobRegistrationStatus,
    ComputeJobStore,
    compute_job_store,
)
from app.services.core_tenant_authority import (
    MissingIdempotentSubmissionTenantAuthorityError,
    MissingStatefulSubmissionTenantAuthorityError,
    admitted_tenant_authority,
)
from app.services.durable_store_runtime import RuntimeStoreProxy
from app.services.execution_registry import (
    ExecutionRegistrationResult,
    ExecutionRegistrationStatus,
    ExecutionRegistry,
    ExecutionStatus,
    execution_registry,
)
from app.services.execution_stage_names import EXECUTION_STAGE_SUBMISSION
from core.errors import APIConflictError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AsyncSubmissionStores:
    """Existing stores, optionally bound by an adapter to one database transaction."""

    executions: ExecutionRegistry | RuntimeStoreProxy[ExecutionRegistry]
    jobs: ComputeJobStore | RuntimeStoreProxy[ComputeJobStore]


def _submission_stores(stores: AsyncSubmissionStores | None) -> AsyncSubmissionStores:
    return stores or AsyncSubmissionStores(execution_registry, compute_job_store)


def register_sync_execution_or_raise(
    *,
    calculation_id: UUID,
    analytics_type: str,
    portfolio_id: str | None,
    requested_window: dict[str, Any],
    input_fingerprint: str | None,
    calculation_hash: str | None,
    request_payload: dict[str, Any] | None = None,
) -> None:
    admitted_tenant_authority(tenant_id_var.get())
    registration = execution_registry.register_execution(
        calculation_id=calculation_id,
        tenant_id=tenant_id_var.get(),
        analytics_type=analytics_type,
        portfolio_id=portfolio_id,
        execution_mode="sync",
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        request_payload=request_payload,
    )
    if registration.status != ExecutionRegistrationStatus.CREATED:
        raise APIConflictError(
            "A calculation with this calculation_id already exists. Use a new calculation_id for synchronous execution."
        )


def register_async_submission_or_raise(
    *,
    calculation_id: UUID,
    analytics_type: str,
    portfolio_id: str | None,
    requested_window: dict[str, Any],
    input_fingerprint: str | None,
    calculation_hash: str | None,
    request_payload: dict[str, Any],
    offload_reason: str,
    accepted_response_factory: Callable[[UUID], BaseModel],
    requires_tenant_authority: bool = False,
    submission_idempotency_key_hash: str | None = None,
    submission_identity_fingerprint: str | None = None,
    submission_contract_version: str | None = None,
    idempotency_conflict_error_code: str | None = None,
    stores: AsyncSubmissionStores | None = None,
) -> ApplicationHttpResponse:
    stores = _submission_stores(stores)
    _require_submission_tenant_if_needed(
        requires_tenant_authority=requires_tenant_authority,
        requires_idempotency_authority=submission_idempotency_key_hash is not None,
    )
    registration = stores.executions.register_execution(
        calculation_id=calculation_id,
        tenant_id=tenant_id_var.get(),
        analytics_type=analytics_type,
        portfolio_id=portfolio_id,
        execution_mode="async",
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        request_payload=request_payload,
        submission_idempotency_key_hash=submission_idempotency_key_hash,
        submission_identity_fingerprint=submission_identity_fingerprint,
        submission_contract_version=submission_contract_version,
    )
    _raise_for_async_submission_conflict(
        registration=registration,
        analytics_type=analytics_type,
        has_idempotency_key=submission_idempotency_key_hash is not None,
        idempotency_conflict_error_code=idempotency_conflict_error_code,
    )

    created_execution = registration.status == ExecutionRegistrationStatus.CREATED
    registered_calculation_id, registered_request_payload = _registered_async_submission(
        registration=registration,
        calculation_id=calculation_id,
        request_payload=request_payload,
    )
    if created_execution:
        stores.executions.start_stage(registered_calculation_id, EXECUTION_STAGE_SUBMISSION)

    if not _is_durably_resolved_execution_replay(registration):
        job_registration = _register_async_compute_job_or_rollback_execution(
            calculation_id=registered_calculation_id,
            analytics_type=analytics_type,
            request_payload=registered_request_payload,
            created_execution=created_execution,
            preserve_created_execution=submission_idempotency_key_hash is not None,
            stores=stores,
        )

        _complete_async_submission_stage_if_needed(
            calculation_id=registered_calculation_id,
            execution_registration_status=registration.status,
            compute_job_registration_status=job_registration.status,
            created_execution=created_execution,
            offload_reason=offload_reason,
            stores=stores,
        )

    _record_idempotent_submission_outcome(
        analytics_type=analytics_type,
        has_idempotency_key=submission_idempotency_key_hash is not None,
        created_execution=created_execution,
    )

    return accepted_application_response(accepted_response_factory(registered_calculation_id))


def _is_durably_resolved_execution_replay(registration: ExecutionRegistrationResult) -> bool:
    return registration.status == ExecutionRegistrationStatus.REPLAY and (
        registration.response_payload_available
        or registration.existing_status in {ExecutionStatus.COMPLETE, ExecutionStatus.FAILED}
    )


def _raise_for_async_submission_conflict(
    *,
    registration: ExecutionRegistrationResult,
    analytics_type: str,
    has_idempotency_key: bool,
    idempotency_conflict_error_code: str | None,
) -> None:
    if registration.status != ExecutionRegistrationStatus.CONFLICT:
        return
    conflict_detail = (
        "Idempotency-Key conflicts with an existing attribution submission identity for this tenant."
        if idempotency_conflict_error_code is not None
        else "A different async calculation already exists for this calculation_id. "
        "Reuse the original request exactly or submit with a new calculation_id."
    )
    if has_idempotency_key:
        record_idempotent_submission(analytics_type=analytics_type, outcome="conflict")
    raise APIConflictError(conflict_detail, error_code=idempotency_conflict_error_code)


def _registered_async_submission(
    *,
    registration: ExecutionRegistrationResult,
    calculation_id: UUID,
    request_payload: dict[str, Any],
) -> tuple[UUID, dict[str, Any]]:
    registered_calculation_id = registration.calculation_id or calculation_id
    registered_request_payload = (
        registration.request_payload if registration.request_payload is not None else request_payload
    )
    return registered_calculation_id, registered_request_payload


def _record_idempotent_submission_outcome(
    *,
    analytics_type: str,
    has_idempotency_key: bool,
    created_execution: bool,
) -> None:
    if not has_idempotency_key:
        return
    record_idempotent_submission(
        analytics_type=analytics_type,
        outcome=("accepted" if created_execution else "replay"),
    )


def _register_async_compute_job_or_rollback_execution(
    *,
    calculation_id: UUID,
    analytics_type: str,
    request_payload: dict[str, Any],
    created_execution: bool,
    preserve_created_execution: bool = False,
    stores: AsyncSubmissionStores | None = None,
) -> ComputeJobRegistrationResult:
    stores = _submission_stores(stores)
    try:
        job_registration = stores.jobs.register_job(
            calculation_id=calculation_id,
            analytics_type=analytics_type,
            tenant_id=tenant_id_var.get(),
            request_payload=request_payload,
        )
    except Exception:
        logger.warning(
            "Async compute job registration failed for calculation_id=%s analytics_type=%s.",
            calculation_id,
            analytics_type,
            exc_info=True,
        )
        _rollback_created_async_execution(
            calculation_id=calculation_id,
            analytics_type=analytics_type,
            created_execution=created_execution,
            preserve_created_execution=preserve_created_execution,
            stores=stores,
        )
        raise

    if job_registration.status == ComputeJobRegistrationStatus.CONFLICT:
        _rollback_created_async_execution(
            calculation_id=calculation_id,
            analytics_type=analytics_type,
            created_execution=created_execution,
            preserve_created_execution=preserve_created_execution,
            stores=stores,
        )
        raise APIConflictError(
            "A different async compute job already exists for this calculation_id. "
            "Reuse the original request exactly or submit with a new calculation_id."
        )
    return job_registration


def _rollback_created_async_execution(
    *,
    calculation_id: UUID,
    analytics_type: str,
    created_execution: bool,
    preserve_created_execution: bool = False,
    stores: AsyncSubmissionStores | None = None,
) -> None:
    if not created_execution or preserve_created_execution:
        return
    try:
        _submission_stores(stores).executions.delete_execution(calculation_id)
    except Exception:
        logger.warning(
            "Async execution registration cleanup failed for calculation_id=%s analytics_type=%s.",
            calculation_id,
            analytics_type,
            exc_info=True,
        )


def _complete_async_submission_stage_if_needed(
    *,
    calculation_id: UUID,
    execution_registration_status: ExecutionRegistrationStatus,
    compute_job_registration_status: ComputeJobRegistrationStatus,
    created_execution: bool,
    offload_reason: str,
    stores: AsyncSubmissionStores | None = None,
) -> None:
    executions = _submission_stores(stores).executions
    if created_execution:
        executions.complete_stage(
            calculation_id,
            EXECUTION_STAGE_SUBMISSION,
            details={"offload_reason": offload_reason},
        )
        return
    if (
        execution_registration_status == ExecutionRegistrationStatus.REPLAY
        and compute_job_registration_status == ComputeJobRegistrationStatus.CREATED
    ):
        executions.start_stage(calculation_id, EXECUTION_STAGE_SUBMISSION)
        executions.complete_stage(
            calculation_id,
            EXECUTION_STAGE_SUBMISSION,
            details={"offload_reason": offload_reason},
        )
        return
    if (
        execution_registration_status == ExecutionRegistrationStatus.REPLAY
        and compute_job_registration_status == ComputeJobRegistrationStatus.REPLAY
    ):
        executions.complete_stage_if_in_progress(
            calculation_id,
            EXECUTION_STAGE_SUBMISSION,
            details={"offload_reason": offload_reason},
        )


def promote_existing_execution_to_async_submission_or_raise(
    *,
    calculation_id: UUID,
    analytics_type: str,
    requested_window: dict[str, Any],
    input_fingerprint: str | None,
    calculation_hash: str | None,
    request_payload: dict[str, Any],
    offload_reason: str,
    accepted_response_factory: Callable[[UUID], BaseModel],
    requires_tenant_authority: bool = False,
) -> ApplicationHttpResponse:
    _require_submission_tenant_if_needed(requires_tenant_authority=requires_tenant_authority)
    job_registration = compute_job_store.register_job(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        tenant_id=tenant_id_var.get(),
        request_payload=request_payload,
    )
    if job_registration.status == ComputeJobRegistrationStatus.CONFLICT:
        raise APIConflictError(
            "A different async compute job already exists for this calculation_id. "
            "Reuse the original request exactly or submit with a new calculation_id."
        )
    execution_registry.update_execution_contract(
        calculation_id,
        execution_mode="async",
        requested_window=requested_window,
    )
    execution_registry.update_execution_identity(
        calculation_id,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        request_payload=request_payload,
    )
    execution_registry.start_stage(calculation_id, EXECUTION_STAGE_SUBMISSION)
    execution_registry.complete_stage(
        calculation_id,
        EXECUTION_STAGE_SUBMISSION,
        details={"offload_reason": offload_reason},
    )
    return accepted_application_response(accepted_response_factory(calculation_id))


def _require_submission_tenant_if_needed(
    *,
    requires_tenant_authority: bool,
    requires_idempotency_authority: bool = False,
) -> None:
    admitted_authority = admitted_tenant_authority(tenant_id_var.get())
    if requires_idempotency_authority and admitted_authority is None:
        raise MissingIdempotentSubmissionTenantAuthorityError()
    if requires_tenant_authority and admitted_authority is None:
        raise MissingStatefulSubmissionTenantAuthorityError()
