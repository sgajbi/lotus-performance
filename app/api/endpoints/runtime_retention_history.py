from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.runtime_retention_history import (
    RuntimeRetentionCleanupRunRequest,
    RuntimeRetentionCleanupRunResponse,
    RuntimeRetentionHistoryResponse,
    build_runtime_retention_cleanup_run_response,
    build_runtime_retention_history_response,
)
from app.services.operator_action_guard_service import enforce_runtime_retention_manual_run_cooldown
from app.services.operator_action_replay_service import resolve_runtime_retention_manual_replay
from app.services.runtime_retention_execution_service import execute_runtime_retention_cleanup
from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot

router = APIRouter(tags=["Integration"])


def _resolve_operator_identity(request: Request) -> str:
    actor_id = request.headers.get("X-Actor-Id", "").strip()
    if actor_id:
        return actor_id
    service_identity = request.headers.get("X-Service-Identity", "").strip()
    if service_identity:
        return service_identity
    raise HTTPException(status_code=400, detail="missing_operator_identity")


def _resolve_tenant_id(request: Request) -> str | None:
    tenant_id = request.headers.get("X-Tenant-Id", "").strip()
    return tenant_id or None


def _resolve_correlation_id(request: Request) -> str | None:
    correlation_id = request.headers.get("X-Correlation-Id", "").strip()
    return correlation_id or None


@router.get(
    "/runtime-retention-cleanups",
    response_model=RuntimeRetentionHistoryResponse,
    summary="Get retained runtime-retention cleanup history",
    description=(
        "Returns the retained runtime-retention cleanup history manifest for lotus-performance, including the latest "
        "artifact, configured retention policy, and summarized retained cleanup entries. Optional query filters allow "
        "operators to narrow the history by operator, trigger mode, job identity, cleanup mode, status, and bounded result count."
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
        "Runs a service-owned runtime-retention cleanup action using the current durable retention policy or an explicit "
        "retention-window override. The resulting evidence is retained in the runtime-retention history so operators can "
        "audit who ran the cleanup, whether it was dry-run or apply, and what terminal state was selected."
    ),
)
async def run_runtime_retention_cleanup(
    request: Request,
    cleanup_request: RuntimeRetentionCleanupRunRequest,
) -> RuntimeRetentionCleanupRunResponse:
    settings = get_settings()
    history_snapshot = build_runtime_retention_history_snapshot(limit=10, trigger_mode="manual")
    replay = resolve_runtime_retention_manual_replay(
        history_snapshot,
        artifact_directory=settings.RUNTIME_RETENTION_ARTIFACT_PATH,
        correlation_id=_resolve_correlation_id(request),
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
    enforce_runtime_retention_manual_run_cooldown(
        history_snapshot,
        cooldown_seconds=settings.RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS,
    )
    evidence = execute_runtime_retention_cleanup(
        apply=cleanup_request.apply,
        retention_days=cleanup_request.retention_days,
        operator_id=_resolve_operator_identity(request),
        tenant_id=_resolve_tenant_id(request),
        correlation_id=_resolve_correlation_id(request),
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
