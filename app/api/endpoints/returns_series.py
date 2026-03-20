from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.returns_series import (
    InputMode,
    ReturnsSeriesAcceptedResponse,
    ReturnsSeriesRequest,
    ReturnsSeriesResponse,
)
from app.services.async_result_service import resolve_async_result
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
    resolve_stateful_returns_series_request,
    resolve_window,
    to_dataframe,
)
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from core.repro import generate_canonical_hash

router = APIRouter(tags=["Integration"])

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
    active_settings = get_settings()
    if request.input_mode.value != "stateful":
        return False
    resolved_window = _resolve_window(request)
    return (
        resolved_window.end_date - resolved_window.start_date
    ).days >= active_settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS


def _should_offload_resolved_returns_series(input_count: int) -> bool:
    active_settings = get_settings()
    return input_count >= active_settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT


def _build_execution_window(
    request: ReturnsSeriesRequest,
    *,
    source_request_fingerprint: str | None = None,
    input_count: int | None = None,
    benchmark_id: str | None = None,
    benchmark_return_source: str | None = None,
    benchmark_work_units: int | None = None,
) -> dict[str, object]:
    requested_window: dict[str, object] = {
        "mode": request.window.mode.value,
        "from_date": str(request.window.from_date) if request.window.from_date else None,
        "to_date": str(request.window.to_date) if request.window.to_date else None,
        "period": request.window.period.value if request.window.period else None,
        "year": request.window.year,
        "input_mode": request.input_mode.value,
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    if input_count is not None:
        requested_window["input_count"] = input_count
    if benchmark_id is not None:
        requested_window["benchmark_id"] = benchmark_id
    if benchmark_return_source is not None:
        requested_window["benchmark_return_source"] = benchmark_return_source
    if benchmark_work_units is not None:
        requested_window["benchmark_work_units"] = benchmark_work_units
    return requested_window


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
    if request.input_mode == InputMode.STATEFUL and not _should_offload_returns_series(request):
        replay_response = replay_promoted_stateful_async_execution(
            calculation_id=request.calculation_id,
            analytics_type="ReturnsSeries",
            source_request_fingerprint=input_fingerprint,
            accepted_response_factory=_accepted_response,
        )
        if replay_response is not None:
            return replay_response
        register_sync_execution_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="ReturnsSeries",
            portfolio_id=request.portfolio_id,
            requested_window=_build_execution_window(
                request,
                source_request_fingerprint=input_fingerprint,
            ),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        try:
            resolved = await resolve_stateful_returns_series_request(request)
            resolved_input_fingerprint, resolved_calculation_hash = generate_canonical_hash(
                resolved.identity_payload,
                "returns-series-v1",
            )
            accepted_response = finalize_resolved_stateful_execution(
                calculation_id=request.calculation_id,
                analytics_type="ReturnsSeries",
                requested_window=_build_execution_window(
                    request,
                    source_request_fingerprint=input_fingerprint,
                    input_count=resolved.input_count,
                    benchmark_id=resolved.resolved_benchmark_id,
                    benchmark_return_source=resolved.resolved_benchmark_return_source,
                    benchmark_work_units=resolved.benchmark_work_units,
                ),
                input_fingerprint=resolved_input_fingerprint,
                calculation_hash=resolved_calculation_hash,
                resolved_request_payload={
                    "resolved_request": resolved.request.model_dump(mode="json"),
                    "source_input_mode": InputMode.STATEFUL.value,
                },
                should_offload=_should_offload_resolved_returns_series(resolved.input_count),
                offload_reason="large_resolved_stateful_returns_series",
                accepted_response_factory=_accepted_response,
            )
            if accepted_response is not None:
                return accepted_response
            return await calculate_returns_series(
                resolved.request,
                source_input_mode=InputMode.STATEFUL,
                resolved_benchmark_id_override=resolved.resolved_benchmark_id,
                resolved_benchmark_return_source_override=resolved.resolved_benchmark_return_source,
            )
        except Exception as exc:
            message = exc.detail["message"] if hasattr(exc, "detail") and isinstance(exc.detail, dict) and "message" in exc.detail else str(getattr(exc, "detail", exc))
            execution_registry.fail_in_progress_stages(request.calculation_id, message)
            execution_registry.mark_failed(request.calculation_id, message)
            raise
    execution_mode = "async" if _should_offload_returns_series(request) else "sync"
    if execution_mode == "async":
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="ReturnsSeries",
            portfolio_id=request.portfolio_id,
            requested_window=_build_execution_window(request),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason="long_window_stateful_returns_series",
            accepted_response_factory=_accepted_response,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id=request.portfolio_id,
        requested_window=_build_execution_window(request),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

    return await calculate_returns_series(request)


@router.get(
    "/returns/series/results/{calculation_id}",
    response_model=ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse,
    summary="Retrieve async returns-series result",
    description="Returns the final returns-series payload for an async executor job, or a pending handle while execution is in progress.",
)
async def get_returns_series_result(calculation_id: UUID) -> ReturnsSeriesResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=ReturnsSeriesResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="Async returns-series result not found for the given calculation_id.",
        failed_detail="Async returns-series execution failed.",
    )
