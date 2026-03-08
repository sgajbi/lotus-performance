# app/api/endpoints/contribution.py
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    ContributionAcceptedResponse,
    ContributionResponse,
)
from app.services.compute_job_store import ComputeJobStatus, compute_job_store
from app.services.contribution_service import calculate_contribution
from app.services.execution_registry import execution_registry
from core.repro import generate_canonical_hash

router = APIRouter()
settings = get_settings()


def _as_numeric(value: object, default=0):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


def _should_offload_contribution(request: ContributionRequest) -> bool:
    return len(request.positions_data) >= settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT


def _build_execution_window(request: ContributionRequest) -> dict[str, object]:
    return {
        "report_start_date": str(request.report_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "position_count": len(request.positions_data),
        "hierarchical": bool(request.hierarchy),
    }


def _accepted_response(calculation_id) -> ContributionAcceptedResponse:
    return ContributionAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/contribution/results/{calculation_id}",
    )


@router.post(
    "/contribution",
    response_model=ContributionResponse | ContributionAcceptedResponse,
    summary="Calculate Position Contribution",
)
async def calculate_contribution_endpoint(request: ContributionRequest) -> ContributionResponse | JSONResponse:
    input_fingerprint, calculation_hash = generate_canonical_hash(request, settings.APP_VERSION)
    execution_registry.create_schema()
    compute_job_store.create_schema()
    execution_mode = "async" if _should_offload_contribution(request) else "sync"
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="Contribution",
        portfolio_id=request.portfolio_id,
        execution_mode=execution_mode,
        requested_window=_build_execution_window(request),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    if execution_mode == "async":
        execution_registry.start_stage(request.calculation_id, "submission")
        compute_job_store.enqueue_job(
            calculation_id=request.calculation_id,
            analytics_type="Contribution",
            request_payload=request.model_dump(mode="json"),
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "submission",
            details={"offload_reason": "large_position_count_contribution"},
        )
        accepted = _accepted_response(request.calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))

    return calculate_contribution(
        request,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )


@router.get(
    "/contribution/results/{calculation_id}",
    response_model=ContributionResponse | ContributionAcceptedResponse,
    summary="Retrieve async contribution result",
)
async def get_contribution_result(calculation_id: UUID) -> ContributionResponse | JSONResponse:
    job = compute_job_store.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Async contribution result not found for the given calculation_id.",
        )
    if job.job_status in {ComputeJobStatus.PENDING, ComputeJobStatus.RUNNING}:
        accepted = _accepted_response(calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))
    if job.job_status == ComputeJobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message or "Async contribution execution failed.",
        )
    return ContributionResponse.model_validate(job.response_payload)
