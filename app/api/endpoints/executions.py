from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, status

from app.models.execution_polling import ExecutionResponse, build_execution_response
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry

router = APIRouter(tags=["Performance"])


@router.get(
    "/executions/{calculation_id}",
    response_model=ExecutionResponse,
    summary="Retrieve execution lifecycle state",
    description=(
        "Returns durable execution, stage, compute-job, async-result, and upstream snapshot metadata for a "
        "lotus-performance calculation. Use this endpoint to poll async work accepted by TWR, benchmark, "
        "workspace summary, returns-series, contribution, attribution, and TWR inspection endpoints before "
        "calling the endpoint-specific result route."
    ),
    responses={
        404: {
            "description": "No durable execution record exists for the supplied calculation_id.",
            "content": {
                "application/json": {"example": {"detail": "Execution data not found for the given calculation_id."}}
            },
        }
    },
)
async def get_execution(
    calculation_id: UUID = Path(
        description="Durable calculation identifier returned by an analytics endpoint.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    ),
) -> ExecutionResponse:
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
