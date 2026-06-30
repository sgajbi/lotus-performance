from dataclasses import dataclass
from typing import NoReturn

from app.core.application_responses import ApplicationHttpResponse
from app.core.config import get_settings
from app.models.benchmark_analytics_requests import (
    BenchmarkInputMode,
    BenchmarkReturnSource,
    benchmark_stateless_work_units,
)
from app.models.responses import PerformanceResponse, TWRAcceptedResponse
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode, TWRResolvedExecutionRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR
from app.services.async_observability_context import async_observability_request_payload
from app.services.engine_exception_mapping_service import map_engine_exception_to_http_error
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import is_mappable_application_error
from app.services.reproducibility_service import generate_request_fingerprint, generate_value_fingerprint
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from app.services.twr_mode_service import resolve_twr_request
from app.services.twr_service import calculate_twr_response
from core.errors import APIError, APIInternalServerError


@dataclass(frozen=True)
class _TWRSyncExecutionStart:
    requested_window: dict[str, object]
    replay_response: ApplicationHttpResponse | None


@dataclass(frozen=True)
class _TWRWorkflowSubmissionContext:
    input_fingerprint: str
    calculation_hash: str
    source_request_fingerprint: str
    requested_window: dict[str, object]


def accepted_twr_response(calculation_id) -> TWRAcceptedResponse:
    return TWRAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/twr/results/{calculation_id}",
    )


def generate_twr_request_hashes(request: TWRAnalyticsRequest, *, engine_version: str) -> tuple[str, str]:
    if request.input_mode == TWRInputMode.STATEFUL:
        canonical_payload = request.model_dump(
            exclude={"performance_start_date"},
            mode="json",
        )
        return generate_value_fingerprint(canonical_payload, engine_version)
    return generate_request_fingerprint(request, engine_version)


def build_resolved_twr_identity_payload(
    *,
    performance_request,
    benchmark_request,
) -> TWRResolvedExecutionRequest:
    return TWRResolvedExecutionRequest(
        portfolio=performance_request,
        benchmark=benchmark_request,
    )


def twr_benchmark_requested(request: TWRAnalyticsRequest) -> bool:
    return request.include_benchmark or request.benchmark is not None


def twr_requested_benchmark_input_mode(request: TWRAnalyticsRequest) -> str | None:
    if request.benchmark is not None:
        return request.benchmark.input_mode.value
    if request.include_benchmark and request.input_mode == TWRInputMode.STATEFUL:
        return BenchmarkInputMode.STATEFUL.value
    return None


def twr_requested_benchmark_return_source(request: TWRAnalyticsRequest) -> str | None:
    if not twr_benchmark_requested(request):
        return None
    if request.benchmark is not None:
        return request.benchmark.return_source.value
    return BenchmarkReturnSource.CALCULATED.value


def twr_requested_benchmark_work_units(request: TWRAnalyticsRequest) -> int:
    if request.benchmark is None or request.benchmark.input_mode != BenchmarkInputMode.STATELESS:
        return 0
    stateless_input = request.benchmark.stateless_input
    if stateless_input is None:
        return 0
    return benchmark_stateless_work_units(
        stateless_input=stateless_input,
        return_source=request.benchmark.return_source,
    )


def twr_requested_input_count(request: TWRAnalyticsRequest) -> int:
    valuation_points = (
        len(request.stateless_input.valuation_points)
        if request.stateless_input is not None
        else len(request.valuation_points)
    )
    return valuation_points + twr_requested_benchmark_work_units(request)


def twr_resolved_benchmark_work_units(benchmark_request) -> int:
    if benchmark_request is None:
        return 0
    return len(benchmark_request.component_observations) or len(benchmark_request.benchmark_return_points)


def twr_resolved_input_count(performance_request, benchmark_request) -> int:
    return len(performance_request.valuation_points) + twr_resolved_benchmark_work_units(benchmark_request)


def twr_resolved_identity_required(resolved_request) -> bool:
    return resolved_request.input_mode == TWRInputMode.STATEFUL or resolved_request.benchmark_request is not None


def twr_request_artifact_model(
    *,
    request: TWRAnalyticsRequest,
    resolved_request,
    resolved_twr_identity_payload: TWRResolvedExecutionRequest,
):
    if twr_resolved_identity_required(resolved_request):
        return resolved_twr_identity_payload
    return request


def twr_resolved_benchmark_return_source(request: TWRAnalyticsRequest) -> BenchmarkReturnSource:
    if request.benchmark is not None:
        return request.benchmark.return_source
    return BenchmarkReturnSource.CALCULATED


def finalize_twr_resolved_execution_identity(
    *,
    request: TWRAnalyticsRequest,
    resolved_request,
    resolved_twr_identity_payload: TWRResolvedExecutionRequest,
    source_request_fingerprint: str,
    resolved_input_count: int,
    benchmark_work_units: int,
    engine_version: str,
) -> tuple[str, str, ApplicationHttpResponse | None]:
    input_fingerprint, calculation_hash = generate_value_fingerprint(
        resolved_twr_identity_payload,
        engine_version,
    )
    if request.input_mode == TWRInputMode.STATEFUL:
        accepted_response = finalize_resolved_stateful_execution(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_TWR,
            requested_window=build_twr_execution_window(
                request,
                input_count=resolved_input_count,
                source_request_fingerprint=source_request_fingerprint,
                benchmark_id=resolved_request.resolved_benchmark_id,
                benchmark_work_units=benchmark_work_units,
            ),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            resolved_request_payload=async_observability_request_payload(
                {
                    "resolved_request": resolved_twr_identity_payload.model_dump(mode="json"),
                    "source_input_mode": resolved_request.input_mode.value,
                    "benchmark_input_mode": (
                        resolved_request.benchmark_input_mode.value
                        if resolved_request.benchmark_input_mode is not None
                        else None
                    ),
                    "resolved_benchmark_id": resolved_request.resolved_benchmark_id,
                    "benchmark_return_source": twr_resolved_benchmark_return_source(request).value,
                    "portfolio_id": request.portfolio_id,
                }
            ),
            should_offload=should_offload_resolved_twr(resolved_input_count),
            offload_reason="large_resolved_stateful_twr",
            accepted_response_factory=accepted_twr_response,
        )
        return input_fingerprint, calculation_hash, accepted_response

    execution_registry.update_execution_identity(
        request.calculation_id,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    return input_fingerprint, calculation_hash, None


def should_preemptively_offload_stateful_twr(request: TWRAnalyticsRequest) -> bool:
    active_settings = get_settings()
    return (
        request.input_mode == TWRInputMode.STATEFUL
        and request.performance_start_date is not None
        and (request.report_end_date - request.performance_start_date).days >= active_settings.TWR_EXECUTOR_WINDOW_DAYS
    )


def should_offload_twr(request: TWRAnalyticsRequest) -> bool:
    active_settings = get_settings()
    return should_preemptively_offload_stateful_twr(request) or (
        twr_requested_input_count(request) >= active_settings.TWR_EXECUTOR_INPUT_COUNT
    )


def should_offload_resolved_twr(input_count: int) -> bool:
    active_settings = get_settings()
    return input_count >= active_settings.TWR_EXECUTOR_INPUT_COUNT


def build_twr_execution_window(
    request: TWRAnalyticsRequest,
    *,
    input_count: int,
    source_request_fingerprint: str | None = None,
    benchmark_id: str | None = None,
    benchmark_work_units: int | None = None,
) -> dict[str, object]:
    requested_window: dict[str, object] = {
        "performance_start_date": (
            str(request.performance_start_date) if request.performance_start_date is not None else None
        ),
        "report_start_date": str(request.report_start_date) if request.report_start_date else None,
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "input_mode": request.input_mode.value,
        "include_benchmark": request.include_benchmark,
        "input_count": input_count,
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    requested_window.update(
        _twr_execution_window_benchmark_fields(
            request,
            benchmark_id=benchmark_id,
            benchmark_work_units=benchmark_work_units,
        )
    )
    return requested_window


def _twr_execution_window_benchmark_fields(
    request: TWRAnalyticsRequest,
    *,
    benchmark_id: str | None = None,
    benchmark_work_units: int | None = None,
) -> dict[str, object]:
    benchmark_fields: dict[str, object] = {}
    requested_benchmark_id = _twr_execution_window_benchmark_id(
        request,
        benchmark_id=benchmark_id,
    )
    if requested_benchmark_id is not None:
        benchmark_fields["benchmark_id"] = requested_benchmark_id
    benchmark_input_mode = twr_requested_benchmark_input_mode(request)
    if benchmark_input_mode is not None:
        benchmark_fields["benchmark_input_mode"] = benchmark_input_mode
    benchmark_return_source = twr_requested_benchmark_return_source(request)
    if benchmark_return_source is not None:
        benchmark_fields["benchmark_return_source"] = benchmark_return_source
    if benchmark_work_units is not None:
        benchmark_fields["benchmark_work_units"] = benchmark_work_units
    return benchmark_fields


def _twr_execution_window_benchmark_id(
    request: TWRAnalyticsRequest,
    *,
    benchmark_id: str | None = None,
) -> str | None:
    if benchmark_id is not None:
        return benchmark_id
    if request.benchmark is not None:
        return request.benchmark.benchmark_id
    return None


async def calculate_twr_workflow(request: TWRAnalyticsRequest) -> PerformanceResponse | ApplicationHttpResponse:
    """Resolve, fence, execute, and map errors for one TWR analytics request."""
    settings = get_settings()
    submission_context = _build_twr_workflow_submission_context(
        request,
        engine_version=settings.APP_VERSION,
    )
    pre_resolution_response = _register_pre_resolution_twr_submission(
        request=request,
        submission_context=submission_context,
    )
    if pre_resolution_response is not None:
        return pre_resolution_response

    replay_response = _register_twr_sync_submission(
        request=request,
        submission_context=submission_context,
    )
    if replay_response is not None:
        return replay_response

    try:
        resolved_request = await resolve_twr_request(request, settings=settings)
        return _calculate_twr_resolved_response(
            request=request,
            resolved_request=resolved_request,
            source_request_fingerprint=submission_context.source_request_fingerprint,
            input_fingerprint=submission_context.input_fingerprint,
            calculation_hash=submission_context.calculation_hash,
            engine_version=settings.APP_VERSION,
        )
    except Exception as exc:
        _raise_twr_workflow_http_error(
            calculation_id=request.calculation_id,
            exc=exc,
        )


def _build_twr_workflow_submission_context(
    request: TWRAnalyticsRequest,
    *,
    engine_version: str,
) -> _TWRWorkflowSubmissionContext:
    input_fingerprint, calculation_hash = generate_twr_request_hashes(request, engine_version=engine_version)
    return _TWRWorkflowSubmissionContext(
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        source_request_fingerprint=input_fingerprint,
        requested_window=build_twr_execution_window(
            request,
            input_count=twr_requested_input_count(request),
        ),
    )


def _register_pre_resolution_twr_submission(
    *,
    request: TWRAnalyticsRequest,
    submission_context: _TWRWorkflowSubmissionContext,
) -> ApplicationHttpResponse | None:
    if not should_offload_twr(request):
        return None
    return register_async_submission_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_TWR,
        portfolio_id=request.portfolio_id,
        requested_window=submission_context.requested_window,
        input_fingerprint=submission_context.input_fingerprint,
        calculation_hash=submission_context.calculation_hash,
        request_payload=async_observability_request_payload(request.model_dump(mode="json")),
        offload_reason=_twr_pre_resolution_offload_reason(request),
        accepted_response_factory=accepted_twr_response,
    )


def _register_twr_sync_submission(
    *,
    request: TWRAnalyticsRequest,
    submission_context: _TWRWorkflowSubmissionContext,
) -> ApplicationHttpResponse | None:
    sync_start = _prepare_twr_sync_execution_start(
        request=request,
        requested_window=submission_context.requested_window,
        source_request_fingerprint=submission_context.source_request_fingerprint,
    )
    if sync_start.replay_response is not None:
        return sync_start.replay_response

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_TWR,
        portfolio_id=request.portfolio_id,
        requested_window=sync_start.requested_window,
        input_fingerprint=submission_context.input_fingerprint,
        calculation_hash=submission_context.calculation_hash,
    )
    return None


def _raise_twr_workflow_http_error(*, calculation_id, exc: Exception) -> NoReturn:
    if isinstance(exc, APIError):
        record_execution_failure(
            calculation_id=calculation_id,
            message=str(exc.detail),
        )
        raise

    if is_mappable_application_error(exc):
        detail = getattr(exc, "detail")
        record_execution_failure(
            calculation_id=calculation_id,
            message=str(detail),
        )
        raise APIError(
            status_code=int(getattr(exc, "status_code")),
            detail=detail,
        ) from exc

    mapped_engine_error = map_engine_exception_to_http_error(exc)
    if mapped_engine_error is not None:
        record_execution_failure(
            calculation_id=calculation_id,
            message=mapped_engine_error.failure_message,
        )
        raise APIError(status_code=mapped_engine_error.status_code, detail=mapped_engine_error.detail) from exc

    detail = f"An unexpected server error occurred: {str(exc)}"
    record_execution_failure(
        calculation_id=calculation_id,
        message=detail,
    )
    raise APIInternalServerError(detail) from exc


def _twr_pre_resolution_offload_reason(request: TWRAnalyticsRequest) -> str:
    if request.input_mode == TWRInputMode.STATEFUL:
        return "long_window_stateful_twr"
    return "large_twr_input_set"


def _calculate_twr_resolved_response(
    *,
    request: TWRAnalyticsRequest,
    resolved_request,
    source_request_fingerprint: str,
    input_fingerprint: str,
    calculation_hash: str,
    engine_version: str,
) -> PerformanceResponse | ApplicationHttpResponse:
    performance_request = resolved_request.performance_request
    resolved_twr_identity_payload = build_resolved_twr_identity_payload(
        performance_request=performance_request,
        benchmark_request=resolved_request.benchmark_request,
    )
    request_artifact_model = twr_request_artifact_model(
        request=request,
        resolved_request=resolved_request,
        resolved_twr_identity_payload=resolved_twr_identity_payload,
    )
    resolved_input_count = twr_resolved_input_count(
        performance_request,
        resolved_request.benchmark_request,
    )
    benchmark_work_units = twr_resolved_benchmark_work_units(resolved_request.benchmark_request)
    if twr_resolved_identity_required(resolved_request):
        input_fingerprint, calculation_hash, accepted_response = finalize_twr_resolved_execution_identity(
            request=request,
            resolved_request=resolved_request,
            resolved_twr_identity_payload=resolved_twr_identity_payload,
            source_request_fingerprint=source_request_fingerprint,
            resolved_input_count=resolved_input_count,
            benchmark_work_units=benchmark_work_units,
            engine_version=engine_version,
        )
        if accepted_response is not None:
            return accepted_response
    return calculate_twr_response(
        performance_request,
        portfolio_id=request.portfolio_id,
        input_mode=resolved_request.input_mode,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        engine_version=engine_version,
        request_artifact_model=request_artifact_model,
        benchmark_request=resolved_request.benchmark_request,
        benchmark_input_mode=resolved_request.benchmark_input_mode,
        resolved_benchmark_id=resolved_request.resolved_benchmark_id,
        benchmark_return_source=twr_resolved_benchmark_return_source(request),
    )


def _prepare_twr_sync_execution_start(
    *,
    request: TWRAnalyticsRequest,
    requested_window: dict[str, object],
    source_request_fingerprint: str,
) -> _TWRSyncExecutionStart:
    if request.input_mode != TWRInputMode.STATEFUL:
        return _TWRSyncExecutionStart(requested_window=requested_window, replay_response=None)

    replay_response = replay_promoted_stateful_async_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_TWR,
        source_request_fingerprint=source_request_fingerprint,
        accepted_response_factory=accepted_twr_response,
    )
    if replay_response is not None:
        return _TWRSyncExecutionStart(requested_window=requested_window, replay_response=replay_response)

    return _TWRSyncExecutionStart(
        requested_window=build_twr_execution_window(
            request,
            input_count=twr_requested_input_count(request),
            source_request_fingerprint=source_request_fingerprint,
        ),
        replay_response=None,
    )
