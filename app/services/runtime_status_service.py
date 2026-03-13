from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.compute_job_store import ComputeQueueStats, compute_job_store
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    check_durable_metadata_store_ready,
)
from app.services.lineage_metadata_store import LineageQueueStats, lineage_metadata_store


@dataclass(frozen=True)
class RuntimeQueueStatus:
    status: str
    reason: str | None
    stats: ComputeQueueStats | LineageQueueStats | None


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    generated_at: datetime
    runtime_status: str
    draining: bool
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeQueueStatus
    lineage_queue: RuntimeQueueStatus


def build_runtime_status_snapshot(*, is_draining: bool) -> RuntimeStatusSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()

    runtime_status = "draining" if is_draining else durability_status.status
    compute_queue = _build_compute_queue_status(durability_status)
    lineage_queue = _build_lineage_queue_status(durability_status)

    if runtime_status == "ready" and (compute_queue.status != "available" or lineage_queue.status != "available"):
        runtime_status = "degraded"

    return RuntimeStatusSnapshot(
        generated_at=generated_at,
        runtime_status=runtime_status,
        draining=is_draining,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
    )


def _build_compute_queue_status(durability_status: DurabilityHealthStatus) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            stats=None,
        )
    try:
        return RuntimeQueueStatus(status="available", reason=None, stats=compute_job_store.get_queue_stats())
    except Exception as exc:
        return RuntimeQueueStatus(status="unavailable", reason=type(exc).__name__, stats=None)


def _build_lineage_queue_status(durability_status: DurabilityHealthStatus) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            stats=None,
        )
    try:
        return RuntimeQueueStatus(
            status="available",
            reason=None,
            stats=lineage_metadata_store.get_pending_payload_stats(),
        )
    except Exception as exc:
        return RuntimeQueueStatus(status="unavailable", reason=type(exc).__name__, stats=None)
