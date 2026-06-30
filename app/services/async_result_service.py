from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.services.async_result_store import AsyncResultRecord, AsyncResultStatus, async_result_store
from app.services.compute_job_store import ComputeJobRecord, ComputeJobStatus, compute_job_store

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)
AcceptedModelT = TypeVar("AcceptedModelT", bound=BaseModel)
ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL = "Async result payload failed response contract validation."
ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON = "async_result_response_schema_invalid"
logger = logging.getLogger(__name__)

ACTIVE_ASYNC_JOB_STATUSES = frozenset(
    {
        ComputeJobStatus.PENDING,
        ComputeJobStatus.LEASED,
        ComputeJobStatus.RUNNING,
    }
)


def _is_active_async_job_status(job_status: ComputeJobStatus) -> bool:
    return job_status in ACTIVE_ASYNC_JOB_STATUSES


def _resolve_stored_async_result(
    *,
    async_result: AsyncResultRecord,
    response_model: type[ResponseModelT],
    failed_detail: str,
) -> ResponseModelT:
    if async_result.result_status == AsyncResultStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=async_result.error_message or failed_detail,
        )
    return _validate_response_payload(
        calculation_id=async_result.calculation_id,
        response_model=response_model,
        response_payload=async_result.response_payload,
        source="async_result_store",
    )


def _resolve_compute_job_result(
    *,
    calculation_id: UUID,
    job: ComputeJobRecord | None,
    response_model: type[ResponseModelT],
    accepted_response_factory: Callable[[UUID], AcceptedModelT],
    not_found_detail: str,
    failed_detail: str,
) -> ResponseModelT | JSONResponse:
    job = _require_compute_job(job, not_found_detail=not_found_detail)
    if _is_active_async_job_status(job.job_status):
        accepted = accepted_response_factory(calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))
    if job.job_status == ComputeJobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message or failed_detail,
        )
    return _validate_response_payload(
        calculation_id=calculation_id,
        response_model=response_model,
        response_payload=job.response_payload,
        source="compute_job_store",
    )


def _validate_response_payload(
    *,
    calculation_id: UUID,
    response_model: type[ResponseModelT],
    response_payload: dict[str, Any] | None,
    source: str,
) -> ResponseModelT:
    try:
        return response_model.model_validate(response_payload)
    except ValidationError as exc:
        logger.warning(
            "Async result response payload failed schema validation.",
            extra={
                "calculation_id": str(calculation_id),
                "source": source,
                "response_model": response_model.__name__,
                "reason": ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_REASON,
                "validation_error_count": exc.error_count(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ASYNC_RESULT_RESPONSE_SCHEMA_INVALID_DETAIL,
        ) from None


def _require_compute_job(
    job: ComputeJobRecord | None,
    *,
    not_found_detail: str,
) -> ComputeJobRecord:
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    return job


def resolve_async_result(
    *,
    calculation_id: UUID,
    response_model: type[ResponseModelT],
    accepted_response_factory: Callable[[UUID], AcceptedModelT],
    not_found_detail: str,
    failed_detail: str,
) -> ResponseModelT | JSONResponse:
    async_result = async_result_store.get_result(calculation_id)
    if async_result is not None:
        return _resolve_stored_async_result(
            async_result=async_result,
            response_model=response_model,
            failed_detail=failed_detail,
        )

    return _resolve_compute_job_result(
        calculation_id=calculation_id,
        job=compute_job_store.get_job(calculation_id),
        response_model=response_model,
        accepted_response_factory=accepted_response_factory,
        not_found_detail=not_found_detail,
        failed_detail=failed_detail,
    )
