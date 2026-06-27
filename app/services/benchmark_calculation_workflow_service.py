from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.benchmark_responses import BenchmarkAcceptedResponse, BenchmarkPerformanceResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_BENCHMARK
from app.services.benchmark_mode_service import ResolvedBenchmarkRequest, resolve_benchmark_request
from app.services.benchmark_service import calculate_benchmark_response
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)


@dataclass(frozen=True)
class _ResolvedBenchmarkExecutionContext:
    resolved_request: ResolvedBenchmarkRequest
    benchmark_request: BenchmarkPerformanceRequest
    request_model_for_lineage: BenchmarkAnalyticsRequest | BenchmarkPerformanceRequest
    input_fingerprint: str
    calculation_hash: str
    should_persist_request: bool


def accepted_benchmark_response(calculation_id) -> BenchmarkAcceptedResponse:
    return BenchmarkAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/benchmark/results/{calculation_id}",
    )


def should_persist_resolved_benchmark_request(request: BenchmarkAnalyticsRequest) -> bool:
    if request.input_mode == BenchmarkInputMode.STATEFUL:
        return True
    stateless_input = request.stateless_input
    if stateless_input is None:
        return False
    return bool(stateless_input.component_price_points)


def should_preemptively_offload_stateful_benchmark(request: BenchmarkAnalyticsRequest) -> bool:
    settings = get_settings()
    return (request.report_end_date - request.benchmark_start_date).days >= settings.BENCHMARK_EXECUTOR_WINDOW_DAYS


def benchmark_requested_input_count(request: BenchmarkAnalyticsRequest) -> int:
    if request.stateless_input is None:
        return 0
    return (
        len(request.stateless_input.component_observations)
        or len(request.stateless_input.component_price_points)
        or len(request.stateless_input.benchmark_return_points)
    )


def should_offload_resolved_benchmark(input_count: int) -> bool:
    settings = get_settings()
    return input_count >= settings.BENCHMARK_EXECUTOR_INPUT_COUNT


def should_offload_benchmark(request: BenchmarkAnalyticsRequest) -> bool:
    settings = get_settings()
    return should_preemptively_offload_stateful_benchmark(request) or (
        benchmark_requested_input_count(request) >= settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    )


def build_benchmark_execution_window(
    request: BenchmarkAnalyticsRequest,
    *,
    source_request_fingerprint: str | None = None,
    input_count: int | None = None,
) -> dict[str, object]:
    requested_window: dict[str, object] = {
        "benchmark_start_date": str(request.benchmark_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "return_source": request.return_source.value,
        "input_mode": request.input_mode.value,
        "input_count": benchmark_requested_input_count(request),
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    if input_count is not None:
        requested_window["input_count"] = input_count
    return requested_window


async def _resolve_benchmark_execution_context(
    *,
    request: BenchmarkAnalyticsRequest,
    settings,
    input_fingerprint: str,
    calculation_hash: str,
) -> _ResolvedBenchmarkExecutionContext:
    resolved_request = await resolve_benchmark_request(request, settings=settings)
    benchmark_request = resolved_request.benchmark_request
    should_persist_request = should_persist_resolved_benchmark_request(request)
    request_model_for_lineage = benchmark_request if should_persist_request else request
    if should_persist_request:
        input_fingerprint, calculation_hash = generate_request_fingerprint(
            benchmark_request,
            settings.APP_VERSION,
        )
    return _ResolvedBenchmarkExecutionContext(
        resolved_request=resolved_request,
        benchmark_request=benchmark_request,
        request_model_for_lineage=request_model_for_lineage,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        should_persist_request=should_persist_request,
    )


def _raise_benchmark_workflow_failure(request: BenchmarkAnalyticsRequest, exc: Exception) -> NoReturn:
    if isinstance(exc, HTTPException):
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
        )
        raise exc
    record_execution_failure(
        calculation_id=request.calculation_id,
        message=f"An unexpected server error occurred: {exc}",
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"An unexpected server error occurred: {exc}",
    ) from exc


async def _calculate_promoted_stateful_benchmark_workflow(
    *,
    request: BenchmarkAnalyticsRequest,
    settings,
    source_request_fingerprint: str,
    input_fingerprint: str,
    calculation_hash: str,
) -> BenchmarkPerformanceResponse | BenchmarkAcceptedResponse:
    replay_response = replay_promoted_stateful_async_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        source_request_fingerprint=input_fingerprint,
        accepted_response_factory=accepted_benchmark_response,
    )
    if replay_response is not None:
        return replay_response

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        portfolio_id=request.benchmark_id,
        requested_window=build_benchmark_execution_window(
            request,
            source_request_fingerprint=source_request_fingerprint,
        ),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    try:
        resolved_context = await _resolve_benchmark_execution_context(
            request=request,
            settings=settings,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        accepted_response = _finalize_promoted_stateful_benchmark_execution(
            request=request,
            source_request_fingerprint=source_request_fingerprint,
            resolved_context=resolved_context,
        )
        if accepted_response is not None:
            return accepted_response
        return calculate_benchmark_response(
            resolved_context.benchmark_request,
            input_fingerprint=resolved_context.input_fingerprint,
            calculation_hash=resolved_context.calculation_hash,
            input_mode=resolved_context.resolved_request.input_mode,
            engine_version=settings.APP_VERSION,
            request_artifact_model=resolved_context.request_model_for_lineage,
        )
    except Exception as exc:
        _raise_benchmark_workflow_failure(request, exc)


def _finalize_promoted_stateful_benchmark_execution(
    *,
    request: BenchmarkAnalyticsRequest,
    source_request_fingerprint: str,
    resolved_context: _ResolvedBenchmarkExecutionContext,
) -> BenchmarkAcceptedResponse | None:
    return finalize_resolved_stateful_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        requested_window=build_benchmark_execution_window(
            request,
            source_request_fingerprint=source_request_fingerprint,
            input_count=resolved_context.resolved_request.input_count,
        ),
        input_fingerprint=resolved_context.input_fingerprint,
        calculation_hash=resolved_context.calculation_hash,
        resolved_request_payload={
            "resolved_request": resolved_context.benchmark_request.model_dump(mode="json"),
            "source_input_mode": BenchmarkInputMode.STATEFUL.value,
        },
        should_offload=should_offload_resolved_benchmark(resolved_context.resolved_request.input_count),
        offload_reason="large_resolved_stateful_benchmark",
        accepted_response_factory=accepted_benchmark_response,
    )


def _initial_benchmark_async_submission(
    request: BenchmarkAnalyticsRequest,
    *,
    source_request_fingerprint: str,
    source_request_hash: str,
) -> BenchmarkAcceptedResponse | None:
    if not should_offload_benchmark(request):
        return None
    return register_async_submission_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        portfolio_id=request.benchmark_id,
        requested_window=build_benchmark_execution_window(request),
        input_fingerprint=source_request_fingerprint,
        calculation_hash=source_request_hash,
        request_payload=request.model_dump(mode="json"),
        offload_reason=(
            "long_window_stateful_benchmark"
            if request.input_mode == BenchmarkInputMode.STATEFUL
            else "large_benchmark_input_set"
        ),
        accepted_response_factory=accepted_benchmark_response,
    )


async def _calculate_initial_sync_benchmark_workflow(
    *,
    request: BenchmarkAnalyticsRequest,
    settings,
    source_request_fingerprint: str,
    source_request_hash: str,
) -> BenchmarkPerformanceResponse:
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
        portfolio_id=request.benchmark_id,
        requested_window=build_benchmark_execution_window(request),
        input_fingerprint=source_request_fingerprint,
        calculation_hash=source_request_hash,
    )
    try:
        resolved_context = await _resolve_benchmark_execution_context(
            request=request,
            settings=settings,
            input_fingerprint=source_request_fingerprint,
            calculation_hash=source_request_hash,
        )
        if resolved_context.should_persist_request:
            execution_registry.update_execution_identity(
                request.calculation_id,
                input_fingerprint=resolved_context.input_fingerprint,
                calculation_hash=resolved_context.calculation_hash,
            )
        return calculate_benchmark_response(
            resolved_context.benchmark_request,
            input_fingerprint=resolved_context.input_fingerprint,
            calculation_hash=resolved_context.calculation_hash,
            input_mode=resolved_context.resolved_request.input_mode,
            engine_version=settings.APP_VERSION,
            request_artifact_model=resolved_context.request_model_for_lineage,
        )
    except Exception as exc:
        _raise_benchmark_workflow_failure(request, exc)


async def calculate_benchmark_workflow(
    request: BenchmarkAnalyticsRequest,
) -> BenchmarkPerformanceResponse | BenchmarkAcceptedResponse:
    """Resolve, fence, execute, and map errors for one benchmark analytics request."""
    settings = get_settings()
    source_request_fingerprint, source_request_hash = generate_request_fingerprint(request, settings.APP_VERSION)
    input_fingerprint, calculation_hash = source_request_fingerprint, source_request_hash
    if request.input_mode == BenchmarkInputMode.STATEFUL and not should_preemptively_offload_stateful_benchmark(
        request
    ):
        return await _calculate_promoted_stateful_benchmark_workflow(
            request=request,
            settings=settings,
            source_request_fingerprint=source_request_fingerprint,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )

    accepted_response = _initial_benchmark_async_submission(
        request,
        source_request_fingerprint=source_request_fingerprint,
        source_request_hash=source_request_hash,
    )
    if accepted_response is not None:
        return accepted_response

    return await _calculate_initial_sync_benchmark_workflow(
        request=request,
        settings=settings,
        source_request_fingerprint=input_fingerprint,
        source_request_hash=calculation_hash,
    )
