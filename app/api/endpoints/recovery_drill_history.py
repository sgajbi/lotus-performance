from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.models.recovery_drill_history import (
    RecoveryDrillHistoryResponse,
    RecoveryDrillRunRequest,
    RecoveryDrillRunResponse,
    build_recovery_drill_history_response,
    build_recovery_drill_run_response,
)
from app.services.operator_action_guard_service import enforce_recovery_drill_manual_run_cooldown
from app.services.operator_action_lease_service import (
    OperatorActionLeaseMetadata,
    build_recovery_drill_action_key,
    operator_action_lease,
)
from app.services.operator_action_replay_service import resolve_recovery_drill_manual_replay
from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot
from scripts.durable_recovery_drill import run_recovery_drill as execute_recovery_drill

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
    "/recovery-drills",
    response_model=RecoveryDrillHistoryResponse,
    summary="Get retained durable recovery-drill history",
    description=(
        "Returns the retained durable recovery-drill history manifest for lotus-performance, including the latest "
        "artifact, configured retention policy, and summarized retained drill entries. Optional query filters allow "
        "operators to narrow the history by operator, backup identifier, status, and bounded result count."
    ),
)
async def get_recovery_drill_history(
    limit: Annotated[
        int | None, Query(ge=1, le=100, description="Maximum number of retained recovery-drill entries to return.")
    ] = None,
    offset: Annotated[
        int, Query(ge=0, description="Zero-based offset into the filtered retained recovery-drill history.")
    ] = 0,
    operator_id: Annotated[
        str | None, Query(description="Filter retained recovery-drill history by operator or automation identity.")
    ] = None,
    backup_identifier: Annotated[
        str | None, Query(description="Filter retained recovery-drill history by backup or restore-set identifier.")
    ] = None,
    status: Annotated[
        str | None, Query(description="Filter retained recovery-drill history by drill outcome status.")
    ] = None,
    generated_after: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history to entries generated at or after this ISO-8601 timestamp."
        ),
    ] = None,
    generated_before: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history to entries generated at or before this ISO-8601 timestamp."
        ),
    ] = None,
) -> RecoveryDrillHistoryResponse:
    snapshot = build_recovery_drill_history_snapshot(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status,
        generated_after=generated_after,
        generated_before=generated_before,
    )
    return build_recovery_drill_history_response(snapshot)


@router.post(
    "/recovery-drills/run",
    response_model=RecoveryDrillRunResponse,
    summary="Run a governed durable recovery drill",
    description=(
        "Runs the service-owned durable recovery drill, retains the resulting evidence in the recovery-drill "
        "artifact history, and returns the immediate drill summary to the caller."
    ),
)
async def run_recovery_drill(
    request: Request,
    recovery_request: RecoveryDrillRunRequest,
) -> RecoveryDrillRunResponse:
    settings = get_settings()
    operator_id = _resolve_operator_identity(request)
    tenant_id = _resolve_tenant_id(request)
    correlation_id = _resolve_correlation_id(request)
    history_snapshot = build_recovery_drill_history_snapshot(limit=10)
    replay = resolve_recovery_drill_manual_replay(
        history_snapshot,
        artifact_directory=settings.RECOVERY_DRILL_ARTIFACT_PATH,
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        backup_identifier=recovery_request.backup_identifier,
    )
    if replay is not None:
        return JSONResponse(
            status_code=200,
            content=build_recovery_drill_run_response(**replay.payload).model_dump(mode="json"),
            headers={"X-Idempotent-Replay": "true"},
        )
    enforce_recovery_drill_manual_run_cooldown(
        history_snapshot,
        operator_id=operator_id,
        tenant_id=tenant_id,
        backup_identifier=recovery_request.backup_identifier,
        cooldown_seconds=settings.RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS,
    )
    action_key = build_recovery_drill_action_key(
        operator_id=operator_id,
        tenant_id=tenant_id,
        backup_identifier=recovery_request.backup_identifier,
    )
    with operator_action_lease(
        artifact_directory=settings.RECOVERY_DRILL_ARTIFACT_PATH,
        action_key=action_key,
        metadata=OperatorActionLeaseMetadata(
            action_name="recovery_drill",
            operator_id=operator_id,
            tenant_id=tenant_id,
            governed_target=recovery_request.backup_identifier,
        ),
    ):
        evidence = execute_recovery_drill(
            output_dir=settings.RECOVERY_DRILL_ARTIFACT_PATH,
            operator_id=operator_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            backup_identifier=recovery_request.backup_identifier,
        )
    return build_recovery_drill_run_response(
        drill_name=evidence.drill_name,
        generated_at_utc=evidence.generated_at_utc,
        evidence_file_name=evidence.evidence_file_name,
        operator_id=evidence.operator_id,
        tenant_id=evidence.tenant_id,
        correlation_id=evidence.correlation_id,
        backup_identifier=evidence.backup_identifier,
        status=evidence.status,
        database_path=evidence.database_path,
        restored_schema_mode=evidence.restored_schema_mode,
        owned_tables_present=evidence.owned_tables_present,
        compute_job_processed_count=evidence.compute_job_processed_count,
        compute_async_result_status=evidence.compute_async_result_status,
        compute_execution_status=evidence.compute_execution_status,
        processed_payload_count=evidence.processed_payload_count,
        materialized_artifact_path=evidence.materialized_artifact_path,
        materialized_artifact_exists=evidence.materialized_artifact_exists,
    )
