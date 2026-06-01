from __future__ import annotations

import logging
from typing import Iterable, Protocol, TypeVar, cast

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
from app.services.runtime_unavailability import (
    LINEAGE_STORAGE_CAPACITY_UNREADABLE_REASON,
    durable_metadata_unavailable_reason,
    lineage_storage_unavailable_reason,
)

logger = logging.getLogger(__name__)

RecoveryEventT = TypeVar("RecoveryEventT", ComputeRecoveryEvent, LineageRecoveryEvent, covariant=True)
InspectionAnchorsT = TypeVar(
    "InspectionAnchorsT",
    ComputeQueueInspectionAnchors,
    LineageQueueInspectionAnchors,
    covariant=True,
)


class RecentRecoveryLister(Protocol[RecoveryEventT]):
    def __call__(self, *, limit: int) -> object: ...


class QueueInspectionAnchorReader(Protocol[InspectionAnchorsT]):
    def __call__(self) -> InspectionAnchorsT: ...


def build_compute_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return unavailable_runtime_queue_status(reason=durable_metadata_unavailable_reason(durability_status))
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
        return unavailable_runtime_queue_status(reason=durable_metadata_unavailable_reason(durability_status))
    lineage_storage_status = check_lineage_storage_ready()
    if not lineage_storage_status.is_ready:
        return unavailable_runtime_queue_status(reason=lineage_storage_unavailable_reason(lineage_storage_status))
    try:
        storage_capacity = get_lineage_storage_capacity()
    except Exception:
        return unavailable_runtime_queue_status(reason=LINEAGE_STORAGE_CAPACITY_UNREADABLE_REASON)
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
    return safe_queue_inspection_anchors(
        read_anchors=compute_job_store.get_queue_inspection_anchors,
        source_label="compute",
    )


def safe_lineage_queue_inspection_anchors() -> LineageQueueInspectionAnchors | None:
    return safe_queue_inspection_anchors(
        read_anchors=lineage_metadata_store.get_queue_inspection_anchors,
        source_label="lineage",
    )


def safe_queue_inspection_anchors(
    *,
    read_anchors: QueueInspectionAnchorReader[InspectionAnchorsT],
    source_label: str,
) -> InspectionAnchorsT | None:
    try:
        return read_anchors()
    except Exception:
        logger.warning(
            "Runtime status %s queue inspection anchors unavailable.",
            source_label,
            exc_info=True,
        )
        return None


def safe_compute_recent_recoveries(*, settings) -> tuple[ComputeRecoveryEvent, ...]:
    return safe_recent_recoveries(
        settings=settings,
        list_recent_recoveries=compute_job_store.list_recent_recoveries,
        source_label="compute",
    )


def safe_lineage_recent_recoveries(*, settings) -> tuple[LineageRecoveryEvent, ...]:
    return safe_recent_recoveries(
        settings=settings,
        list_recent_recoveries=lineage_metadata_store.list_recent_recoveries,
        source_label="lineage",
    )


def safe_recent_recoveries(
    *,
    settings,
    list_recent_recoveries: RecentRecoveryLister[RecoveryEventT],
    source_label: str,
) -> tuple[RecoveryEventT, ...]:
    try:
        limit = recent_recovery_limit(settings=settings)
        if limit == 0:
            return ()
        page = list_recent_recoveries(limit=limit)
        return tuple(cast(Iterable[RecoveryEventT], getattr(page, "items", page)))
    except Exception:
        logger.warning(
            "Runtime status %s recent recovery evidence unavailable.",
            source_label,
            exc_info=True,
        )
        return ()


def recent_recovery_limit(*, settings) -> int:
    return max(0, int(getattr(settings, "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT", 5)))
