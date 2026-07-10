from __future__ import annotations

from typing import NoReturn

from app.core.application_responses import ApplicationHttpResponse
from app.core.async_polling import recommended_async_poll_after_seconds
from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkInputMode, benchmark_stateless_work_units
from app.models.twr_requests import TWRInputMode
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.models.workspace_summary_responses import WorkspaceSummaryAcceptedResponse, WorkspaceSummaryResponse
from app.services.analytics_workflow_commands import WorkspaceSummaryWorkflowCommand, workflow_request
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
from app.services.async_observability_context import async_observability_request_payload
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from app.services.workspace_summary_service import (
    calculate_workspace_summary,
    workspace_longest_requested_window_days,
)
from core.errors import APIInternalServerError


def accepted_workspace_summary_response(calculation_id) -> WorkspaceSummaryAcceptedResponse:
    return WorkspaceSummaryAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/workspace-summary/results/{calculation_id}",
        recommended_poll_after_seconds=recommended_async_poll_after_seconds(),
    )


def workspace_requested_benchmark_work_units(request: WorkspaceSummaryRequest) -> int:
    benchmark = request.benchmark
    if benchmark is None or benchmark.input_mode != BenchmarkInputMode.STATELESS or benchmark.stateless_input is None:
        return 0
    return benchmark_stateless_work_units(
        stateless_input=benchmark.stateless_input,
        return_source=benchmark.return_source,
    )


def workspace_requested_input_count(request: WorkspaceSummaryRequest) -> int:
    valuation_points = (
        len(request.resolved_stateless_valuation_points()) if request.input_mode == TWRInputMode.STATELESS else 0
    )
    return valuation_points + workspace_requested_benchmark_work_units(request)


def workspace_requested_window(request: WorkspaceSummaryRequest) -> dict[str, object]:
    return {
        "report_end_date": str(request.report_end_date),
        "requested_periods": [item.period.value for item in request.periods],
        "input_mode": request.input_mode.value,
        "include_benchmark": request.include_benchmark,
        "input_count": workspace_requested_input_count(request),
        "longest_window_days": workspace_longest_requested_window_days(request),
    }


def should_offload_workspace_summary(request: WorkspaceSummaryRequest) -> bool:
    settings = get_settings()
    return (
        request.input_mode == TWRInputMode.STATEFUL
        and workspace_longest_requested_window_days(request) >= settings.WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS
    ) or (workspace_requested_input_count(request) >= settings.WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT)


def workspace_offload_reason(request: WorkspaceSummaryRequest) -> str:
    if request.input_mode == TWRInputMode.STATEFUL:
        return "long_window_stateful_workspace_summary"
    return "large_workspace_summary_input_set"


def calculate_workspace_summary_workflow(
    command: WorkspaceSummaryWorkflowCommand,
) -> WorkspaceSummaryResponse | ApplicationHttpResponse:
    """Fence, execute, and map errors for one workspace-summary analytics request."""
    request = workflow_request(command, WorkspaceSummaryRequest)
    settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, settings.APP_VERSION)
    requested_window = workspace_requested_window(request)
    if should_offload_workspace_summary(request):
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
            portfolio_id=request.portfolio_id,
            requested_window=requested_window,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=async_observability_request_payload(request.model_dump(mode="json")),
            offload_reason=workspace_offload_reason(request),
            accepted_response_factory=accepted_workspace_summary_response,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY,
        portfolio_id=request.portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    execution_registry.mark_running(request.calculation_id)
    try:
        return calculate_workspace_summary(request, settings=settings)
    except Exception as exc:
        _raise_workspace_summary_workflow_error(calculation_id=request.calculation_id, exc=exc)


def _raise_workspace_summary_workflow_error(*, calculation_id, exc: Exception) -> NoReturn:
    if _is_http_style_exception(exc):
        record_execution_failure(calculation_id=calculation_id, message=str(getattr(exc, "detail")))
        raise exc

    detail = f"An unexpected server error occurred while calculating workspace summary: {exc}"
    record_execution_failure(calculation_id=calculation_id, message=detail)
    raise APIInternalServerError(detail=detail) from exc


def _is_http_style_exception(exc: Exception) -> bool:
    return hasattr(exc, "status_code") and hasattr(exc, "detail")
