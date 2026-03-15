# app/api/endpoints/contribution.py
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.contribution_analytics_requests import (
    ContributionAnalyticsRequest,
    ContributionInputMode,
)
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    ContributionAcceptedResponse,
    ContributionResponse,
)
from app.services.async_result_service import resolve_async_result
from app.services.contribution_mode_service import resolve_contribution_request
from app.services.contribution_service import calculate_contribution
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from core.repro import generate_canonical_hash

router = APIRouter()


def _as_numeric(value: object, default=0):
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


def _should_offload_contribution(request: ContributionAnalyticsRequest | ContributionRequest) -> bool:
    active_settings = get_settings()
    input_mode = getattr(request, "input_mode", ContributionInputMode.STATELESS)
    if input_mode == ContributionInputMode.STATEFUL:
        return (
            request.report_end_date - request.report_start_date
        ).days >= active_settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS

    stateless_input = getattr(request, "stateless_input", None)
    if stateless_input is not None:
        position_count = len(request.stateless_input.positions_data)
    elif input_mode == ContributionInputMode.STATEFUL:
        position_count = 0
    else:
        position_count = len(request.positions_data)
    return position_count >= active_settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT


def _build_execution_window(request: ContributionAnalyticsRequest | ContributionRequest) -> dict[str, object]:
    stateless_input = getattr(request, "stateless_input", None)
    input_mode = getattr(request, "input_mode", ContributionInputMode.STATELESS)
    if stateless_input is not None:
        position_count = len(request.stateless_input.positions_data)
    elif input_mode == ContributionInputMode.STATEFUL:
        position_count = 0
    else:
        position_count = len(request.positions_data)
    return {
        "report_start_date": str(request.report_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "position_count": position_count,
        "hierarchical": bool(request.hierarchy),
        "input_mode": input_mode.value,
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
async def calculate_contribution_endpoint(
    request: ContributionAnalyticsRequest,
) -> ContributionResponse | JSONResponse:
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_canonical_hash(request, active_settings.APP_VERSION)
    execution_mode = "async" if _should_offload_contribution(request) else "sync"
    if execution_mode == "async":
        offload_reason = (
            "long_window_stateful_contribution"
            if request.input_mode == ContributionInputMode.STATEFUL
            else "large_position_count_contribution"
        )
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="Contribution",
            portfolio_id=request.portfolio_id,
            requested_window=_build_execution_window(request),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=offload_reason,
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

    try:
        resolved = await resolve_contribution_request(request, settings=active_settings)
        if resolved.input_mode == ContributionInputMode.STATEFUL:
            input_fingerprint, calculation_hash = generate_canonical_hash(
                resolved.contribution_request,
                active_settings.APP_VERSION,
            )
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
        response = calculate_contribution(
            resolved.contribution_request,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            input_mode=resolved.input_mode,
        )
        return response
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
        )
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected error occurred during contribution request resolution: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during contribution request resolution: {exc}",
        ) from exc


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
