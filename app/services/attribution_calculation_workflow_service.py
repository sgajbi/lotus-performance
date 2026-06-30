from __future__ import annotations

from typing import Protocol, cast

from app.core.application_responses import ApplicationHttpResponse
from app.core.config import Settings, get_settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.attribution_responses import AttributionAcceptedResponse, AttributionResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_ATTRIBUTION
from app.services.async_observability_context import async_observability_request_payload
from app.services.attribution_mode_service import ResolvedAttributionRequest, resolve_attribution_request
from app.services.attribution_service import calculate_attribution
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_stage_errors import execution_stage_failure_detail, is_mappable_application_error
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)
from core.errors import APIInternalServerError


class _AttributionWorkflowSettings(Protocol):
    APP_VERSION: str


def accepted_attribution_response(calculation_id) -> AttributionAcceptedResponse:
    return AttributionAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/attribution/results/{calculation_id}",
    )


def _stateless_attribution_input_count(request: AttributionAnalyticsRequest | AttributionRequest) -> int:
    return (
        len(request.instruments_data or [])
        + len(request.portfolio_groups_data or [])
        + len(request.benchmark_groups_data or [])
    )


def attribution_input_count(request: AttributionAnalyticsRequest | AttributionRequest) -> int:
    input_mode = getattr(request, "input_mode", AttributionInputMode.STATELESS)
    if input_mode == AttributionInputMode.STATEFUL:
        return 0
    stateless_input = getattr(request, "stateless_input", None)
    if stateless_input is not None:
        return _stateless_attribution_input_count(stateless_input)
    return _stateless_attribution_input_count(request)


def should_offload_attribution(request: AttributionAnalyticsRequest | AttributionRequest) -> bool:
    active_settings = get_settings()
    input_mode = getattr(request, "input_mode", AttributionInputMode.STATELESS)
    if input_mode == AttributionInputMode.STATEFUL:
        return (
            request.report_end_date - request.report_start_date
        ).days >= active_settings.ATTRIBUTION_EXECUTOR_WINDOW_DAYS
    return attribution_input_count(request) >= active_settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT


def should_offload_resolved_attribution(input_count: int) -> bool:
    active_settings = get_settings()
    return input_count >= active_settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT


def build_attribution_execution_window(
    request: AttributionAnalyticsRequest | AttributionRequest,
    *,
    input_count: int,
    source_request_fingerprint: str | None = None,
    benchmark_id: str | None = None,
    benchmark_return_source: str | None = None,
) -> dict[str, object]:
    requested_window = {
        "report_start_date": str(request.report_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "input_count": input_count,
        "mode": request.mode.value,
        "group_by": request.group_by,
        "input_mode": getattr(request, "input_mode", AttributionInputMode.STATELESS).value,
    }
    requested_window.update(
        _attribution_execution_window_optional_metadata(
            source_request_fingerprint=source_request_fingerprint,
            benchmark_id=benchmark_id,
            benchmark_return_source=benchmark_return_source,
        )
    )
    return requested_window


def _attribution_execution_window_optional_metadata(
    *,
    source_request_fingerprint: str | None = None,
    benchmark_id: str | None = None,
    benchmark_return_source: str | None = None,
) -> dict[str, object]:
    optional_metadata: dict[str, object] = {}
    if source_request_fingerprint is not None:
        optional_metadata["source_request_fingerprint"] = source_request_fingerprint
    if benchmark_id is not None:
        optional_metadata["benchmark_id"] = benchmark_id
    if benchmark_return_source is not None:
        optional_metadata["benchmark_return_source"] = benchmark_return_source
    return optional_metadata


def _finalize_resolved_stateful_attribution_execution(
    request: AttributionAnalyticsRequest,
    resolved: ResolvedAttributionRequest,
    *,
    active_settings: _AttributionWorkflowSettings,
    source_request_fingerprint: str,
) -> tuple[str, str, ApplicationHttpResponse | None]:
    input_fingerprint, calculation_hash = generate_request_fingerprint(
        resolved.attribution_request,
        active_settings.APP_VERSION,
    )
    requested_window = build_attribution_execution_window(
        request,
        input_count=resolved.input_count,
        source_request_fingerprint=source_request_fingerprint,
        benchmark_id=resolved.resolved_benchmark_id,
        benchmark_return_source=resolved.resolved_benchmark_return_source,
    )
    accepted_response = finalize_resolved_stateful_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        resolved_request_payload=async_observability_request_payload(
            {
                "resolved_request": resolved.attribution_request.model_dump(mode="json"),
                "source_input_mode": resolved.input_mode.value,
                "resolved_benchmark_id": resolved.resolved_benchmark_id,
                "resolved_benchmark_return_source": resolved.resolved_benchmark_return_source,
            }
        ),
        should_offload=should_offload_resolved_attribution(resolved.input_count),
        offload_reason="large_resolved_stateful_attribution",
        accepted_response_factory=accepted_attribution_response,
    )
    return input_fingerprint, calculation_hash, accepted_response


def _initial_attribution_async_submission(
    request: AttributionAnalyticsRequest,
    *,
    requested_window: dict[str, object],
    input_fingerprint: str,
    calculation_hash: str,
) -> ApplicationHttpResponse | None:
    if not should_offload_attribution(request):
        return None
    offload_reason = (
        "long_window_stateful_attribution"
        if request.input_mode == AttributionInputMode.STATEFUL
        else "large_attribution_input_set"
    )
    return register_async_submission_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        portfolio_id=request.portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        request_payload=async_observability_request_payload(request.model_dump(mode="json")),
        offload_reason=offload_reason,
        accepted_response_factory=accepted_attribution_response,
    )


def _stateful_attribution_replay_or_sync_window(
    request: AttributionAnalyticsRequest,
    *,
    source_request_fingerprint: str,
    requested_window: dict[str, object],
) -> tuple[ApplicationHttpResponse | None, dict[str, object]]:
    if request.input_mode != AttributionInputMode.STATEFUL:
        return None, requested_window

    replay_response = replay_promoted_stateful_async_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        source_request_fingerprint=source_request_fingerprint,
        accepted_response_factory=accepted_attribution_response,
    )
    if replay_response is not None:
        return replay_response, requested_window

    return None, build_attribution_execution_window(
        request,
        input_count=attribution_input_count(request),
        source_request_fingerprint=source_request_fingerprint,
    )


def _calculate_resolved_attribution_response(
    request: AttributionAnalyticsRequest,
    resolved: ResolvedAttributionRequest,
    *,
    active_settings: _AttributionWorkflowSettings,
    source_request_fingerprint: str,
    input_fingerprint: str,
    calculation_hash: str,
) -> AttributionResponse | ApplicationHttpResponse:
    if resolved.input_mode == AttributionInputMode.STATEFUL:
        input_fingerprint, calculation_hash, accepted_response = _finalize_resolved_stateful_attribution_execution(
            request,
            resolved,
            active_settings=active_settings,
            source_request_fingerprint=source_request_fingerprint,
        )
        if accepted_response is not None:
            return accepted_response
    return calculate_attribution(
        resolved.attribution_request,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        input_mode=resolved.input_mode,
        resolved_benchmark_id=resolved.resolved_benchmark_id,
        resolved_benchmark_return_source=resolved.resolved_benchmark_return_source,
    )


async def calculate_attribution_workflow(
    request: AttributionAnalyticsRequest,
) -> AttributionResponse | ApplicationHttpResponse:
    """Resolve, fence, execute, and map errors for one attribution analytics request."""
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, active_settings.APP_VERSION)
    source_request_fingerprint = input_fingerprint
    requested_window = build_attribution_execution_window(
        request,
        input_count=attribution_input_count(request),
    )
    accepted_response = _initial_attribution_async_submission(
        request,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    if accepted_response is not None:
        return accepted_response

    replay_response, requested_window = _stateful_attribution_replay_or_sync_window(
        request,
        source_request_fingerprint=source_request_fingerprint,
        requested_window=requested_window,
    )
    if replay_response is not None:
        return replay_response

    _register_attribution_sync_execution(
        request,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

    return await _resolve_and_calculate_attribution_response(
        request,
        active_settings=active_settings,
        source_request_fingerprint=source_request_fingerprint,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )


def _register_attribution_sync_execution(
    request: AttributionAnalyticsRequest,
    *,
    requested_window: dict[str, object],
    input_fingerprint: str,
    calculation_hash: str,
) -> None:
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_ATTRIBUTION,
        portfolio_id=request.portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )


async def _resolve_and_calculate_attribution_response(
    request: AttributionAnalyticsRequest,
    *,
    active_settings: _AttributionWorkflowSettings,
    source_request_fingerprint: str,
    input_fingerprint: str,
    calculation_hash: str,
) -> AttributionResponse | ApplicationHttpResponse:
    try:
        resolved = await resolve_attribution_request(request, settings=cast(Settings, active_settings))
        return _calculate_resolved_attribution_response(
            request,
            resolved,
            active_settings=active_settings,
            source_request_fingerprint=source_request_fingerprint,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
    except Exception as exc:
        if is_mappable_application_error(exc):
            record_execution_failure(
                calculation_id=request.calculation_id,
                message=execution_stage_failure_detail(exc),
            )
            raise
        failure_detail = _unexpected_attribution_resolution_failure_detail(exc)
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=failure_detail,
        )
        raise APIInternalServerError(failure_detail) from exc


def _unexpected_attribution_resolution_failure_detail(exc: Exception) -> str:
    return f"An unexpected error occurred during attribution request resolution: {exc}"
