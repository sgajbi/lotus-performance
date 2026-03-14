from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.models.execution_polling import ExecutionResponse, build_execution_response
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry

router = APIRouter(tags=["Performance"])


@router.get(
    "/executions/{calculation_id}",
    response_model=ExecutionResponse,
    summary="Retrieve execution lifecycle state",
    description="Returns durable execution and stage metadata for a lotus-performance calculation.",
)
async def get_execution(calculation_id: UUID) -> ExecutionResponse:
    record = execution_registry.get_execution(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution data not found for the given calculation_id.",
        )

    job = compute_job_store.get_job(calculation_id)
    async_result = async_result_store.get_result(calculation_id)
    return build_execution_response(
        record=record,
        job=job,
        async_result=async_result,
    )
