from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    check_durable_metadata_store_ready,
    check_lineage_storage_ready,
    get_lineage_storage_capacity,
)
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.recovery_drill_history_service import (
    build_recovery_drill_history_snapshot,
)
from app.services.runtime_retention_history_service import (
    build_runtime_retention_history_snapshot,
)
from app.services.runtime_status_degradation import (
    append_latest_history_age_degradation_detail as _append_latest_history_age_degradation_detail,
)
from app.services.runtime_status_degradation import (
    append_lifecycle_state_degradation_detail as _append_lifecycle_state_degradation_detail,
)
from app.services.runtime_status_degradation import (
    append_operator_action_degradation_details as _append_operator_action_degradation_details,
)
from app.services.runtime_status_degradation import (
    collect_runtime_degradation_details as _collect_runtime_degradation_details,
)
from app.services.runtime_status_degradation import (
    collect_runtime_degradation_reasons as _collect_runtime_degradation_reasons,
)
from app.services.runtime_status_degradation import (
    compute_queue_degradation_details as _compute_queue_degradation_details,
)
from app.services.runtime_status_degradation import (
    lineage_queue_degradation_details as _lineage_queue_degradation_details,
)
from app.services.runtime_status_domain import (
    RecoveryDrillStatus,
    RuntimeDegradationDetail,
    RuntimeQueueStatus,
    RuntimeRetentionStatus,
    RuntimeStatusSnapshot,
)
from app.services.runtime_status_lifecycle import (
    missing_recovery_drill_status as _build_missing_recovery_drill_status,
)
from app.services.runtime_status_lifecycle import (
    missing_runtime_retention_status as _build_missing_runtime_retention_status,
)
from app.services.runtime_status_lifecycle import (
    recovery_drill_degradation_details as _recovery_drill_degradation_details,
)
from app.services.runtime_status_lifecycle import (
    recovery_drill_status_from_latest as _recovery_drill_status_from_latest,
)
from app.services.runtime_status_lifecycle import (
    runtime_retention_status_from_latest as _runtime_retention_status_from_latest,
)
from app.services.runtime_status_lifecycle import (
    unavailable_recovery_drill_status as _build_unavailable_recovery_drill_status,
)
from app.services.runtime_status_lifecycle import (
    unavailable_runtime_retention_status as _build_unavailable_runtime_retention_status,
)
from app.services.runtime_status_operator_action import build_operator_action_status as _build_operator_action_status
from app.services.runtime_status_policy import (
    build_compute_queue_policy,
    build_lineage_queue_policy,
    build_recovery_drill_policy,
    build_runtime_retention_policy,
)
from app.services.runtime_status_queue import (
    runtime_queue_status_from_degradation as _runtime_queue_status_from_degradation,
)
from app.services.runtime_status_queue import (
    safe_compute_queue_inspection_anchors as _safe_compute_queue_inspection_anchors,
)
from app.services.runtime_status_queue import safe_compute_recent_recoveries as _safe_compute_recent_recoveries
from app.services.runtime_status_queue import (
    safe_lineage_queue_inspection_anchors as _safe_lineage_queue_inspection_anchors,
)
from app.services.runtime_status_queue import safe_lineage_recent_recoveries as _safe_lineage_recent_recoveries
from app.services.runtime_status_queue import unavailable_runtime_queue_status as _unavailable_runtime_queue_status
from app.services.runtime_status_retention_preview import (
    build_runtime_retention_preview as _build_runtime_retention_preview,
)
from app.services.runtime_status_time import age_seconds_since as _age_seconds_since


def build_runtime_status_snapshot(*, is_draining: bool) -> RuntimeStatusSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()
    settings = get_settings()
    compute_queue_policy = build_compute_queue_policy(settings=settings)
    lineage_queue_policy = build_lineage_queue_policy(settings=settings)
    recovery_drill_policy = build_recovery_drill_policy(settings=settings)
    runtime_retention_policy = build_runtime_retention_policy(settings=settings)

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
        return _unavailable_runtime_queue_status(
            reason=durability_status.reason or "durable_metadata_store_unreachable"
        )
    try:
        stats = compute_job_store.get_queue_stats()
        inspection_anchors = _safe_compute_queue_inspection_anchors()
        recent_recoveries = _safe_compute_recent_recoveries(settings=settings)
        degradation_details = _compute_queue_degradation_details(stats, settings=settings)
        return _runtime_queue_status_from_degradation(
            stats=stats,
            inspection_anchors=inspection_anchors,
            recent_recoveries=recent_recoveries,
            degradation_details=degradation_details,
        )
    except Exception as exc:
        return _unavailable_runtime_queue_status(reason=type(exc).__name__)


def _build_lineage_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return _unavailable_runtime_queue_status(
            reason=durability_status.reason or "durable_metadata_store_unreachable"
        )
    lineage_storage_status = check_lineage_storage_ready()
    if not lineage_storage_status.is_ready:
        return _unavailable_runtime_queue_status(reason=lineage_storage_status.reason or "lineage_storage_unavailable")
    try:
        storage_capacity = get_lineage_storage_capacity()
    except Exception:
        return _unavailable_runtime_queue_status(reason="lineage_storage_capacity_unreadable")
    try:
        stats = lineage_metadata_store.get_pending_payload_stats()
        inspection_anchors = _safe_lineage_queue_inspection_anchors()
        recent_recoveries = _safe_lineage_recent_recoveries(settings=settings)
        degradation_details = _lineage_queue_degradation_details(
            stats,
            storage_capacity=storage_capacity,
            settings=settings,
        )
        return _runtime_queue_status_from_degradation(
            stats=stats,
            inspection_anchors=inspection_anchors,
            recent_recoveries=recent_recoveries,
            degradation_details=degradation_details,
            storage_capacity=storage_capacity,
        )
    except Exception as exc:
        return _unavailable_runtime_queue_status(reason=type(exc).__name__)


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
    degradation_details = _recovery_drill_degradation_details(
        latest=latest,
        latest_age_seconds=latest_age_seconds,
        threshold=threshold,
        active_run_status=active_run_status,
        active_run_age_threshold=active_run_age_threshold,
        reclaim_threshold=reclaim_threshold,
    )
    return _recovery_drill_status_from_latest(
        latest=latest,
        latest_age_seconds=latest_age_seconds,
        active_run_status=active_run_status,
        degradation_details=degradation_details,
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
    return _runtime_retention_status_from_latest(
        latest=latest,
        latest_age_seconds=latest_age_seconds,
        active_run_status=active_run_status,
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
        degradation_details=tuple(degradation_details),
    )
