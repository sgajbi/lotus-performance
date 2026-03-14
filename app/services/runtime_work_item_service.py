from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.compute_job_store import ComputeQueueInspectionItem, compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus, check_durable_metadata_store_ready
from app.services.lineage_metadata_store import LineageQueueInspectionItem, lineage_metadata_store


@dataclass(frozen=True)
class RuntimeWorkItemQueueState:
    status: str
    reason: str | None


@dataclass(frozen=True)
class RuntimeWorkItemSnapshot:
    generated_at: datetime
    status_filter: str
    limit: int
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeWorkItemQueueState
    lineage_queue: RuntimeWorkItemQueueState
    compute_items: list[ComputeQueueInspectionItem]
    lineage_items: list[LineageQueueInspectionItem]


def build_runtime_work_item_snapshot(*, status_filter: str, limit: int) -> RuntimeWorkItemSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()

    if not durability_status.is_ready:
        return RuntimeWorkItemSnapshot(
            generated_at=generated_at,
            status_filter=status_filter,
            limit=limit,
            durable_metadata_store=durability_status,
            compute_queue=RuntimeWorkItemQueueState(
                status="unavailable",
                reason=durability_status.reason or "durable_metadata_store_unreachable",
            ),
            lineage_queue=RuntimeWorkItemQueueState(
                status="unavailable",
                reason=durability_status.reason or "durable_metadata_store_unreachable",
            ),
            compute_items=[],
            lineage_items=[],
        )

    compute_queue_state, compute_items = _safe_compute_items(status_filter=status_filter, limit=limit, generated_at=generated_at)
    lineage_queue_state, lineage_items = _safe_lineage_items(status_filter=status_filter, limit=limit, generated_at=generated_at)

    return RuntimeWorkItemSnapshot(
        generated_at=generated_at,
        status_filter=status_filter,
        limit=limit,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue_state,
        lineage_queue=lineage_queue_state,
        compute_items=compute_items,
        lineage_items=lineage_items,
    )


def _safe_compute_items(
    *,
    status_filter: str,
    limit: int,
    generated_at: datetime,
) -> tuple[RuntimeWorkItemQueueState, list[ComputeQueueInspectionItem]]:
    try:
        return (
            RuntimeWorkItemQueueState(status="available", reason=None),
            compute_job_store.list_inspection_items(status_filter=status_filter, limit=limit, now=generated_at),
        )
    except Exception as exc:
        return RuntimeWorkItemQueueState(status="unavailable", reason=type(exc).__name__), []


def _safe_lineage_items(
    *,
    status_filter: str,
    limit: int,
    generated_at: datetime,
) -> tuple[RuntimeWorkItemQueueState, list[LineageQueueInspectionItem]]:
    try:
        return (
            RuntimeWorkItemQueueState(status="available", reason=None),
            lineage_metadata_store.list_inspection_items(status_filter=status_filter, limit=limit, now=generated_at),
        )
    except Exception as exc:
        return RuntimeWorkItemQueueState(status="unavailable", reason=type(exc).__name__), []
