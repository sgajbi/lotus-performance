from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.contribution_analytics_requests import (
    ContributionAnalyticsRequest,
    ContributionInputMode,
)
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import ContributionAcceptedResponse, ContributionResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_CONTRIBUTION
from app.services.contribution_mode_service import resolve_contribution_request
from app.services.contribution_service import calculate_contribution
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)


def accepted_contribution_response(calculation_id) -> ContributionAcceptedResponse:
    return ContributionAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/performance/contribution/results/{calculation_id}",
    )


def contribution_position_count(request: ContributionAnalyticsRequest | ContributionRequest) -> int:
    stateless_input = getattr(request, "stateless_input", None)
    input_mode = getattr(request, "input_mode", ContributionInputMode.STATELESS)
    if stateless_input is not None:
        return len(getattr(stateless_input, "positions_data", []) or [])
    if input_mode == ContributionInputMode.STATEFUL:
        return 0
    return len(getattr(request, "positions_data", []) or [])


def should_preemptively_offload_stateful_contribution(request: ContributionAnalyticsRequest) -> bool:
    active_settings = get_settings()
    return (
        request.report_end_date - request.report_start_date
    ).days >= active_settings.CONTRIBUTION_EXECUTOR_WINDOW_DAYS


def should_offload_resolved_contribution(position_count: int) -> bool:
    active_settings = get_settings()
    return position_count >= active_settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT


def should_offload_contribution(request: ContributionAnalyticsRequest | ContributionRequest) -> bool:
    active_settings = get_settings()
    input_mode = getattr(request, "input_mode", ContributionInputMode.STATELESS)
    if input_mode == ContributionInputMode.STATEFUL:
        return should_preemptively_offload_stateful_contribution(request)
    return contribution_position_count(request) >= active_settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT


def build_contribution_execution_window(
    request: ContributionAnalyticsRequest | ContributionRequest,
    *,
    source_request_fingerprint: str | None = None,
) -> dict[str, object]:
    input_mode = getattr(request, "input_mode", ContributionInputMode.STATELESS)
    requested_window = {
        "report_start_date": str(request.report_start_date),
        "report_end_date": str(request.report_end_date),
        "requested_periods": [analysis.period.value for analysis in request.analyses],
        "position_count": contribution_position_count(request),
        "hierarchical": bool(request.hierarchy),
        "input_mode": input_mode.value,
    }
    if source_request_fingerprint is not None:
        requested_window["source_request_fingerprint"] = source_request_fingerprint
    return requested_window


def build_resolved_contribution_execution_window(
    request: ContributionAnalyticsRequest,
    *,
    position_count: int,
    source_request_fingerprint: str,
) -> dict[str, object]:
    requested_window = build_contribution_execution_window(
        request,
        source_request_fingerprint=source_request_fingerprint,
    )
    requested_window["position_count"] = position_count
    return requested_window


async def calculate_contribution_workflow(
    request: ContributionAnalyticsRequest,
) -> ContributionResponse | ContributionAcceptedResponse:
    """Resolve, fence, execute, and map errors for one contribution analytics request."""
    active_settings = get_settings()
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, active_settings.APP_VERSION)
    if request.input_mode == ContributionInputMode.STATEFUL and not should_preemptively_offload_stateful_contribution(
        request
    ):
        replay_response = replay_promoted_stateful_async_execution(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
            source_request_fingerprint=input_fingerprint,
            accepted_response_factory=accepted_contribution_response,
        )
        if replay_response is not None:
            return replay_response
        register_sync_execution_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
            portfolio_id=request.portfolio_id,
            requested_window=build_contribution_execution_window(
                request,
                source_request_fingerprint=input_fingerprint,
            ),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
        try:
            resolved = await resolve_contribution_request(request, settings=active_settings)
            resolved_request = resolved.contribution_request
            resolved_input_fingerprint, resolved_calculation_hash = generate_request_fingerprint(
                resolved_request,
                active_settings.APP_VERSION,
            )
            resolved_window = build_resolved_contribution_execution_window(
                request,
                position_count=resolved.position_count,
                source_request_fingerprint=input_fingerprint,
            )
            accepted_response = finalize_resolved_stateful_execution(
                calculation_id=request.calculation_id,
                analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
                requested_window=resolved_window,
                input_fingerprint=resolved_input_fingerprint,
                calculation_hash=resolved_calculation_hash,
                resolved_request_payload=resolved_request.model_dump(mode="json"),
                should_offload=should_offload_resolved_contribution(resolved.position_count),
                offload_reason="large_resolved_stateful_contribution",
                accepted_response_factory=accepted_contribution_response,
            )
            if accepted_response is not None:
                return accepted_response

            return calculate_contribution(
                resolved_request,
                input_fingerprint=resolved_input_fingerprint,
                calculation_hash=resolved_calculation_hash,
                input_mode=resolved.input_mode,
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
                message=f"An unexpected error occurred during contribution request resolution: {exc}",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred during contribution request resolution: {exc}",
            ) from exc

    if should_offload_contribution(request):
        offload_reason = (
            "long_window_stateful_contribution"
            if request.input_mode == ContributionInputMode.STATEFUL
            else "large_position_count_contribution"
        )
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
            portfolio_id=request.portfolio_id,
            requested_window=build_contribution_execution_window(request),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=request.model_dump(mode="json"),
            offload_reason=offload_reason,
            accepted_response_factory=accepted_contribution_response,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_CONTRIBUTION,
        portfolio_id=request.portfolio_id,
        requested_window=build_contribution_execution_window(request),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

    try:
        resolved = await resolve_contribution_request(request, settings=active_settings)
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
