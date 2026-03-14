from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.compute_job_store import ComputeQueueInspectionItem, compute_job_store
from app.services.durability_health_service import DurabilityHealthStatus, check_durable_metadata_store_ready
from app.services.lineage_metadata_store import LineageQueueInspectionItem, lineage_metadata_store


@dataclass(frozen=True)
class RuntimeWorkItemSnapshot:
    generated_at: datetime
    status_filter: str
    limit: int
    durable_metadata_store: DurabilityHealthStatus
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
            compute_items=[],
            lineage_items=[],
        )

    return RuntimeWorkItemSnapshot(
        generated_at=generated_at,
        status_filter=status_filter,
        limit=limit,
        durable_metadata_store=durability_status,
        compute_items=compute_job_store.list_inspection_items(status_filter=status_filter, limit=limit, now=generated_at),
        lineage_items=lineage_metadata_store.list_inspection_items(
            status_filter=status_filter,
            limit=limit,
            now=generated_at,
        ),
    )
