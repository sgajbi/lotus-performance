from __future__ import annotations

from app.services.compute_job_store import (
    ComputeQueueInspectionAnchors,
    ComputeQueueStats,
    ComputeRecoveryEvent,
    compute_job_store,
)
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    LineageStorageCapacitySnapshot,
    check_lineage_storage_ready,
    get_lineage_storage_capacity,
)
from app.services.lineage_metadata_store import (
    LineageQueueInspectionAnchors,
    LineageQueueStats,
    LineageRecoveryEvent,
    lineage_metadata_store,
)
from app.services.runtime_status_degradation import compute_queue_degradation_details, lineage_queue_degradation_details
from app.services.runtime_status_domain import RuntimeDegradationDetail, RuntimeQueueStatus


def build_compute_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return unavailable_runtime_queue_status(reason=durability_status.reason or "durable_metadata_store_unreachable")
    try:
        stats = compute_job_store.get_queue_stats()
        inspection_anchors = safe_compute_queue_inspection_anchors()
        recent_recoveries = safe_compute_recent_recoveries(settings=settings)
        degradation_details = compute_queue_degradation_details(stats, settings=settings)
        return runtime_queue_status_from_degradation(
            stats=stats,
            inspection_anchors=inspection_anchors,
            recent_recoveries=recent_recoveries,
            degradation_details=degradation_details,
        )
    except Exception as exc:
        return unavailable_runtime_queue_status(reason=type(exc).__name__)


def build_lineage_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return unavailable_runtime_queue_status(reason=durability_status.reason or "durable_metadata_store_unreachable")
    lineage_storage_status = check_lineage_storage_ready()
    if not lineage_storage_status.is_ready:
        return unavailable_runtime_queue_status(reason=lineage_storage_status.reason or "lineage_storage_unavailable")
    try:
        storage_capacity = get_lineage_storage_capacity()
    except Exception:
        return unavailable_runtime_queue_status(reason="lineage_storage_capacity_unreadable")
    try:
        stats = lineage_metadata_store.get_pending_payload_stats()
        inspection_anchors = safe_lineage_queue_inspection_anchors()
        recent_recoveries = safe_lineage_recent_recoveries(settings=settings)
        degradation_details = lineage_queue_degradation_details(
            stats,
            storage_capacity=storage_capacity,
            settings=settings,
        )
        return runtime_queue_status_from_degradation(
            stats=stats,
            inspection_anchors=inspection_anchors,
            recent_recoveries=recent_recoveries,
            degradation_details=degradation_details,
            storage_capacity=storage_capacity,
        )
    except Exception as exc:
        return unavailable_runtime_queue_status(reason=type(exc).__name__)


def runtime_queue_status_from_degradation(
    *,
    stats: ComputeQueueStats | LineageQueueStats,
    inspection_anchors: ComputeQueueInspectionAnchors | LineageQueueInspectionAnchors | None,
    recent_recoveries: tuple[ComputeRecoveryEvent | LineageRecoveryEvent, ...],
    degradation_details: tuple[RuntimeDegradationDetail, ...],
    storage_capacity: LineageStorageCapacitySnapshot | None = None,
) -> RuntimeQueueStatus:
    degradation_reasons = tuple(detail.reason for detail in degradation_details)
    return RuntimeQueueStatus(
        status="degraded" if degradation_reasons else "available",
        reason=degradation_reasons[0] if degradation_reasons else None,
        degradation_reasons=degradation_reasons,
        degradation_details=degradation_details,
        stats=stats,
        inspection_anchors=inspection_anchors,
        recent_recoveries=recent_recoveries,
        storage_capacity=storage_capacity,
    )


def unavailable_runtime_queue_status(*, reason: str) -> RuntimeQueueStatus:
    return RuntimeQueueStatus(
        status="unavailable",
        reason=reason,
        degradation_reasons=(),
        degradation_details=(),
        stats=None,
        inspection_anchors=None,
        recent_recoveries=(),
    )


def safe_compute_queue_inspection_anchors() -> ComputeQueueInspectionAnchors | None:
    try:
        return compute_job_store.get_queue_inspection_anchors()
    except Exception:
        return None


def safe_lineage_queue_inspection_anchors() -> LineageQueueInspectionAnchors | None:
    try:
        return lineage_metadata_store.get_queue_inspection_anchors()
    except Exception:
        return None


def safe_compute_recent_recoveries(*, settings) -> tuple[ComputeRecoveryEvent, ...]:
    try:
        limit = recent_recovery_limit(settings=settings)
        if limit == 0:
            return ()
        page = compute_job_store.list_recent_recoveries(limit=limit)
        return tuple(getattr(page, "items", page))
    except Exception:
        return ()


def safe_lineage_recent_recoveries(*, settings) -> tuple[LineageRecoveryEvent, ...]:
    try:
        limit = recent_recovery_limit(settings=settings)
        if limit == 0:
            return ()
        page = lineage_metadata_store.list_recent_recoveries(limit=limit)
        return tuple(getattr(page, "items", page))
    except Exception:
        return ()


def recent_recovery_limit(*, settings) -> int:
    return max(0, int(getattr(settings, "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT", 5)))
