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
from app.services.operator_action_replay_service import ActionReplayResult, resolve_runtime_retention_manual_replay
from app.services.operator_run_response_projection import build_operator_run_response_from_evidence
from app.services.runtime_retention_execution_service import (
    RuntimeRetentionCleanupEvidence,
    execute_runtime_retention_cleanup,
)
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistorySnapshot,
    build_runtime_retention_history_snapshot,
)


@dataclass(frozen=True)
class RuntimeRetentionCleanupRunResult:
    response: RuntimeRetentionCleanupRunResponse
    is_replay: bool


def _runtime_retention_cleanup_response_from_evidence(
    evidence: RuntimeRetentionCleanupEvidence,
) -> RuntimeRetentionCleanupRunResponse:
    return build_operator_run_response_from_evidence(
        build_runtime_retention_cleanup_run_response,
        evidence,
    )


def _enforce_runtime_retention_manual_run_guards(
    *,
    cleanup_request: RuntimeRetentionCleanupRunRequest,
    history_snapshot: RuntimeRetentionHistorySnapshot,
    operator_id: str,
    tenant_id: str | None,
    resolved_retention_days: int,
    apply_preview_max_age_seconds: float,
    cooldown_seconds: float,
) -> None:
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


def _runtime_retention_replay_run_result(replay: ActionReplayResult | None) -> RuntimeRetentionCleanupRunResult | None:
    if replay is None:
        return None
    return RuntimeRetentionCleanupRunResult(
        response=build_runtime_retention_cleanup_run_response(**replay.payload),
        is_replay=True,
    )


def _runtime_retention_governed_target(
    *,
    apply: bool,
    retention_days: int,
    job_id: str | None,
) -> str:
    cleanup_mode = "apply" if apply else "dry_run"
    return f"{cleanup_mode}:{retention_days}:{job_id or 'no-job'}"


def _run_runtime_retention_cleanup_under_lease(
    *,
    cleanup_request: RuntimeRetentionCleanupRunRequest,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str | None,
    artifact_directory: Path,
    action_lease_stale_seconds: float,
    resolved_retention_days: int,
    now_utc: datetime | None,
) -> RuntimeRetentionCleanupRunResult:
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
            governed_target=_runtime_retention_governed_target(
                apply=cleanup_request.apply,
                retention_days=resolved_retention_days,
                job_id=cleanup_request.job_id,
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
        response=_runtime_retention_cleanup_response_from_evidence(evidence),
        is_replay=False,
    )


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
    replay_result = _runtime_retention_replay_run_result(replay)
    if replay_result is not None:
        return replay_result

    _enforce_runtime_retention_manual_run_guards(
        cleanup_request=cleanup_request,
        history_snapshot=history_snapshot,
        operator_id=operator_id,
        tenant_id=tenant_id,
        resolved_retention_days=resolved_retention_days,
        apply_preview_max_age_seconds=apply_preview_max_age_seconds,
        cooldown_seconds=cooldown_seconds,
    )

    return _run_runtime_retention_cleanup_under_lease(
        cleanup_request=cleanup_request,
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        artifact_directory=artifact_directory,
        action_lease_stale_seconds=action_lease_stale_seconds,
        resolved_retention_days=resolved_retention_days,
        now_utc=now_utc,
    )
