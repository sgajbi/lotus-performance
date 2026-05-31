from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.operator_context import resolve_operator_request_context
from app.core.config import get_settings
from app.models.runtime_retention_history import (
    RuntimeRetentionCleanupRunRequest,
    RuntimeRetentionCleanupRunResponse,
    RuntimeRetentionHistoryResponse,
    build_runtime_retention_cleanup_run_response,
    build_runtime_retention_history_response,
)
from app.services.operator_action_guard_service import (
    enforce_runtime_retention_apply_preview,
    enforce_runtime_retention_manual_run_cooldown,
)
from app.services.operator_action_lease_service import (
    OperatorActionLeaseMetadata,
    build_runtime_retention_action_key,
    operator_action_lease,
)
from app.services.operator_action_replay_service import resolve_runtime_retention_manual_replay
from app.services.runtime_retention_execution_service import execute_runtime_retention_cleanup
from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot

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
    limit: Annotated[
        int | None,
        Query(ge=1, le=100, description="Maximum number of retained runtime-retention cleanup entries to return."),
    ] = None,
    offset: Annotated[
        int, Query(ge=0, description="Zero-based offset into the filtered retained runtime-retention cleanup history.")
    ] = 0,
    operator_id: Annotated[
        str | None,
        Query(description="Filter retained runtime-retention cleanup history by operator or automation identity."),
    ] = None,
    trigger_mode: Annotated[
        str | None,
        Query(description="Filter retained runtime-retention cleanup history by manual or scheduled trigger mode."),
    ] = None,
    job_id: Annotated[
        str | None,
        Query(description="Filter retained runtime-retention cleanup history by scheduler or automation job identity."),
    ] = None,
    cleanup_mode: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by cleanup mode.")
    ] = None,
    status: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by execution outcome status.")
    ] = None,
    generated_after: Annotated[
        str | None,
        Query(
            description="Filter retained runtime-retention cleanup history to entries generated at or after this ISO-8601 timestamp."
        ),
    ] = None,
    generated_before: Annotated[
        str | None,
        Query(
            description="Filter retained runtime-retention cleanup history to entries generated at or before this ISO-8601 timestamp."
        ),
    ] = None,
) -> RuntimeRetentionHistoryResponse:
    snapshot = build_runtime_retention_history_snapshot(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode=cleanup_mode,
        status_filter=status,
        generated_after=generated_after,
        generated_before=generated_before,
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
    settings = get_settings()
    operator_context = resolve_operator_request_context(request)
    resolved_retention_days = cleanup_request.retention_days or settings.RUNTIME_RETENTION_DAYS
    history_snapshot = build_runtime_retention_history_snapshot(limit=100, trigger_mode="manual")
    replay = resolve_runtime_retention_manual_replay(
        history_snapshot,
        artifact_directory=settings.RUNTIME_RETENTION_ARTIFACT_PATH,
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        correlation_id=operator_context.correlation_id,
        apply=cleanup_request.apply,
        retention_days=cleanup_request.retention_days,
        job_id=cleanup_request.job_id,
    )
    if replay is not None:
        return JSONResponse(
            status_code=200,
            content=build_runtime_retention_cleanup_run_response(**replay.payload).model_dump(mode="json"),
            headers={"X-Idempotent-Replay": "true"},
        )
    if cleanup_request.apply:
        enforce_runtime_retention_apply_preview(
            history_snapshot,
            operator_id=operator_context.operator_id,
            tenant_id=operator_context.tenant_id,
            retention_days=resolved_retention_days,
            job_id=cleanup_request.job_id,
            preview_max_age_seconds=settings.RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS,
        )
    enforce_runtime_retention_manual_run_cooldown(
        history_snapshot,
        apply=cleanup_request.apply,
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        retention_days=resolved_retention_days,
        job_id=cleanup_request.job_id,
        cooldown_seconds=settings.RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS,
    )
    action_key = build_runtime_retention_action_key(
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        apply=cleanup_request.apply,
        retention_days=resolved_retention_days,
        job_id=cleanup_request.job_id,
    )
    with operator_action_lease(
        artifact_directory=settings.RUNTIME_RETENTION_ARTIFACT_PATH,
        action_key=action_key,
        metadata=OperatorActionLeaseMetadata(
            action_name="runtime_retention_cleanup",
            operator_id=operator_context.operator_id,
            tenant_id=operator_context.tenant_id,
            governed_target=f"{'apply' if cleanup_request.apply else 'dry_run'}:{resolved_retention_days}:{cleanup_request.job_id or 'no-job'}",
            acquired_at_utc=datetime.now(UTC).isoformat(),
        ),
        stale_after_seconds=settings.RUNTIME_RETENTION_ACTION_LEASE_STALE_SECONDS,
    ):
        evidence = execute_runtime_retention_cleanup(
            apply=cleanup_request.apply,
            retention_days=cleanup_request.retention_days,
            operator_id=operator_context.operator_id,
            tenant_id=operator_context.tenant_id,
            correlation_id=operator_context.correlation_id,
            trigger_mode="manual",
            job_id=cleanup_request.job_id,
        )
    return build_runtime_retention_cleanup_run_response(
        cleanup_name=evidence.cleanup_name,
        generated_at_utc=evidence.generated_at_utc,
        evidence_file_name=evidence.evidence_file_name,
        operator_id=evidence.operator_id,
        tenant_id=evidence.tenant_id,
        correlation_id=evidence.correlation_id,
        trigger_mode=evidence.trigger_mode,
        job_id=evidence.job_id,
        cleanup_mode=evidence.cleanup_mode,
        status=evidence.status,
        retention_days=evidence.retention_days,
        cutoff_utc=evidence.cutoff_utc,
        prunable_execution_count=evidence.prunable_execution_count,
        prunable_compute_job_count=evidence.prunable_compute_job_count,
        prunable_async_result_count=evidence.prunable_async_result_count,
        prunable_lineage_record_count=evidence.prunable_lineage_record_count,
        prunable_lineage_artifact_count=evidence.prunable_lineage_artifact_count,
    )
