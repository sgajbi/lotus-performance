from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import JSONResponse

from app.api.dependencies.execution_polling import get_execution_polling_store
from app.api.http_response_adapter import to_fastapi_response
from app.models.execution_polling import ExecutionResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.ports.execution_polling import ExecutionPollingStore
from app.services.execution_polling_service import EXECUTION_POLLING_NOT_FOUND_DETAIL, get_execution_polling_response

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
            "model": ErrorDetailResponse,
            "description": "No durable execution record exists for the supplied calculation_id.",
            "content": {"application/json": {"example": {"detail": EXECUTION_POLLING_NOT_FOUND_DETAIL}}},
        }
    },
)
async def get_execution(
    request: Request,
    calculation_id: UUID = Path(
        description="Durable calculation identifier returned by an analytics endpoint.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    ),
    store: ExecutionPollingStore = Depends(get_execution_polling_store),
) -> ExecutionResponse | JSONResponse:
    response = get_execution_polling_response(calculation_id, store=store, request_headers=request.headers)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=EXECUTION_POLLING_NOT_FOUND_DETAIL,
        )

    return to_fastapi_response(response)
