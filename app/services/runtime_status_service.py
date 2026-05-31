from __future__ import annotations

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
from app.services.runtime_degradation_policy import (
    ThresholdComparison,
    as_decimal_number,
    threshold_breach_values,
)
from app.services.runtime_retention_history_service import (
    build_runtime_retention_history_snapshot,
)
from app.services.runtime_retention_service import run_runtime_retention_cleanup
from app.services.runtime_status_domain import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    OperatorActionStatus,
    RecentOperatorActionReclaim,
    RecoveryDrillDegradationPolicy,
    RecoveryDrillStatus,
    RuntimeDegradationDetail,
    RuntimeQueueStatus,
    RuntimeRetentionDegradationPolicy,
    RuntimeRetentionPreviewFields,
    RuntimeRetentionStatus,
    RuntimeStatusSnapshot,
)


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
    active_run_age_threshold = getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS", 0.0)
    reclaim_threshold = getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0)
    active_run_status = _build_operator_action_status(
        artifact_directory=getattr(settings, "RECOVERY_DRILL_ARTIFACT_PATH", Path("artifacts/durable-recovery-drill")),
        action_name="recovery_drill",
    )
    try:
        snapshot = build_recovery_drill_history_snapshot(limit=1)
    except Exception as exc:
        return _build_unavailable_recovery_drill_status(
            reason=type(exc).__name__,
            active_run_status=active_run_status,
        )

    if snapshot.status != "available":
        if snapshot.reason in {
            "recovery_drill_artifact_directory_missing",
            "recovery_drill_manifest_missing",
        }:
            return _build_missing_recovery_drill_status(threshold=threshold, active_run_status=active_run_status)
        return _build_unavailable_recovery_drill_status(
            reason=snapshot.reason or snapshot.status,
            active_run_status=active_run_status,
        )

    if not snapshot.entries:
        return _build_missing_recovery_drill_status(threshold=threshold, active_run_status=active_run_status)

    latest = snapshot.entries[0]
    latest_age_seconds = _age_seconds_since(latest.generated_at_utc)
    degradation_details: list[RuntimeDegradationDetail] = []
    _append_lifecycle_state_degradation_detail(
        degradation_details,
        is_healthy=latest.status == "passed",
        reason="recovery_drill_latest_not_passed",
    )
    _append_latest_history_age_degradation_detail(
        degradation_details,
        reason="recovery_drill_age_exceeded",
        latest_age_seconds=latest_age_seconds,
        threshold=threshold,
    )
    _append_operator_action_degradation_details(
        degradation_details,
        active_run_status=active_run_status,
        active_run_age_threshold=active_run_age_threshold,
        active_run_reason="recovery_drill_active_run_age_exceeded",
        reclaim_threshold=reclaim_threshold,
        reclaim_reason="recovery_drill_reclaim_pressure_exceeded",
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


def _build_unavailable_recovery_drill_status(
    *,
    reason: str,
    active_run_status: OperatorActionStatus,
) -> RecoveryDrillStatus:
    return RecoveryDrillStatus(
        status="unavailable",
        reason=reason,
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


def _build_runtime_retention_status(*, settings) -> RuntimeRetentionStatus:
    threshold = getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0)
    active_run_age_threshold = getattr(
        settings,
        "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
        0.0,
    )
    reclaim_threshold = getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0)
    active_run_status = _build_operator_action_status(
        artifact_directory=getattr(
            settings, "RUNTIME_RETENTION_ARTIFACT_PATH", Path("artifacts/runtime-retention-cleanup")
        ),
        action_name="runtime_retention_cleanup",
    )
    try:
        snapshot = build_runtime_retention_history_snapshot(limit=1)
    except Exception as exc:
        return _build_unavailable_runtime_retention_status(
            reason=type(exc).__name__,
            active_run_status=active_run_status,
            preview_status="unavailable",
            preview_reason="runtime_retention_preview_unavailable",
            preview_summary=None,
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
        return _build_unavailable_runtime_retention_status(
            reason=snapshot.reason or snapshot.status,
            active_run_status=active_run_status,
            preview_status=preview_status,
            preview_reason=preview_reason,
            preview_summary=preview_summary,
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
    latest_age_seconds = _age_seconds_since(latest.generated_at_utc)
    degradation_details: list[RuntimeDegradationDetail] = []
    _append_lifecycle_state_degradation_detail(
        degradation_details,
        is_healthy=latest.cleanup_mode == "apply",
        reason="runtime_retention_latest_not_applied",
    )
    _append_latest_history_age_degradation_detail(
        degradation_details,
        reason="runtime_retention_age_exceeded",
        latest_age_seconds=latest_age_seconds,
        threshold=threshold,
    )
    _append_operator_action_degradation_details(
        degradation_details,
        active_run_status=active_run_status,
        active_run_age_threshold=active_run_age_threshold,
        active_run_reason="runtime_retention_active_run_age_exceeded",
        reclaim_threshold=reclaim_threshold,
        reclaim_reason="runtime_retention_reclaim_pressure_exceeded",
    )
    reasons: tuple[str, ...] = tuple(detail.reason for detail in degradation_details)
    preview_fields = _runtime_retention_preview_fields(
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
    )
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
        preview_status=preview_fields.status,
        preview_reason=preview_fields.reason,
        current_cutoff_utc=preview_fields.cutoff_utc,
        current_retention_days=preview_fields.retention_days,
        current_prunable_execution_count=preview_fields.prunable_execution_count,
        current_prunable_compute_job_count=preview_fields.prunable_compute_job_count,
        current_prunable_async_result_count=preview_fields.prunable_async_result_count,
        current_prunable_lineage_record_count=preview_fields.prunable_lineage_record_count,
        current_prunable_lineage_artifact_count=preview_fields.prunable_lineage_artifact_count,
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


def _build_unavailable_runtime_retention_status(
    *,
    reason: str,
    active_run_status: OperatorActionStatus,
    preview_status: str,
    preview_reason: str | None,
    preview_summary,
) -> RuntimeRetentionStatus:
    preview_fields = _runtime_retention_preview_fields(
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
    )
    return RuntimeRetentionStatus(
        status="unavailable",
        reason=reason,
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
        preview_status=preview_fields.status,
        preview_reason=preview_fields.reason,
        current_cutoff_utc=preview_fields.cutoff_utc,
        current_retention_days=preview_fields.retention_days,
        current_prunable_execution_count=preview_fields.prunable_execution_count,
        current_prunable_compute_job_count=preview_fields.prunable_compute_job_count,
        current_prunable_async_result_count=preview_fields.prunable_async_result_count,
        current_prunable_lineage_record_count=preview_fields.prunable_lineage_record_count,
        current_prunable_lineage_artifact_count=preview_fields.prunable_lineage_artifact_count,
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


def _compute_queue_degradation_details(stats: ComputeQueueStats, *, settings) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    _append_degradation_detail_if_breached(
        details,
        reason="compute_retry_backlog_exceeded",
        observed_value=stats.retry_backlog_count,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="compute_terminal_failure_exceeded",
        observed_value=stats.terminal_failure_count,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="compute_lease_expiry_pressure_exceeded",
        observed_value=stats.lease_expired_count,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="compute_pending_age_exceeded",
        observed_value=stats.oldest_pending_age_seconds,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="compute_leased_age_exceeded",
        observed_value=stats.oldest_leased_age_seconds,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="compute_running_age_exceeded",
        observed_value=stats.oldest_running_age_seconds,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
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
    _append_degradation_detail_if_breached(
        details,
        reason="lineage_leased_age_exceeded",
        observed_value=stats.oldest_leased_age_seconds,
        threshold_value=lineage_leased_age_degrade_seconds,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="lineage_retry_backlog_exceeded",
        observed_value=stats.retry_backlog_count,
        threshold_value=lineage_retry_backlog_degrade_count,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="lineage_terminal_failure_exceeded",
        observed_value=stats.terminal_failure_count,
        threshold_value=lineage_terminal_failure_degrade_count,
    )
    _append_degradation_detail_if_breached(
        details,
        reason="lineage_pending_age_exceeded",
        observed_value=stats.oldest_pending_age_seconds,
        threshold_value=lineage_pending_age_degrade_seconds,
    )
    lineage_storage_min_free_bytes = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0)
    lineage_storage_min_free_ratio = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0)
    _append_degradation_detail_if_breached(
        details,
        reason="lineage_storage_free_bytes_below_threshold",
        observed_value=storage_capacity.free_bytes,
        threshold_value=lineage_storage_min_free_bytes,
        comparison="at_or_below",
    )
    _append_degradation_detail_if_breached(
        details,
        reason="lineage_storage_free_ratio_below_threshold",
        observed_value=storage_capacity.free_ratio,
        threshold_value=lineage_storage_min_free_ratio,
        comparison="at_or_below",
    )
    return tuple(details)


def _append_degradation_detail_if_breached(
    details: list[RuntimeDegradationDetail],
    *,
    reason: str,
    observed_value: object,
    threshold_value: object,
    comparison: ThresholdComparison = "at_or_above",
) -> None:
    breached_values = threshold_breach_values(
        observed_value=observed_value,
        threshold_value=threshold_value,
        comparison=comparison,
    )
    if breached_values is None:
        return
    observed_decimal, threshold_decimal = breached_values
    details.append(
        RuntimeDegradationDetail(
            reason=reason,
            observed_value=observed_decimal,
            threshold_value=threshold_decimal,
        )
    )


def _append_operator_action_degradation_details(
    details: list[RuntimeDegradationDetail],
    *,
    active_run_status: OperatorActionStatus,
    active_run_age_threshold: float,
    active_run_reason: str,
    reclaim_threshold: int,
    reclaim_reason: str,
) -> None:
    if active_run_status.status == "active" and active_run_status.oldest_active_run_age_seconds is not None:
        _append_degradation_detail_if_breached(
            details,
            reason=active_run_reason,
            observed_value=active_run_status.oldest_active_run_age_seconds,
            threshold_value=active_run_age_threshold,
        )
    _append_degradation_detail_if_breached(
        details,
        reason=reclaim_reason,
        observed_value=active_run_status.reclaimed_run_count,
        threshold_value=reclaim_threshold,
    )


def _append_latest_history_age_degradation_detail(
    details: list[RuntimeDegradationDetail],
    *,
    reason: str,
    latest_age_seconds: float,
    threshold: float,
) -> None:
    _append_degradation_detail_if_breached(
        details,
        reason=reason,
        observed_value=latest_age_seconds,
        threshold_value=threshold,
    )


def _append_lifecycle_state_degradation_detail(
    details: list[RuntimeDegradationDetail],
    *,
    is_healthy: bool,
    reason: str,
) -> None:
    if is_healthy:
        return
    details.append(
        RuntimeDegradationDetail(
            reason=reason,
            observed_value=_as_decimal_number(0),
            threshold_value=_as_decimal_number(0),
        )
    )


def _as_decimal_number(value: object) -> Decimal:
    return as_decimal_number(value)


def _build_missing_recovery_drill_status(
    *,
    threshold: float,
    active_run_status: OperatorActionStatus,
) -> RecoveryDrillStatus:
    missing_history_reasons, details = _missing_history_degradation(
        threshold=threshold,
        reason="recovery_drill_history_unavailable",
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
    missing_history_reasons, details = _missing_history_degradation(
        threshold=threshold,
        reason="runtime_retention_history_unavailable",
    )
    preview_fields = _runtime_retention_preview_fields(
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
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
        preview_status=preview_fields.status,
        preview_reason=preview_fields.reason,
        current_cutoff_utc=preview_fields.cutoff_utc,
        current_retention_days=preview_fields.retention_days,
        current_prunable_execution_count=preview_fields.prunable_execution_count,
        current_prunable_compute_job_count=preview_fields.prunable_compute_job_count,
        current_prunable_async_result_count=preview_fields.prunable_async_result_count,
        current_prunable_lineage_record_count=preview_fields.prunable_lineage_record_count,
        current_prunable_lineage_artifact_count=preview_fields.prunable_lineage_artifact_count,
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


def _missing_history_degradation(
    *,
    threshold: float,
    reason: str,
) -> tuple[tuple[str, ...], tuple[RuntimeDegradationDetail, ...]]:
    if threshold <= 0:
        return (), ()
    return (
        (reason,),
        (
            RuntimeDegradationDetail(
                reason=reason,
                observed_value=_as_decimal_number(0),
                threshold_value=_as_decimal_number(threshold),
            ),
        ),
    )


def _runtime_retention_preview_fields(
    *,
    preview_status: str,
    preview_reason: str | None,
    preview_summary,
) -> RuntimeRetentionPreviewFields:
    return RuntimeRetentionPreviewFields(
        status=preview_status,
        reason=preview_reason,
        cutoff_utc=None if preview_summary is None else preview_summary.cutoff_utc,
        retention_days=None if preview_summary is None else preview_summary.retention_days,
        prunable_execution_count=None if preview_summary is None else preview_summary.prunable_execution_count,
        prunable_compute_job_count=None if preview_summary is None else preview_summary.prunable_compute_job_count,
        prunable_async_result_count=None if preview_summary is None else preview_summary.prunable_async_result_count,
        prunable_lineage_record_count=None
        if preview_summary is None
        else preview_summary.prunable_lineage_record_count,
        prunable_lineage_artifact_count=None
        if preview_summary is None
        else preview_summary.prunable_lineage_artifact_count,
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
        latest_reclaimed_run_age_seconds = _age_seconds_since(latest_reclaimed_run.reclaimed_at_utc)
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
    return OperatorActionStatus(
        status="active",
        reason=None,
        active_run_count=len(snapshot.active_leases),
        oldest_active_run_operator_id=oldest.operator_id,
        oldest_active_run_tenant_id=oldest.tenant_id,
        oldest_active_run_governed_target=oldest.governed_target,
        oldest_active_run_acquired_at_utc=oldest.acquired_at_utc,
        oldest_active_run_age_seconds=_age_seconds_since(oldest.acquired_at_utc),
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
            reclaimed_age_seconds=_age_seconds_since(event.reclaimed_at_utc),
            reclaim_count=event.reclaim_count,
        )
        for event in events[:5]
    )


def _parse_reclaimed_at_utc(timestamp_utc: str) -> datetime:
    return _parse_utc_datetime(timestamp_utc)


def _age_seconds_since(timestamp_utc: str) -> float:
    return max(0.0, (datetime.now(UTC) - _parse_utc_datetime(timestamp_utc)).total_seconds())


def _parse_utc_datetime(timestamp_utc: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
        active_run_age_seconds=getattr(
            settings,
            "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
            0.0,
        ),
        reclaim_count=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0),
    )


def _build_runtime_retention_policy(*, settings) -> RuntimeRetentionDegradationPolicy:
    return RuntimeRetentionDegradationPolicy(
        max_age_seconds=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0),
        active_run_age_seconds=getattr(
            settings,
            "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
            0.0,
        ),
        reclaim_count=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0),
    )
