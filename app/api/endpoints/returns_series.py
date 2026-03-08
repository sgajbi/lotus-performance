from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.returns_series import (
    ReturnsSeriesAcceptedResponse,
    ReturnsSeriesRequest,
    ReturnsSeriesResponse,
)
from app.services.compute_job_store import ComputeJobStatus, compute_job_store
from app.services.core_integration_service import CoreIntegrationService  # noqa: F401
from app.services.execution_registry import execution_registry
from app.services.returns_series_service import (
    calculate_returns_series,
    core_points_to_dataframe,
    date_range_count,
    detect_gaps,
    filter_window,
    period_start,
    points_from_df,
    portfolio_timeseries_to_valuation_points,
    resample_returns,
    resolve_window,
    to_dataframe,
)
from core.repro import generate_canonical_hash

router = APIRouter(tags=["Integration"])
settings = get_settings()

_core_points_to_dataframe = core_points_to_dataframe
_date_range_count = date_range_count
_detect_gaps = detect_gaps
_filter_window = filter_window
_period_start = period_start
_points_from_df = points_from_df
_portfolio_timeseries_to_valuation_points = portfolio_timeseries_to_valuation_points
_resample_returns = resample_returns
_resolve_window = resolve_window
_to_dataframe = to_dataframe


def _should_offload_returns_series(request: ReturnsSeriesRequest) -> bool:
    if request.input_mode.value != "stateful":
        return False
    resolved_window = _resolve_window(request)
    return (resolved_window.end_date - resolved_window.start_date).days >= settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS


def _build_execution_window(request: ReturnsSeriesRequest) -> dict[str, object]:
    return {
        "mode": request.window.mode.value,
        "from_date": str(request.window.from_date) if request.window.from_date else None,
        "to_date": str(request.window.to_date) if request.window.to_date else None,
        "period": request.window.period.value if request.window.period else None,
        "year": request.window.year,
        "input_mode": request.input_mode.value,
    }


def _accepted_response(calculation_id) -> ReturnsSeriesAcceptedResponse:
    return ReturnsSeriesAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/integration/returns/series/results/{calculation_id}",
    )


@router.post(
    "/returns/series",
    response_model=ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse,
    summary="Get canonical return series for downstream analytics",
    description=(
        "Returns canonical portfolio/benchmark/risk-free return time series for stateful analytics consumers. "
        "Supports stateless (request-supplied inputs) and stateful (platform-sourced inputs) modes."
    ),
)
async def get_returns_series(request: ReturnsSeriesRequest) -> ReturnsSeriesResponse | JSONResponse:
    input_fingerprint, calculation_hash = generate_canonical_hash(request, "returns-series-v1")
    execution_registry.create_schema()
    compute_job_store.create_schema()
    execution_mode = "async" if _should_offload_returns_series(request) else "sync"
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="ReturnsSeries",
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
            analytics_type="ReturnsSeries",
            request_payload=request.model_dump(mode="json"),
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "submission",
            details={"offload_reason": "long_window_stateful_returns_series"},
        )
        accepted = _accepted_response(request.calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))

    return await calculate_returns_series(request)


@router.get(
    "/returns/series/results/{calculation_id}",
    response_model=ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse,
    summary="Retrieve async returns-series result",
    description="Returns the final returns-series payload for an async executor job, or a pending handle while execution is in progress.",
)
async def get_returns_series_result(calculation_id: UUID) -> ReturnsSeriesResponse | JSONResponse:
    job = compute_job_store.get_job(calculation_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Async returns-series result not found for the given calculation_id.",
        )
    if job.job_status in {ComputeJobStatus.PENDING, ComputeJobStatus.RUNNING}:
        accepted = _accepted_response(calculation_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump(mode="json"))
    if job.job_status == ComputeJobStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message or "Async returns-series execution failed.",
        )
    return ReturnsSeriesResponse.model_validate(job.response_payload)
