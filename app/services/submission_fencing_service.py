from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.async_result_store import async_result_store
from app.services.compute_job_store import (
    ComputeJobRegistrationStatus,
    compute_job_store,
)
from app.services.execution_registry import (
    ExecutionRegistrationStatus,
    execution_registry,
)


def register_sync_execution_or_raise(
    *,
    calculation_id: UUID,
    analytics_type: str,
    portfolio_id: str | None,
    requested_window: dict[str, Any],
    input_fingerprint: str | None,
    calculation_hash: str | None,
) -> None:
    registration = execution_registry.register_execution(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        portfolio_id=portfolio_id,
        execution_mode="sync",
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    if registration.status != ExecutionRegistrationStatus.CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A calculation with this calculation_id already exists. "
                "Use a new calculation_id for synchronous execution."
            ),
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
) -> JSONResponse:
    execution_registry.create_schema()
    compute_job_store.create_schema()
    async_result_store.create_schema()

    registration = execution_registry.register_execution(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        portfolio_id=portfolio_id,
        execution_mode="async",
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    if registration.status == ExecutionRegistrationStatus.CONFLICT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A different async calculation already exists for this calculation_id. "
                "Reuse the original request exactly or submit with a new calculation_id."
            ),
        )

    if registration.status == ExecutionRegistrationStatus.CREATED:
        execution_registry.start_stage(calculation_id, "submission")

    job_registration = compute_job_store.register_job(
        calculation_id=calculation_id,
        analytics_type=analytics_type,
        request_payload=request_payload,
    )
    if job_registration.status == ComputeJobRegistrationStatus.CONFLICT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A different async compute job already exists for this calculation_id. "
                "Reuse the original request exactly or submit with a new calculation_id."
            ),
        )

    if registration.status == ExecutionRegistrationStatus.CREATED:
        execution_registry.complete_stage(
            calculation_id,
            "submission",
            details={"offload_reason": offload_reason},
        )

    accepted = accepted_response_factory(calculation_id)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))
