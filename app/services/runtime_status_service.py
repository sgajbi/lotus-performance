from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings
from app.services.compute_job_store import (
    ComputeQueueInspectionAnchors,
    ComputeQueueStats,
    ComputeRecoveryEvent,
    compute_job_store,
)
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    LineageStorageCapacitySnapshot,
    check_durable_metadata_store_ready,
    check_lineage_storage_ready,
    get_lineage_storage_capacity,
)
from app.services.lineage_metadata_store import (
    LineageQueueInspectionAnchors,
    LineageQueueStats,
    LineageRecoveryEvent,
    lineage_metadata_store,
)
from app.services.operator_action_lease_service import build_operator_action_lease_snapshot
from app.services.recovery_drill_history_service import (
    build_recovery_drill_history_snapshot,
)
from app.services.runtime_retention_history_service import (
    build_runtime_retention_history_snapshot,
)
from app.services.runtime_retention_service import run_runtime_retention_cleanup


@dataclass(frozen=True)
class RuntimeQueueStatus:
    status: str
    reason: str | None
    degradation_reasons: tuple[str, ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]
    stats: ComputeQueueStats | LineageQueueStats | None
    inspection_anchors: ComputeQueueInspectionAnchors | LineageQueueInspectionAnchors | None
    recent_recoveries: tuple[ComputeRecoveryEvent | LineageRecoveryEvent, ...]
    storage_capacity: LineageStorageCapacitySnapshot | None = None


@dataclass(frozen=True)
class RuntimeDegradationDetail:
    reason: str
    observed_value: Decimal
    threshold_value: Decimal


@dataclass(frozen=True)
class ComputeQueueDegradationPolicy:
    pending_age_seconds: float
    leased_age_seconds: float
    running_age_seconds: float
    retry_backlog_count: int
    lease_expiry_count: int
    terminal_failure_count: int


@dataclass(frozen=True)
class LineageQueueDegradationPolicy:
    pending_age_seconds: float
    leased_age_seconds: float
    retry_backlog_count: int
    terminal_failure_count: int
    storage_min_free_bytes: int
    storage_min_free_ratio: float


@dataclass(frozen=True)
class RecoveryDrillStatus:
    status: str
    reason: str | None
    active_run_status: str
    active_run_reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple["RecentOperatorActionReclaim", ...]
    latest_generated_at_utc: str | None
    latest_status: str | None
    latest_operator_id: str | None
    latest_backup_identifier: str | None
    latest_age_seconds: float | None
    degradation_reasons: tuple[str, ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]


@dataclass(frozen=True)
class RecoveryDrillDegradationPolicy:
    max_age_seconds: float
    reclaim_count: int


@dataclass(frozen=True)
class RuntimeRetentionStatus:
    status: str
    reason: str | None
    active_run_status: str
    active_run_reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple["RecentOperatorActionReclaim", ...]
    preview_status: str
    preview_reason: str | None
    current_cutoff_utc: str | None
    current_retention_days: int | None
    current_prunable_execution_count: int | None
    current_prunable_compute_job_count: int | None
    current_prunable_async_result_count: int | None
    current_prunable_lineage_record_count: int | None
    current_prunable_lineage_artifact_count: int | None
    latest_generated_at_utc: str | None
    latest_status: str | None
    latest_operator_id: str | None
    latest_trigger_mode: str | None
    latest_job_id: str | None
    latest_cleanup_mode: str | None
    latest_retention_days: int | None
    latest_age_seconds: float | None
    degradation_reasons: tuple["str", ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]


@dataclass(frozen=True)
class RuntimeRetentionDegradationPolicy:
    max_age_seconds: float
    reclaim_count: int


@dataclass(frozen=True)
class OperatorActionStatus:
    status: str
    reason: str | None
    active_run_count: int
    oldest_active_run_operator_id: str | None
    oldest_active_run_tenant_id: str | None
    oldest_active_run_governed_target: str | None
    oldest_active_run_acquired_at_utc: str | None
    oldest_active_run_age_seconds: float | None
    latest_reclaimed_run_operator_id: str | None
    latest_reclaimed_run_tenant_id: str | None
    latest_reclaimed_run_governed_target: str | None
    latest_reclaimed_run_acquired_at_utc: str | None
    latest_reclaimed_run_reclaimed_at_utc: str | None
    latest_reclaimed_run_age_seconds: float | None
    reclaimed_run_count: int
    recent_reclaimed_runs: tuple["RecentOperatorActionReclaim", ...]


@dataclass(frozen=True)
class RecentOperatorActionReclaim:
    operator_id: str
    tenant_id: str | None
    governed_target: str
    acquired_at_utc: str
    reclaimed_at_utc: str
    reclaimed_age_seconds: float
    reclaim_count: int


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    generated_at: datetime
    runtime_status: str
    runtime_degradation_reasons: tuple[str, ...]
    runtime_degradation_details: tuple[RuntimeDegradationDetail, ...]
    draining: bool
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeQueueStatus
    lineage_queue: RuntimeQueueStatus
    recovery_drill: RecoveryDrillStatus
    runtime_retention: RuntimeRetentionStatus
    compute_queue_policy: ComputeQueueDegradationPolicy
    lineage_queue_policy: LineageQueueDegradationPolicy
    recovery_drill_policy: RecoveryDrillDegradationPolicy
    runtime_retention_policy: RuntimeRetentionDegradationPolicy


def build_runtime_status_snapshot(*, is_draining: bool) -> RuntimeStatusSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()
    settings = get_settings()
    compute_queue_policy = _build_compute_queue_policy(settings=settings)
    lineage_queue_policy = _build_lineage_queue_policy(settings=settings)
    recovery_drill_policy = _build_recovery_drill_policy(settings=settings)
    runtime_retention_policy = _build_runtime_retention_policy(settings=settings)

    runtime_status = "draining" if is_draining else durability_status.status
    compute_queue = _build_compute_queue_status(durability_status, settings=settings)
    lineage_queue = _build_lineage_queue_status(durability_status, settings=settings)
    recovery_drill = _build_recovery_drill_status(settings=settings)
    runtime_retention = _build_runtime_retention_status(settings=settings)
    runtime_degradation_reasons = _collect_runtime_degradation_reasons(
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
    )
    runtime_degradation_details = _collect_runtime_degradation_details(
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
    )

    if runtime_status == "ready" and (
        compute_queue.status != "available"
        or lineage_queue.status != "available"
        or recovery_drill.status != "available"
        or runtime_retention.status != "available"
    ):
        runtime_status = "degraded"

    return RuntimeStatusSnapshot(
        generated_at=generated_at,
        runtime_status=runtime_status,
        runtime_degradation_reasons=runtime_degradation_reasons,
        runtime_degradation_details=runtime_degradation_details,
        draining=is_draining,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        recovery_drill=recovery_drill,
        runtime_retention=runtime_retention,
        compute_queue_policy=compute_queue_policy,
        lineage_queue_policy=lineage_queue_policy,
        recovery_drill_policy=recovery_drill_policy,
        runtime_retention_policy=runtime_retention_policy,
    )


def _build_compute_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )
    try:
        stats = compute_job_store.get_queue_stats()
        inspection_anchors = _safe_compute_queue_inspection_anchors()
        recent_recoveries = _safe_compute_recent_recoveries(settings=settings)
        degradation_details = _compute_queue_degradation_details(stats, settings=settings)
        degradation_reasons = tuple(detail.reason for detail in degradation_details)
        if degradation_reasons:
            return RuntimeQueueStatus(
                status="degraded",
                reason=degradation_reasons[0],
                degradation_reasons=degradation_reasons,
                degradation_details=degradation_details,
                stats=stats,
                inspection_anchors=inspection_anchors,
                recent_recoveries=recent_recoveries,
            )
        return RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=stats,
            inspection_anchors=inspection_anchors,
            recent_recoveries=recent_recoveries,
        )
    except Exception as exc:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=type(exc).__name__,
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )


def _build_lineage_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )
    lineage_storage_status = check_lineage_storage_ready()
    if not lineage_storage_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=lineage_storage_status.reason or "lineage_storage_unavailable",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )
    try:
        storage_capacity = get_lineage_storage_capacity()
    except Exception:
        return RuntimeQueueStatus(
            status="unavailable",
            reason="lineage_storage_capacity_unreadable",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )
    try:
        stats = lineage_metadata_store.get_pending_payload_stats()
        inspection_anchors = _safe_lineage_queue_inspection_anchors()
        recent_recoveries = _safe_lineage_recent_recoveries(settings=settings)
        degradation_details = _lineage_queue_degradation_details(
            stats,
            storage_capacity=storage_capacity,
            settings=settings,
        )
        degradation_reasons = tuple(detail.reason for detail in degradation_details)
        if degradation_reasons:
            return RuntimeQueueStatus(
                status="degraded",
                reason=degradation_reasons[0],
                degradation_reasons=degradation_reasons,
                degradation_details=degradation_details,
                stats=stats,
                inspection_anchors=inspection_anchors,
                recent_recoveries=recent_recoveries,
                storage_capacity=storage_capacity,
            )
        return RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=stats,
            inspection_anchors=inspection_anchors,
            recent_recoveries=recent_recoveries,
            storage_capacity=storage_capacity,
        )
    except Exception as exc:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=type(exc).__name__,
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )


def _safe_compute_queue_inspection_anchors() -> ComputeQueueInspectionAnchors | None:
    try:
        return compute_job_store.get_queue_inspection_anchors()
    except Exception:
        return None


def _safe_lineage_queue_inspection_anchors() -> LineageQueueInspectionAnchors | None:
    try:
        return lineage_metadata_store.get_queue_inspection_anchors()
    except Exception:
        return None


def _safe_compute_recent_recoveries(*, settings) -> tuple[ComputeRecoveryEvent, ...]:
    try:
        limit = max(0, int(getattr(settings, "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT", 5)))
        if limit == 0:
            return ()
        page = compute_job_store.list_recent_recoveries(limit=limit)
        return tuple(getattr(page, "items", page))
    except Exception:
        return ()


def _safe_lineage_recent_recoveries(*, settings) -> tuple[LineageRecoveryEvent, ...]:
    try:
        limit = max(0, int(getattr(settings, "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT", 5)))
        if limit == 0:
            return ()
        page = lineage_metadata_store.list_recent_recoveries(limit=limit)
        return tuple(getattr(page, "items", page))
    except Exception:
        return ()


def _build_recovery_drill_status(*, settings) -> RecoveryDrillStatus:
    threshold = getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS", 0.0)
    reclaim_threshold = getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0)
    active_run_status = _build_operator_action_status(
        artifact_directory=getattr(settings, "RECOVERY_DRILL_ARTIFACT_PATH", Path("artifacts/durable-recovery-drill")),
        action_name="recovery_drill",
    )
    try:
        snapshot = build_recovery_drill_history_snapshot(limit=1)
    except Exception as exc:
        return RecoveryDrillStatus(
            status="unavailable",
            reason=type(exc).__name__,
            active_run_status=active_run_status.status,
            active_run_reason=active_run_status.reason,
            active_run_count=active_run_status.active_run_count,
            oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
            oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
            oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
            oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
            oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
            latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
            latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
            latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
            latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
            latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
            latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
            reclaimed_run_count=active_run_status.reclaimed_run_count,
            recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_backup_identifier=None,
            latest_age_seconds=None,
            degradation_reasons=(),
            degradation_details=(),
        )

    if snapshot.status != "available":
        if snapshot.reason in {
            "recovery_drill_artifact_directory_missing",
            "recovery_drill_manifest_missing",
        }:
            return _build_missing_recovery_drill_status(threshold=threshold, active_run_status=active_run_status)
        return RecoveryDrillStatus(
            status="unavailable",
            reason=snapshot.reason or snapshot.status,
            active_run_status=active_run_status.status,
            active_run_reason=active_run_status.reason,
            active_run_count=active_run_status.active_run_count,
            oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
            oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
            oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
            oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
            oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
            latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
            latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
            latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
            latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
            latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
            latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
            reclaimed_run_count=active_run_status.reclaimed_run_count,
            recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_backup_identifier=None,
            latest_age_seconds=None,
            degradation_reasons=(),
            degradation_details=(),
        )

    if not snapshot.entries:
        return _build_missing_recovery_drill_status(threshold=threshold, active_run_status=active_run_status)

    latest = snapshot.entries[0]
    latest_generated_at = datetime.fromisoformat(latest.generated_at_utc.replace("Z", "+00:00"))
    latest_age_seconds = max(0.0, (datetime.now(UTC) - latest_generated_at).total_seconds())
    degradation_details: list[RuntimeDegradationDetail] = []
    if latest.status != "passed":
        degradation_details.append(
            RuntimeDegradationDetail(
                reason="recovery_drill_latest_not_passed",
                observed_value=_as_decimal_number(0),
                threshold_value=_as_decimal_number(0),
            )
        )
    if threshold > 0 and latest_age_seconds >= threshold:
        degradation_details.append(
            RuntimeDegradationDetail(
                reason="recovery_drill_age_exceeded",
                observed_value=_as_decimal_number(latest_age_seconds),
                threshold_value=_as_decimal_number(threshold),
            )
        )
    if reclaim_threshold > 0 and active_run_status.reclaimed_run_count >= reclaim_threshold:
        degradation_details.append(
            RuntimeDegradationDetail(
                reason="recovery_drill_reclaim_pressure_exceeded",
                observed_value=_as_decimal_number(active_run_status.reclaimed_run_count),
                threshold_value=_as_decimal_number(reclaim_threshold),
            )
        )
    reasons: tuple[str, ...] = tuple(detail.reason for detail in degradation_details)
    return RecoveryDrillStatus(
        status="degraded" if reasons else "available",
        reason=reasons[0] if reasons else None,
        active_run_status=active_run_status.status,
        active_run_reason=active_run_status.reason,
        active_run_count=active_run_status.active_run_count,
        oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
        oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
        oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
        oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
        oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
        latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
        latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
        latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
        latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
        latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
        latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
        reclaimed_run_count=active_run_status.reclaimed_run_count,
        recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
        latest_generated_at_utc=latest.generated_at_utc,
        latest_status=latest.status,
        latest_operator_id=latest.operator_id,
        latest_backup_identifier=latest.backup_identifier,
        latest_age_seconds=latest_age_seconds,
        degradation_reasons=reasons,
        degradation_details=tuple(degradation_details),
    )


def _build_runtime_retention_status(*, settings) -> RuntimeRetentionStatus:
    threshold = getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0)
    reclaim_threshold = getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0)
    active_run_status = _build_operator_action_status(
        artifact_directory=getattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", Path("artifacts/runtime-retention-cleanup")),
        action_name="runtime_retention_cleanup",
    )
    try:
        snapshot = build_runtime_retention_history_snapshot(limit=1)
    except Exception as exc:
        return RuntimeRetentionStatus(
            status="unavailable",
            reason=type(exc).__name__,
            active_run_status=active_run_status.status,
            active_run_reason=active_run_status.reason,
            active_run_count=active_run_status.active_run_count,
            oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
            oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
            oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
            oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
            oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
            latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
            latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
            latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
            latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
            latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
            latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
            reclaimed_run_count=active_run_status.reclaimed_run_count,
            recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
            preview_status="unavailable",
            preview_reason="runtime_retention_preview_unavailable",
            current_cutoff_utc=None,
            current_retention_days=None,
            current_prunable_execution_count=None,
            current_prunable_compute_job_count=None,
            current_prunable_async_result_count=None,
            current_prunable_lineage_record_count=None,
            current_prunable_lineage_artifact_count=None,
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_trigger_mode=None,
            latest_job_id=None,
            latest_cleanup_mode=None,
            latest_retention_days=None,
            latest_age_seconds=None,
            degradation_reasons=(),
            degradation_details=(),
        )
    preview_status, preview_reason, preview_summary = _build_runtime_retention_preview()

    if snapshot.status != "available":
        if snapshot.reason in {
            "runtime_retention_artifact_directory_missing",
            "runtime_retention_manifest_missing",
        }:
            return _build_missing_runtime_retention_status(
                threshold=threshold,
                active_run_status=active_run_status,
                preview_status=preview_status,
                preview_reason=preview_reason,
                preview_summary=preview_summary,
            )
        return RuntimeRetentionStatus(
            status="unavailable",
            reason=snapshot.reason or snapshot.status,
            active_run_status=active_run_status.status,
            active_run_reason=active_run_status.reason,
            active_run_count=active_run_status.active_run_count,
            oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
            oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
            oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
            oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
            oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
            latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
            latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
            latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
            latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
            latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
            latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
            reclaimed_run_count=active_run_status.reclaimed_run_count,
            recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
            preview_status=preview_status,
            preview_reason=preview_reason,
            current_cutoff_utc=None if preview_summary is None else preview_summary.cutoff_utc,
            current_retention_days=None if preview_summary is None else preview_summary.retention_days,
            current_prunable_execution_count=(
                None if preview_summary is None else preview_summary.prunable_execution_count
            ),
            current_prunable_compute_job_count=(
                None if preview_summary is None else preview_summary.prunable_compute_job_count
            ),
            current_prunable_async_result_count=(
                None if preview_summary is None else preview_summary.prunable_async_result_count
            ),
            current_prunable_lineage_record_count=(
                None if preview_summary is None else preview_summary.prunable_lineage_record_count
            ),
            current_prunable_lineage_artifact_count=(
                None if preview_summary is None else preview_summary.prunable_lineage_artifact_count
            ),
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_trigger_mode=None,
            latest_job_id=None,
            latest_cleanup_mode=None,
            latest_retention_days=None,
            latest_age_seconds=None,
            degradation_reasons=(),
            degradation_details=(),
        )

    if not snapshot.entries:
        return _build_missing_runtime_retention_status(
            threshold=threshold,
            active_run_status=active_run_status,
            preview_status=preview_status,
            preview_reason=preview_reason,
            preview_summary=preview_summary,
        )

    latest = snapshot.entries[0]
    latest_generated_at = datetime.fromisoformat(latest.generated_at_utc.replace("Z", "+00:00"))
    latest_age_seconds = max(0.0, (datetime.now(UTC) - latest_generated_at).total_seconds())
    degradation_details: list[RuntimeDegradationDetail] = []
    if latest.cleanup_mode != "apply":
        degradation_details.append(
            RuntimeDegradationDetail(
                reason="runtime_retention_latest_not_applied",
                observed_value=_as_decimal_number(0),
                threshold_value=_as_decimal_number(0),
            )
        )
    if threshold > 0 and latest_age_seconds >= threshold:
        degradation_details.append(
            RuntimeDegradationDetail(
                reason="runtime_retention_age_exceeded",
                observed_value=_as_decimal_number(latest_age_seconds),
                threshold_value=_as_decimal_number(threshold),
            )
        )
    if reclaim_threshold > 0 and active_run_status.reclaimed_run_count >= reclaim_threshold:
        degradation_details.append(
            RuntimeDegradationDetail(
                reason="runtime_retention_reclaim_pressure_exceeded",
                observed_value=_as_decimal_number(active_run_status.reclaimed_run_count),
                threshold_value=_as_decimal_number(reclaim_threshold),
            )
        )
    reasons: tuple[str, ...] = tuple(detail.reason for detail in degradation_details)
    return RuntimeRetentionStatus(
        status="degraded" if reasons else "available",
        reason=reasons[0] if reasons else None,
        active_run_status=active_run_status.status,
        active_run_reason=active_run_status.reason,
        active_run_count=active_run_status.active_run_count,
        oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
        oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
        oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
        oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
        oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
        latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
        latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
        latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
        latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
        latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
        latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
        reclaimed_run_count=active_run_status.reclaimed_run_count,
        recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
        preview_status=preview_status,
        preview_reason=preview_reason,
        current_cutoff_utc=None if preview_summary is None else preview_summary.cutoff_utc,
        current_retention_days=None if preview_summary is None else preview_summary.retention_days,
        current_prunable_execution_count=None if preview_summary is None else preview_summary.prunable_execution_count,
        current_prunable_compute_job_count=(
            None if preview_summary is None else preview_summary.prunable_compute_job_count
        ),
        current_prunable_async_result_count=(
            None if preview_summary is None else preview_summary.prunable_async_result_count
        ),
        current_prunable_lineage_record_count=(
            None if preview_summary is None else preview_summary.prunable_lineage_record_count
        ),
        current_prunable_lineage_artifact_count=(
            None if preview_summary is None else preview_summary.prunable_lineage_artifact_count
        ),
        latest_generated_at_utc=latest.generated_at_utc,
        latest_status=latest.status,
        latest_operator_id=latest.operator_id,
        latest_trigger_mode=latest.trigger_mode,
        latest_job_id=latest.job_id,
        latest_cleanup_mode=latest.cleanup_mode,
        latest_retention_days=latest.retention_days,
        latest_age_seconds=latest_age_seconds,
        degradation_reasons=reasons,
        degradation_details=tuple(degradation_details),
    )


def _compute_queue_degradation_details(stats: ComputeQueueStats, *, settings) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    if (
        settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT > 0
        and stats.retry_backlog_count >= settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_retry_backlog_exceeded",
                observed_value=_as_decimal_number(stats.retry_backlog_count),
                threshold_value=_as_decimal_number(settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT > 0
        and stats.terminal_failure_count >= settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_terminal_failure_exceeded",
                observed_value=_as_decimal_number(stats.terminal_failure_count),
                threshold_value=_as_decimal_number(settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT > 0
        and stats.lease_expired_count >= settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_lease_expiry_pressure_exceeded",
                observed_value=_as_decimal_number(stats.lease_expired_count),
                threshold_value=_as_decimal_number(settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_pending_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_pending_age_exceeded",
                observed_value=_as_decimal_number(stats.oldest_pending_age_seconds),
                threshold_value=_as_decimal_number(settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_leased_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_leased_age_exceeded",
                observed_value=_as_decimal_number(stats.oldest_leased_age_seconds),
                threshold_value=_as_decimal_number(settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_running_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_running_age_exceeded",
                observed_value=_as_decimal_number(stats.oldest_running_age_seconds),
                threshold_value=_as_decimal_number(settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS),
            )
        )
    return tuple(details)


def _lineage_queue_degradation_details(
    stats: LineageQueueStats,
    *,
    storage_capacity: LineageStorageCapacitySnapshot,
    settings,
) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    lineage_leased_age_degrade_seconds = getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0)
    lineage_retry_backlog_degrade_count = getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0)
    lineage_terminal_failure_degrade_count = getattr(
        settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0
    )
    lineage_pending_age_degrade_seconds = getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0)
    if lineage_leased_age_degrade_seconds > 0 and stats.oldest_leased_age_seconds >= lineage_leased_age_degrade_seconds:
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_leased_age_exceeded",
                observed_value=_as_decimal_number(stats.oldest_leased_age_seconds),
                threshold_value=_as_decimal_number(lineage_leased_age_degrade_seconds),
            )
        )
    if lineage_retry_backlog_degrade_count > 0 and stats.retry_backlog_count >= lineage_retry_backlog_degrade_count:
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_retry_backlog_exceeded",
                observed_value=_as_decimal_number(stats.retry_backlog_count),
                threshold_value=_as_decimal_number(lineage_retry_backlog_degrade_count),
            )
        )
    if (
        lineage_terminal_failure_degrade_count > 0
        and stats.terminal_failure_count >= lineage_terminal_failure_degrade_count
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_terminal_failure_exceeded",
                observed_value=_as_decimal_number(stats.terminal_failure_count),
                threshold_value=_as_decimal_number(lineage_terminal_failure_degrade_count),
            )
        )
    if (
        lineage_pending_age_degrade_seconds > 0
        and stats.oldest_pending_age_seconds >= lineage_pending_age_degrade_seconds
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_pending_age_exceeded",
                observed_value=_as_decimal_number(stats.oldest_pending_age_seconds),
                threshold_value=_as_decimal_number(lineage_pending_age_degrade_seconds),
            )
        )
    lineage_storage_min_free_bytes = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0)
    lineage_storage_min_free_ratio = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0)
    if lineage_storage_min_free_bytes > 0 and storage_capacity.free_bytes <= lineage_storage_min_free_bytes:
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_storage_free_bytes_below_threshold",
                observed_value=_as_decimal_number(storage_capacity.free_bytes),
                threshold_value=_as_decimal_number(lineage_storage_min_free_bytes),
            )
        )
    if lineage_storage_min_free_ratio > 0 and storage_capacity.free_ratio <= lineage_storage_min_free_ratio:
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_storage_free_ratio_below_threshold",
                observed_value=_as_decimal_number(storage_capacity.free_ratio),
                threshold_value=_as_decimal_number(lineage_storage_min_free_ratio),
            )
        )
    return tuple(details)


def _as_decimal_number(value: object) -> Decimal:
    return Decimal(str(value))


def _build_missing_recovery_drill_status(
    *,
    threshold: float,
    active_run_status: OperatorActionStatus,
) -> RecoveryDrillStatus:
    details: tuple[RuntimeDegradationDetail, ...] = ()
    missing_history_reasons: tuple[str, ...] = ()
    if threshold > 0:
        missing_history_reasons = ("recovery_drill_history_unavailable",)
        details = (
            RuntimeDegradationDetail(
                reason="recovery_drill_history_unavailable",
                observed_value=_as_decimal_number(0),
                threshold_value=_as_decimal_number(threshold),
            ),
        )
    return RecoveryDrillStatus(
        status="available" if not missing_history_reasons else "degraded",
        reason=None if not missing_history_reasons else missing_history_reasons[0],
        active_run_status=active_run_status.status,
        active_run_reason=active_run_status.reason,
        active_run_count=active_run_status.active_run_count,
        oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
        oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
        oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
        oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
        oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
        latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
        latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
        latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
        latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
        latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
        latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
        reclaimed_run_count=active_run_status.reclaimed_run_count,
        recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
        latest_generated_at_utc=None,
        latest_status=None,
        latest_operator_id=None,
        latest_backup_identifier=None,
        latest_age_seconds=None,
        degradation_reasons=missing_history_reasons,
        degradation_details=details,
    )


def _build_missing_runtime_retention_status(
    *,
    threshold: float,
    active_run_status: OperatorActionStatus,
    preview_status: str,
    preview_reason: str | None,
    preview_summary,
) -> RuntimeRetentionStatus:
    details: tuple[RuntimeDegradationDetail, ...] = ()
    missing_history_reasons: tuple[str, ...] = ()
    if threshold > 0:
        missing_history_reasons = ("runtime_retention_history_unavailable",)
        details = (
            RuntimeDegradationDetail(
                reason="runtime_retention_history_unavailable",
                observed_value=_as_decimal_number(0),
                threshold_value=_as_decimal_number(threshold),
            ),
        )
    return RuntimeRetentionStatus(
        status="available" if not missing_history_reasons else "degraded",
        reason=None if not missing_history_reasons else missing_history_reasons[0],
        active_run_status=active_run_status.status,
        active_run_reason=active_run_status.reason,
        active_run_count=active_run_status.active_run_count,
        oldest_active_run_operator_id=active_run_status.oldest_active_run_operator_id,
        oldest_active_run_tenant_id=active_run_status.oldest_active_run_tenant_id,
        oldest_active_run_governed_target=active_run_status.oldest_active_run_governed_target,
        oldest_active_run_acquired_at_utc=active_run_status.oldest_active_run_acquired_at_utc,
        oldest_active_run_age_seconds=active_run_status.oldest_active_run_age_seconds,
        latest_reclaimed_run_operator_id=active_run_status.latest_reclaimed_run_operator_id,
        latest_reclaimed_run_tenant_id=active_run_status.latest_reclaimed_run_tenant_id,
        latest_reclaimed_run_governed_target=active_run_status.latest_reclaimed_run_governed_target,
        latest_reclaimed_run_acquired_at_utc=active_run_status.latest_reclaimed_run_acquired_at_utc,
        latest_reclaimed_run_reclaimed_at_utc=active_run_status.latest_reclaimed_run_reclaimed_at_utc,
        latest_reclaimed_run_age_seconds=active_run_status.latest_reclaimed_run_age_seconds,
        reclaimed_run_count=active_run_status.reclaimed_run_count,
        recent_reclaimed_runs=active_run_status.recent_reclaimed_runs,
        preview_status=preview_status,
        preview_reason=preview_reason,
        current_cutoff_utc=None if preview_summary is None else preview_summary.cutoff_utc,
        current_retention_days=None if preview_summary is None else preview_summary.retention_days,
        current_prunable_execution_count=None if preview_summary is None else preview_summary.prunable_execution_count,
        current_prunable_compute_job_count=(
            None if preview_summary is None else preview_summary.prunable_compute_job_count
        ),
        current_prunable_async_result_count=(
            None if preview_summary is None else preview_summary.prunable_async_result_count
        ),
        current_prunable_lineage_record_count=(
            None if preview_summary is None else preview_summary.prunable_lineage_record_count
        ),
        current_prunable_lineage_artifact_count=(
            None if preview_summary is None else preview_summary.prunable_lineage_artifact_count
        ),
        latest_generated_at_utc=None,
        latest_status=None,
        latest_operator_id=None,
        latest_trigger_mode=None,
        latest_job_id=None,
        latest_cleanup_mode=None,
        latest_retention_days=None,
        latest_age_seconds=None,
        degradation_reasons=missing_history_reasons,
        degradation_details=details,
    )


def _build_runtime_retention_preview():
    try:
        summary = run_runtime_retention_cleanup(dry_run=True)
        return "available", None, summary
    except Exception as exc:
        return "unavailable", type(exc).__name__, None


def _build_operator_action_status(*, artifact_directory, action_name: str) -> OperatorActionStatus:
    try:
        snapshot = build_operator_action_lease_snapshot(
            artifact_directory=artifact_directory,
            action_name=action_name,
        )
    except Exception as exc:
        return OperatorActionStatus(
            status="unavailable",
            reason=type(exc).__name__,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=None,
            latest_reclaimed_run_tenant_id=None,
            latest_reclaimed_run_governed_target=None,
            latest_reclaimed_run_acquired_at_utc=None,
            latest_reclaimed_run_reclaimed_at_utc=None,
            latest_reclaimed_run_age_seconds=None,
            reclaimed_run_count=0,
            recent_reclaimed_runs=(),
        )
    if snapshot.status != "available":
        return OperatorActionStatus(
            status="unavailable",
            reason=snapshot.reason,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=None,
            latest_reclaimed_run_tenant_id=None,
            latest_reclaimed_run_governed_target=None,
            latest_reclaimed_run_acquired_at_utc=None,
            latest_reclaimed_run_reclaimed_at_utc=None,
            latest_reclaimed_run_age_seconds=None,
            reclaimed_run_count=0,
            recent_reclaimed_runs=(),
        )
    latest_reclaimed_run = snapshot.latest_reclaimed_lease
    recent_reclaimed_runs = _build_recent_operator_action_reclaims(snapshot=snapshot)
    latest_reclaimed_run_age_seconds = None
    if latest_reclaimed_run is not None:
        reclaimed_at = datetime.fromisoformat(latest_reclaimed_run.reclaimed_at_utc.replace("Z", "+00:00"))
        if reclaimed_at.tzinfo is None:
            reclaimed_at = reclaimed_at.replace(tzinfo=UTC)
        else:
            reclaimed_at = reclaimed_at.astimezone(UTC)
        latest_reclaimed_run_age_seconds = max(0.0, (datetime.now(UTC) - reclaimed_at).total_seconds())
    if not snapshot.active_leases:
        return OperatorActionStatus(
            status="available",
            reason=None,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.operator_id
            ),
            latest_reclaimed_run_tenant_id=None if latest_reclaimed_run is None else latest_reclaimed_run.tenant_id,
            latest_reclaimed_run_governed_target=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.governed_target
            ),
            latest_reclaimed_run_acquired_at_utc=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.acquired_at_utc
            ),
            latest_reclaimed_run_reclaimed_at_utc=(
                None if latest_reclaimed_run is None else latest_reclaimed_run.reclaimed_at_utc
            ),
            latest_reclaimed_run_age_seconds=latest_reclaimed_run_age_seconds,
            reclaimed_run_count=0 if latest_reclaimed_run is None else latest_reclaimed_run.reclaim_count,
            recent_reclaimed_runs=recent_reclaimed_runs,
        )
    oldest = snapshot.active_leases[0]
    acquired_at = datetime.fromisoformat(oldest.acquired_at_utc.replace("Z", "+00:00"))
    if acquired_at.tzinfo is None:
        acquired_at = acquired_at.replace(tzinfo=UTC)
    else:
        acquired_at = acquired_at.astimezone(UTC)
    return OperatorActionStatus(
        status="active",
        reason=None,
        active_run_count=len(snapshot.active_leases),
        oldest_active_run_operator_id=oldest.operator_id,
        oldest_active_run_tenant_id=oldest.tenant_id,
        oldest_active_run_governed_target=oldest.governed_target,
        oldest_active_run_acquired_at_utc=oldest.acquired_at_utc,
        oldest_active_run_age_seconds=max(0.0, (datetime.now(UTC) - acquired_at).total_seconds()),
        latest_reclaimed_run_operator_id=None if latest_reclaimed_run is None else latest_reclaimed_run.operator_id,
        latest_reclaimed_run_tenant_id=None if latest_reclaimed_run is None else latest_reclaimed_run.tenant_id,
        latest_reclaimed_run_governed_target=(
            None if latest_reclaimed_run is None else latest_reclaimed_run.governed_target
        ),
        latest_reclaimed_run_acquired_at_utc=(
            None if latest_reclaimed_run is None else latest_reclaimed_run.acquired_at_utc
        ),
        latest_reclaimed_run_reclaimed_at_utc=(
            None if latest_reclaimed_run is None else latest_reclaimed_run.reclaimed_at_utc
        ),
        latest_reclaimed_run_age_seconds=latest_reclaimed_run_age_seconds,
        reclaimed_run_count=0 if latest_reclaimed_run is None else latest_reclaimed_run.reclaim_count,
        recent_reclaimed_runs=recent_reclaimed_runs,
    )


def _build_recent_operator_action_reclaims(*, snapshot) -> tuple[RecentOperatorActionReclaim, ...]:
    events = tuple(getattr(snapshot, "recent_reclaimed_leases", ()))
    return tuple(
        RecentOperatorActionReclaim(
            operator_id=event.operator_id,
            tenant_id=event.tenant_id,
            governed_target=event.governed_target,
            acquired_at_utc=event.acquired_at_utc,
            reclaimed_at_utc=event.reclaimed_at_utc,
            reclaimed_age_seconds=max(
                0.0,
                (datetime.now(UTC) - _parse_reclaimed_at_utc(event.reclaimed_at_utc)).total_seconds(),
            ),
            reclaim_count=event.reclaim_count,
        )
        for event in events[:5]
    )


def _parse_reclaimed_at_utc(timestamp_utc: str) -> datetime:
    reclaimed_at = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    if reclaimed_at.tzinfo is None:
        return reclaimed_at.replace(tzinfo=UTC)
    return reclaimed_at.astimezone(UTC)


def _collect_runtime_degradation_reasons(
    *,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
    recovery_drill: RecoveryDrillStatus,
    runtime_retention: RuntimeRetentionStatus,
) -> tuple[str, ...]:
    reasons: list[str] = []

    for prefix, queue_status in (
        ("compute_queue", compute_queue),
        ("lineage_queue", lineage_queue),
    ):
        if queue_status.status == "degraded":
            reasons.extend(f"{prefix}:{reason}" for reason in queue_status.degradation_reasons)
        elif queue_status.status == "unavailable" and queue_status.reason is not None:
            reasons.append(f"{prefix}:{queue_status.reason}")

    if recovery_drill.status == "degraded":
        reasons.extend(f"recovery_drill:{reason}" for reason in recovery_drill.degradation_reasons)
    elif recovery_drill.status == "unavailable" and recovery_drill.reason is not None:
        reasons.append(f"recovery_drill:{recovery_drill.reason}")

    if runtime_retention.status == "degraded":
        reasons.extend(f"runtime_retention:{reason}" for reason in runtime_retention.degradation_reasons)
    elif runtime_retention.status == "unavailable" and runtime_retention.reason is not None:
        reasons.append(f"runtime_retention:{runtime_retention.reason}")

    return tuple(reasons)


def _collect_runtime_degradation_details(
    *,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
    recovery_drill: RecoveryDrillStatus,
    runtime_retention: RuntimeRetentionStatus,
) -> tuple[RuntimeDegradationDetail, ...]:
    return (
        compute_queue.degradation_details
        + lineage_queue.degradation_details
        + recovery_drill.degradation_details
        + runtime_retention.degradation_details
    )


def _build_compute_queue_policy(*, settings) -> ComputeQueueDegradationPolicy:
    return ComputeQueueDegradationPolicy(
        pending_age_seconds=settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
        leased_age_seconds=settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
        running_age_seconds=settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
        retry_backlog_count=settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
        lease_expiry_count=settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
        terminal_failure_count=settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )


def _build_lineage_queue_policy(*, settings) -> LineageQueueDegradationPolicy:
    return LineageQueueDegradationPolicy(
        pending_age_seconds=getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
        leased_age_seconds=getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
        retry_backlog_count=getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
        terminal_failure_count=getattr(settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
        storage_min_free_bytes=getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0),
        storage_min_free_ratio=getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0),
    )


def _build_recovery_drill_policy(*, settings) -> RecoveryDrillDegradationPolicy:
    return RecoveryDrillDegradationPolicy(
        max_age_seconds=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS", 0.0),
        reclaim_count=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0),
    )


def _build_runtime_retention_policy(*, settings) -> RuntimeRetentionDegradationPolicy:
    return RuntimeRetentionDegradationPolicy(
        max_age_seconds=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0),
        reclaim_count=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0),
    )
