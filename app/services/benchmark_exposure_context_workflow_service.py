from __future__ import annotations

from app.core.config import get_settings
from app.models.benchmark_exposure_context import BenchmarkExposureContextRequest, BenchmarkExposureContextResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_BENCHMARK_EXPOSURE_CONTEXT
from app.services.benchmark_exposure_context_service import build_benchmark_exposure_context
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import execution_stage_failure_detail, is_mappable_application_error
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.submission_fencing_service import register_sync_execution_or_raise
from core.errors import APIInternalServerError

_UNEXPECTED_BENCHMARK_EXPOSURE_FAILURE_DETAIL = (
    "An unexpected server error occurred while building benchmark exposure context: {error}"
)


async def calculate_benchmark_exposure_context_response(
    request: BenchmarkExposureContextRequest,
) -> BenchmarkExposureContextResponse:
    """Run the synchronous benchmark exposure context workflow behind the API boundary."""
    stateful_input_service = build_stateful_input_service(settings=get_settings())
    _register_benchmark_exposure_execution(request)
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    try:
        execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)
        execution_stage_started = True
        response = await build_benchmark_exposure_context(
            request=request,
            stateful_input_service=stateful_input_service,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_EXECUTION,
            details={"row_count": len(response.rows)},
        )
        execution_registry.mark_complete(request.calculation_id)
        return response
    except Exception as exc:
        if is_mappable_application_error(exc):
            _record_benchmark_exposure_failure(
                request=request,
                message=execution_stage_failure_detail(exc),
                execution_stage_started=execution_stage_started,
            )
            raise
        failure_detail = _UNEXPECTED_BENCHMARK_EXPOSURE_FAILURE_DETAIL.format(error=exc)
        _record_benchmark_exposure_failure(
            request=request,
            message=failure_detail,
            execution_stage_started=execution_stage_started,
        )
        raise APIInternalServerError(failure_detail) from exc


def _register_benchmark_exposure_execution(request: BenchmarkExposureContextRequest) -> None:
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK_EXPOSURE_CONTEXT,
        portfolio_id=request.portfolio_id,
        requested_window=_benchmark_exposure_requested_window(request),
        input_fingerprint=None,
        calculation_hash=None,
    )


def _benchmark_exposure_requested_window(request: BenchmarkExposureContextRequest) -> dict[str, object]:
    return {
        "as_of_date": str(request.as_of_date),
        "window_start_date": str(request.window.start_date),
        "window_end_date": str(request.window.end_date),
        "frequency": request.frequency.value,
        "grouping_dimensions": [dimension.value for dimension in request.grouping_dimensions],
        "benchmark_id": request.benchmark_id,
        "reporting_currency": request.reporting_currency,
    }


def _record_benchmark_exposure_failure(
    *,
    request: BenchmarkExposureContextRequest,
    message: str,
    execution_stage_started: bool,
) -> None:
    record_execution_failure(
        calculation_id=request.calculation_id,
        message=message,
        execution_stage_started=execution_stage_started,
    )
