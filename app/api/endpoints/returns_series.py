from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.async_openapi import async_result_responses, async_submission_responses
from app.models.returns_series import (
    ReturnsSeriesAcceptedResponse,
    ReturnsSeriesRequest,
    ReturnsSeriesResponse,
)
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_RETURNS_SERIES
from app.services.async_result_service import resolve_async_result
from app.services.returns_series_calculation_workflow_service import (
    accepted_returns_series_response,
    calculate_returns_series_workflow,
)

router = APIRouter(tags=["Integration"])


@router.post(
    "/returns/series",
    response_model=ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse,
    summary="Get canonical return series for downstream analytics",
    description=(
        "Returns canonical portfolio/benchmark/risk-free return time series for stateful analytics consumers. "
        "Supports stateless (request-supplied inputs) and stateful (platform-sourced inputs) modes."
    ),
    responses=async_submission_responses(
        accepted_model=ReturnsSeriesAcceptedResponse,
        analytics_name="returns-series",
        result_path_template="/integration/returns/series/results/{calculation_id}",
    ),
)
async def get_returns_series(request: ReturnsSeriesRequest) -> ReturnsSeriesResponse | JSONResponse:
    return await calculate_returns_series_workflow(request)


@router.get(
    "/returns/series/results/{calculation_id}",
    response_model=ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse,
    summary="Retrieve async returns-series result",
    description="Returns the final returns-series payload for an async executor job, or a pending handle while execution is in progress.",
    responses=async_result_responses(
        accepted_model=ReturnsSeriesAcceptedResponse,
        analytics_name="returns-series",
        result_path_template="/integration/returns/series/results/{calculation_id}",
        not_found_detail="Async returns-series result not found for the given calculation_id.",
        failed_detail="Async returns-series execution failed.",
    ),
)
async def get_returns_series_result(calculation_id: UUID, request: Request) -> ReturnsSeriesResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        expected_analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        response_model=ReturnsSeriesResponse,
        accepted_response_factory=accepted_returns_series_response,
        not_found_detail="Async returns-series result not found for the given calculation_id.",
        failed_detail="Async returns-series execution failed.",
        request_headers=request.headers,
    )
