from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.runtime_retention_history import build_runtime_retention_history_query
from app.api.operator_context import resolve_operator_request_context
from app.core.config import get_settings
from app.models.runtime_retention_history import (
    RuntimeRetentionCleanupRunRequest,
    RuntimeRetentionCleanupRunResponse,
    RuntimeRetentionHistoryQueryParams,
    RuntimeRetentionHistoryResponse,
    build_runtime_retention_history_response,
)
from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot
from app.services.runtime_retention_run_service import (
    run_runtime_retention_cleanup as run_runtime_retention_cleanup_action,
)

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-retention-cleanups",
    response_model=RuntimeRetentionHistoryResponse,
    summary="Get retained runtime-retention cleanup history",
    description=(
        "Returns the retained runtime-retention cleanup history manifest for lotus-performance. Use this operator "
        "control-plane endpoint to inspect latest cleanup assurance, retained evidence artifacts, retention "
        "policy, applied filters, deterministic paging, cleanup mode, prunable counts, and time-windowed cleanup "
        "outcomes without shell access to the artifact directory."
    ),
)
async def get_runtime_retention_history(
    query: Annotated[RuntimeRetentionHistoryQueryParams, Depends(build_runtime_retention_history_query)],
) -> RuntimeRetentionHistoryResponse:
    """Return retained runtime-retention cleanup history for operator review."""
    snapshot = build_runtime_retention_history_snapshot(
        limit=query.limit,
        offset=query.offset,
        operator_id=query.operator_id,
        trigger_mode=query.trigger_mode,
        job_id=query.job_id,
        cleanup_mode=query.cleanup_mode,
        status_filter=query.status,
        generated_after=query.generated_after,
        generated_before=query.generated_before,
    )
    return build_runtime_retention_history_response(snapshot)


@router.post(
    "/runtime-retention-cleanups/run",
    response_model=RuntimeRetentionCleanupRunResponse,
    summary="Run a governed runtime-retention cleanup preview or apply action",
    description=(
        "Runs a governed service-owned runtime-retention cleanup preview or apply action using the current durable "
        "retention policy or an explicit retention-window override. The endpoint requires an operator identity, "
        "enforces preview-before-apply, idempotent replay, cooldown, and stale-lease guards, retains evidence in "
        "runtime-retention history, and returns prunable execution, compute, async-result, lineage-record, and "
        "lineage-artifact counts."
    ),
)
async def run_runtime_retention_cleanup(
    request: Request,
    cleanup_request: RuntimeRetentionCleanupRunRequest,
) -> RuntimeRetentionCleanupRunResponse:
    """Run or replay a governed runtime-retention cleanup action under lease controls."""
    settings = get_settings()
    operator_context = resolve_operator_request_context(request)
    result = run_runtime_retention_cleanup_action(
        cleanup_request=cleanup_request,
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        correlation_id=operator_context.correlation_id,
        artifact_directory=settings.RUNTIME_RETENTION_ARTIFACT_PATH,
        action_lease_stale_seconds=settings.RUNTIME_RETENTION_ACTION_LEASE_STALE_SECONDS,
        cooldown_seconds=settings.RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS,
        apply_preview_max_age_seconds=settings.RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS,
        retention_days_default=settings.RUNTIME_RETENTION_DAYS,
    )
    if result.is_replay:
        return JSONResponse(
            status_code=200,
            content=result.response.model_dump(mode="json"),
            headers={"X-Idempotent-Replay": "true"},
        )
    return result.response
