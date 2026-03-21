from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_responses import (
    BenchmarkAcceptedResponse,
    BenchmarkPerformanceResponse,
)
from app.services.async_result_service import resolve_async_result
from app.services.benchmark_mode_service import resolve_benchmark_request
from app.services.benchmark_service import calculate_benchmark_response
from app.services.execution_lifecycle_service import (
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from core.repro import generate_canonical_hash

router = APIRouter(tags=["Performance"])


@router.post(
    "/benchmark",
    response_model=BenchmarkPerformanceResponse | BenchmarkAcceptedResponse,
    summary="Calculate benchmark performance",
)
async def calculate_benchmark_endpoint(
    request: BenchmarkAnalyticsRequest,
) -> BenchmarkPerformanceResponse | JSONResponse:
    settings = get_settings()
    source_request_fingerprint, source_request_hash = generate_canonical_hash(request, settings.APP_VERSION)
    input_fingerprint, calculation_hash = source_request_fingerprint, source_request_hash
    if request.input_mode == BenchmarkInputMode.STATEFUL and not _should_preemptively_offload_stateful_benchmark(
        request
    ):
        replay_response = replay_promoted_stateful_async_execution(
            calculation_id=request.calculation_id,
            analytics_type="BENCHMARK",
            source_request_fingerprint=input_fingerprint,
            accepted_response_factory=_accepted_response,
        )
        if replay_response is not None:
            return replay_response

        register_sync_execution_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="BENCHMARK",
            portfolio_id=request.benchmark_id,
            requested_window=_build_execution_window(
                request,
                source_request_fingerprint=source_request_fingerprint,
            ),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        try:
            resolved_request = await resolve_benchmark_request(request, settings=settings)
            benchmark_request = resolved_request.benchmark_request
            request_model_for_lineage = (
                benchmark_request if _should_persist_resolved_benchmark_request(request) else request
            )
            if _should_persist_resolved_benchmark_request(request):
                input_fingerprint, calculation_hash = generate_canonical_hash(
                    benchmark_request,
                    settings.APP_VERSION,
                )
            accepted_response = finalize_resolved_stateful_execution(
                calculation_id=request.calculation_id,
                analytics_type="BENCHMARK",
                requested_window=_build_execution_window(
                    request,
                    source_request_fingerprint=source_request_fingerprint,
                    input_count=resolved_request.input_count,
                ),
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                resolved_request_payload={
                    "resolved_request": benchmark_request.model_dump(mode="json"),
                    "source_input_mode": BenchmarkInputMode.STATEFUL.value,
                },
                should_offload=_should_offload_resolved_benchmark(resolved_request.input_count),
                offload_reason="large_resolved_stateful_benchmark",
                accepted_response_factory=_accepted_response,
            )
            if accepted_response is not None:
                return accepted_response
            return calculate_benchmark_response(
                benchmark_request,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
                input_mode=resolved_request.input_mode,
                engine_version=settings.APP_VERSION,
                request_artifact_model=request_model_for_lineage,
            )
        except HTTPException as exc:
            record_execution_failure(
                calculation_id=request.calculation_id,
                message=str(exc.detail),
            )
            raise
        except Exception as exc:
            record_execution_failure(
                calculation_id=request.calculation_id,
                message=f"An unexpected server error occurred: {exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected server error occurred: {exc}",
            ) from exc

    if _should_offload_benchmark(request):
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type="BENCHMARK",
            portfolio_id=request.benchmark_id,
            requested_window=_build_execution_window(request),
            input_fingerprint=source_request_fingerprint,
            calculation_hash=source_request_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=(
                "long_window_stateful_benchmark"
                if request.input_mode == BenchmarkInputMode.STATEFUL
                else "large_benchmark_input_set"
            ),
            accepted_response_factory=_accepted_response,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type="BENCHMARK",
        portfolio_id=request.benchmark_id,
        requested_window=_build_execution_window(request),
        input_fingerprint=source_request_fingerprint,
        calculation_hash=source_request_hash,
    )
    try:
        resolved_request = await resolve_benchmark_request(request, settings=settings)
        benchmark_request = resolved_request.benchmark_request
        request_model_for_lineage = (
            benchmark_request if _should_persist_resolved_benchmark_request(request) else request
        )
        if _should_persist_resolved_benchmark_request(request):
            input_fingerprint, calculation_hash = generate_canonical_hash(
                benchmark_request,
                settings.APP_VERSION,
            )
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=input_fingerprint,
                calculation_hash=calculation_hash,
            )
        return calculate_benchmark_response(
            benchmark_request,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            input_mode=resolved_request.input_mode,
            engine_version=settings.APP_VERSION,
            request_artifact_model=request_model_for_lineage,
        )
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
        )
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected server error occurred: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred: {exc}",
        ) from exc


@router.get(
    "/benchmark/results/{calculation_id}",
    response_model=BenchmarkPerformanceResponse | BenchmarkAcceptedResponse,
    summary="Retrieve async benchmark result",
)
async def get_benchmark_result(calculation_id: UUID) -> BenchmarkPerformanceResponse | JSONResponse:
    return resolve_async_result(
        calculation_id=calculation_id,
        response_model=BenchmarkPerformanceResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="Async benchmark result not found for the given calculation_id.",
        failed_detail="Async benchmark execution failed.",
    )


def _should_persist_resolved_benchmark_request(request: BenchmarkAnalyticsRequest) -> bool:
    if request.input_mode == BenchmarkInputMode.STATEFUL:
        return True
    stateless_input = request.stateless_input
    if stateless_input is None:
        return False
    return bool(stateless_input.component_price_points)


def _should_preemptively_offload_stateful_benchmark(request: BenchmarkAnalyticsRequest) -> bool:
    settings = get_settings()
    return (request.report_end_date - request.benchmark_start_date).days >= settings.BENCHMARK_EXECUTOR_WINDOW_DAYS


def _benchmark_requested_input_count(request: BenchmarkAnalyticsRequest) -> int:
    if request.stateless_input is None:
        return 0
    return (
        len(request.stateless_input.component_observations)
        or len(request.stateless_input.component_price_points)
        or len(request.stateless_input.benchmark_return_points)
    )


def _should_offload_resolved_benchmark(input_count: int) -> bool:
    settings = get_settings()
    return input_count >= settings.BENCHMARK_EXECUTOR_INPUT_COUNT


def _should_offload_benchmark(request: BenchmarkAnalyticsRequest) -> bool:
    settings = get_settings()
    return _should_preemptively_offload_stateful_benchmark(request) or (
        _benchmark_requested_input_count(request) >= settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    )


def _build_execution_window(
    request: BenchmarkAnalyticsRequest,
    *,
    source_request_fingerprint: str | None = None,
    input_count: int | None = None,
) -> dict[str, object]:
    requested_window = {
        "benchmark_start_date": str(request.benchmark_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "return_source": request.return_source.value,
        "input_mode": request.input_mode.value,
        "input_count": _benchmark_requested_input_count(request),
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    if input_count is not None:
        requested_window["input_count"] = input_count
    return requested_window


def _accepted_response(calculation_id) -> BenchmarkAcceptedResponse:
    return BenchmarkAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/benchmark/results/{calculation_id}",
    )
