from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models.runtime_retention_history import (
    RuntimeRetentionCleanupRunRequest,
    RuntimeRetentionCleanupRunResponse,
    build_runtime_retention_cleanup_run_response,
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


@dataclass(frozen=True)
class RuntimeRetentionCleanupRunResult:
    response: RuntimeRetentionCleanupRunResponse
    is_replay: bool


def run_runtime_retention_cleanup(
    *,
    cleanup_request: RuntimeRetentionCleanupRunRequest,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str | None,
    artifact_directory: Path,
    action_lease_stale_seconds: float,
    cooldown_seconds: float,
    apply_preview_max_age_seconds: float,
    retention_days_default: int,
    now_utc: datetime | None = None,
) -> RuntimeRetentionCleanupRunResult:
    """Run or replay a governed runtime-retention cleanup action."""
    resolved_retention_days = cleanup_request.retention_days or retention_days_default
    history_snapshot = build_runtime_retention_history_snapshot(
        artifact_directory=artifact_directory,
        limit=100,
        trigger_mode="manual",
    )
    replay = resolve_runtime_retention_manual_replay(
        history_snapshot,
        artifact_directory=artifact_directory,
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        apply=cleanup_request.apply,
        retention_days=cleanup_request.retention_days,
        job_id=cleanup_request.job_id,
    )
    if replay is not None:
        return RuntimeRetentionCleanupRunResult(
            response=build_runtime_retention_cleanup_run_response(**replay.payload),
            is_replay=True,
        )

    if cleanup_request.apply:
        enforce_runtime_retention_apply_preview(
            history_snapshot,
            operator_id=operator_id,
            tenant_id=tenant_id,
            retention_days=resolved_retention_days,
            job_id=cleanup_request.job_id,
            preview_max_age_seconds=apply_preview_max_age_seconds,
        )

    enforce_runtime_retention_manual_run_cooldown(
        history_snapshot,
        apply=cleanup_request.apply,
        operator_id=operator_id,
        tenant_id=tenant_id,
        retention_days=resolved_retention_days,
        job_id=cleanup_request.job_id,
        cooldown_seconds=cooldown_seconds,
    )

    action_key = build_runtime_retention_action_key(
        operator_id=operator_id,
        tenant_id=tenant_id,
        apply=cleanup_request.apply,
        retention_days=resolved_retention_days,
        job_id=cleanup_request.job_id,
    )
    with operator_action_lease(
        artifact_directory=artifact_directory,
        action_key=action_key,
        metadata=OperatorActionLeaseMetadata(
            action_name="runtime_retention_cleanup",
            operator_id=operator_id,
            tenant_id=tenant_id,
            governed_target=(
                f"{'apply' if cleanup_request.apply else 'dry_run'}:{resolved_retention_days}:{cleanup_request.job_id or 'no-job'}"
            ),
            acquired_at_utc=(now_utc or datetime.now(UTC)).isoformat(),
        ),
        stale_after_seconds=action_lease_stale_seconds,
        now_utc=now_utc,
    ):
        evidence = execute_runtime_retention_cleanup(
            apply=cleanup_request.apply,
            retention_days=cleanup_request.retention_days,
            operator_id=operator_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            trigger_mode="manual",
            job_id=cleanup_request.job_id,
            output_dir=artifact_directory,
        )

    return RuntimeRetentionCleanupRunResult(
        response=build_runtime_retention_cleanup_run_response(
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
        ),
        is_replay=False,
    )
