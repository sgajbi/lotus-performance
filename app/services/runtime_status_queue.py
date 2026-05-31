from __future__ import annotations

from app.services.compute_job_store import (
    ComputeQueueInspectionAnchors,
    ComputeQueueStats,
    ComputeRecoveryEvent,
)
from app.services.durability_health_service import LineageStorageCapacitySnapshot
from app.services.lineage_metadata_store import (
    LineageQueueInspectionAnchors,
    LineageQueueStats,
    LineageRecoveryEvent,
)
from app.services.runtime_status_domain import RuntimeDegradationDetail, RuntimeQueueStatus


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
