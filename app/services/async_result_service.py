from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.async_result_store import AsyncResultStatus, async_result_store
from app.services.compute_job_store import ComputeJobStatus, compute_job_store

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)
AcceptedModelT = TypeVar("AcceptedModelT", bound=BaseModel)


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
        if async_result.result_status == AsyncResultStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=async_result.error_message or failed_detail,
            )
        return response_model.model_validate(async_result.response_payload)

    job = compute_job_store.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    if job.job_status in {ComputeJobStatus.PENDING, ComputeJobStatus.LEASED, ComputeJobStatus.RUNNING}:
        accepted = accepted_response_factory(calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))
    if job.job_status == ComputeJobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message or failed_detail,
        )
    return response_model.model_validate(job.response_payload)
