from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.application_responses import ApplicationHttpResponse
from app.core.config import get_settings
from app.models.returns_series import (
    InputMode,
    ReturnsSeriesAcceptedResponse,
    ReturnsSeriesRequest,
    ReturnsSeriesResponse,
)
from app.services.analytics_workflow_commands import ReturnsSeriesWorkflowCommand, workflow_request
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_RETURNS_SERIES
from app.services.async_observability_context import async_observability_request_payload
from app.services.execution_registry import execution_registry
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.returns_series_service import (
    ResolvedStatefulReturnsSeriesRequest,
    calculate_returns_series,
    resolve_stateful_returns_series_request,
    resolve_window,
)
from app.services.stateful_execution_policy_service import (
    finalize_resolved_stateful_execution,
    replay_promoted_stateful_async_execution,
)
from app.services.submission_fencing_service import (
    register_async_submission_or_raise,
    register_sync_execution_or_raise,
)


def accepted_returns_series_response(calculation_id: UUID) -> ReturnsSeriesAcceptedResponse:
    return ReturnsSeriesAcceptedResponse(
        calculation_id=calculation_id,
        poll_path=f"/performance/executions/{calculation_id}",
        result_path=f"/integration/returns/series/results/{calculation_id}",
    )


def should_offload_returns_series(request: ReturnsSeriesRequest) -> bool:
    active_settings = get_settings()
    if request.input_mode == InputMode.STATELESS:
        return returns_series_stateless_input_count(request) >= active_settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT
    resolved_window = resolve_window(request)
    return (
        resolved_window.end_date - resolved_window.start_date
    ).days >= active_settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS


def returns_series_stateless_input_count(request: ReturnsSeriesRequest) -> int:
    stateless_input = request.stateless_input
    if request.input_mode != InputMode.STATELESS or stateless_input is None:
        return 0
    return sum(
        len(points or [])
        for points in (
            stateless_input.portfolio_returns,
            stateless_input.benchmark_returns,
            stateless_input.risk_free_returns,
        )
    )


def should_offload_resolved_returns_series(input_count: int) -> bool:
    active_settings = get_settings()
    return input_count >= active_settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT


def _returns_series_execution_metadata(
    *,
    source_request_fingerprint: str | None,
    input_count: int | None,
    benchmark_id: str | None,
    benchmark_return_source: str | None,
    benchmark_work_units: int | None,
) -> dict[str, object]:
    metadata: dict[str, object | None] = {
        "source_request_fingerprint": source_request_fingerprint,
        "input_count": input_count,
        "benchmark_id": benchmark_id,
        "benchmark_return_source": benchmark_return_source,
        "benchmark_work_units": benchmark_work_units,
    }
    return {field: value for field, value in metadata.items() if value is not None}


def _execution_failure_message(exc: Exception) -> str:
    detail: Any = getattr(exc, "detail", exc)
    if isinstance(detail, dict) and "message" in detail:
        return str(detail["message"])
    return str(detail)


def build_returns_series_execution_window(
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
    requested_window.update(
        _returns_series_execution_metadata(
            source_request_fingerprint=source_request_fingerprint,
            input_count=input_count,
            benchmark_id=benchmark_id,
            benchmark_return_source=benchmark_return_source,
            benchmark_work_units=benchmark_work_units,
        )
    )
    return requested_window


def _resolved_returns_series_execution_window(
    request: ReturnsSeriesRequest,
    *,
    source_request_fingerprint: str,
    resolved: ResolvedStatefulReturnsSeriesRequest,
) -> dict[str, object]:
    return build_returns_series_execution_window(
        request,
        source_request_fingerprint=source_request_fingerprint,
        input_count=resolved.input_count,
        benchmark_id=resolved.resolved_benchmark_id,
        benchmark_return_source=resolved.resolved_benchmark_return_source,
        benchmark_work_units=resolved.benchmark_work_units,
    )


def _resolved_returns_series_async_request_payload(
    resolved: ResolvedStatefulReturnsSeriesRequest,
) -> dict[str, object]:
    return async_observability_request_payload(
        {
            "resolved_request": resolved.request.model_dump(mode="json"),
            "source_input_mode": InputMode.STATEFUL.value,
            "resolved_benchmark_id": resolved.resolved_benchmark_id,
            "resolved_benchmark_return_source": resolved.resolved_benchmark_return_source,
            "freshness_portfolio_returns": _freshness_return_records(resolved.freshness_portfolio_df),
            "freshness_benchmark_returns": _freshness_return_records(resolved.freshness_benchmark_df),
            "freshness_risk_free_returns": _freshness_return_records(resolved.freshness_risk_free_df),
            "risk_free_source_quality": (
                resolved.risk_free_source_quality.model_dump(mode="json")
                if resolved.risk_free_source_quality is not None
                else None
            ),
        }
    )


def _freshness_return_records(df: Any) -> list[dict[str, str]] | None:
    if df is None:
        return None
    records: list[dict[str, str]] = []
    for row in df[["date", "return_value"]].to_dict("records"):
        date_value = row["date"]
        records.append(
            {
                "date": date_value.date().isoformat() if hasattr(date_value, "date") else str(date_value),
                "return_value": str(row["return_value"]),
            }
        )
    return records


def _finalize_resolved_returns_series_execution(
    *,
    request: ReturnsSeriesRequest,
    source_request_fingerprint: str,
    resolved: ResolvedStatefulReturnsSeriesRequest,
    input_fingerprint: str,
    calculation_hash: str,
) -> ApplicationHttpResponse | None:
    return finalize_resolved_stateful_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        requested_window=_resolved_returns_series_execution_window(
            request,
            source_request_fingerprint=source_request_fingerprint,
            resolved=resolved,
        ),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        resolved_request_payload=_resolved_returns_series_async_request_payload(resolved),
        should_offload=should_offload_resolved_returns_series(resolved.input_count),
        offload_reason="large_resolved_stateful_returns_series",
        accepted_response_factory=accepted_returns_series_response,
    )


async def _calculate_promoted_stateful_returns_series(
    *,
    request: ReturnsSeriesRequest,
    input_fingerprint: str,
    calculation_hash: str,
) -> ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse | ApplicationHttpResponse:
    replay_response = replay_promoted_stateful_async_execution(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        source_request_fingerprint=input_fingerprint,
        accepted_response_factory=accepted_returns_series_response,
    )
    if replay_response is not None:
        return replay_response
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id=request.portfolio_id,
        requested_window=build_returns_series_execution_window(
            request,
            source_request_fingerprint=input_fingerprint,
        ),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )
    try:
        resolved = await resolve_stateful_returns_series_request(request)
        resolved_input_fingerprint, resolved_calculation_hash = generate_request_fingerprint(
            resolved.identity_payload,
            "returns-series-v1",
        )
        accepted_response = _finalize_resolved_returns_series_execution(
            request=request,
            source_request_fingerprint=input_fingerprint,
            resolved=resolved,
            input_fingerprint=resolved_input_fingerprint,
            calculation_hash=resolved_calculation_hash,
        )
        if accepted_response is not None:
            return accepted_response
        return await calculate_returns_series(
            resolved.request,
            source_input_mode=InputMode.STATEFUL,
            resolved_benchmark_id_override=resolved.resolved_benchmark_id,
            resolved_benchmark_return_source_override=resolved.resolved_benchmark_return_source,
            risk_free_source_quality_override=resolved.risk_free_source_quality,
            freshness_portfolio_df_override=resolved.freshness_portfolio_df,
            freshness_benchmark_df_override=resolved.freshness_benchmark_df,
            freshness_risk_free_df_override=resolved.freshness_risk_free_df,
        )
    except Exception as exc:
        message = _execution_failure_message(exc)
        execution_registry.fail_in_progress_stages(request.calculation_id, message)
        execution_registry.mark_failed(request.calculation_id, message)
        raise


async def calculate_returns_series_workflow(
    command: ReturnsSeriesWorkflowCommand,
) -> ReturnsSeriesResponse | ReturnsSeriesAcceptedResponse | ApplicationHttpResponse:
    """Resolve, fence, execute, and enqueue one returns-series request."""
    request = workflow_request(command, ReturnsSeriesRequest)
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, "returns-series-v1")
    should_offload = should_offload_returns_series(request)
    if request.input_mode == InputMode.STATEFUL and not should_offload:
        return await _calculate_promoted_stateful_returns_series(
            request=request,
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
        )
    execution_mode = "async" if should_offload else "sync"
    stateless_input_count = (
        returns_series_stateless_input_count(request) if request.input_mode == InputMode.STATELESS else None
    )
    if execution_mode == "async":
        return register_async_submission_or_raise(
            calculation_id=request.calculation_id,
            analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
            portfolio_id=request.portfolio_id,
            requested_window=build_returns_series_execution_window(request, input_count=stateless_input_count),
            input_fingerprint=input_fingerprint,
            calculation_hash=calculation_hash,
            request_payload=async_observability_request_payload(request.model_dump(mode="json")),
            offload_reason=(
                "large_stateless_returns_series"
                if request.input_mode == InputMode.STATELESS
                else "long_window_stateful_returns_series"
            ),
            accepted_response_factory=accepted_returns_series_response,
        )

    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_RETURNS_SERIES,
        portfolio_id=request.portfolio_id,
        requested_window=build_returns_series_execution_window(request, input_count=stateless_input_count),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
    )

    return await calculate_returns_series(request)
