# app/api/endpoints/contribution.py
from uuid import UUID

import pandas as pd
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    ContributionAcceptedResponse,
    ContributionResponse,
)
from app.services.async_result_service import resolve_async_result
from app.services.contribution_service import calculate_contribution
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
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
    execution_mode = "async" if _should_offload_contribution(request) else "sync"
    if execution_mode == "async":
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="Contribution",
            portfolio_id=request.portfolio_id,
            requested_window=_build_execution_window(request),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason="large_position_count_contribution",
            accepted_response_factory=_accepted_response,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="Contribution",
        portfolio_id=request.portfolio_id,
        requested_window=_build_execution_window(request),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

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
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=ContributionResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="Async contribution result not found for the given calculation_id.",
        failed_detail="Async contribution execution failed.",
    )
