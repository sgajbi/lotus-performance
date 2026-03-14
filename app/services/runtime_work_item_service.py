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
    total_count: int
    returned_count: int
    next_offset: int | None


@dataclass(frozen=True)
class RuntimeWorkItemSnapshot:
    generated_at: datetime
    queue_filter: str
    status_filter: str
    limit: int
    offset: int
    min_age_seconds: float
    compute_analytics_type: str | None
    lineage_calculation_type: str | None
    calculation_id_contains: str | None
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeWorkItemQueueState
    lineage_queue: RuntimeWorkItemQueueState
    compute_items: list[ComputeQueueInspectionItem]
    lineage_items: list[LineageQueueInspectionItem]


def build_runtime_work_item_snapshot(
    *,
    queue_filter: str,
    status_filter: str,
    limit: int,
    offset: int,
    min_age_seconds: float,
    compute_analytics_type: str | None,
    lineage_calculation_type: str | None,
    calculation_id_contains: str | None,
) -> RuntimeWorkItemSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()

    if not durability_status.is_ready:
        return RuntimeWorkItemSnapshot(
            generated_at=generated_at,
            queue_filter=queue_filter,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
            min_age_seconds=min_age_seconds,
            compute_analytics_type=compute_analytics_type,
            lineage_calculation_type=lineage_calculation_type,
            calculation_id_contains=calculation_id_contains,
            durable_metadata_store=durability_status,
            compute_queue=RuntimeWorkItemQueueState(
                status="unavailable",
                reason=durability_status.reason or "durable_metadata_store_unreachable",
                total_count=0,
                returned_count=0,
                next_offset=None,
            ),
            lineage_queue=RuntimeWorkItemQueueState(
                status="unavailable",
                reason=durability_status.reason or "durable_metadata_store_unreachable",
                total_count=0,
                returned_count=0,
                next_offset=None,
            ),
            compute_items=[],
            lineage_items=[],
        )

    include_compute = queue_filter in {"both", "compute"}
    include_lineage = queue_filter in {"both", "lineage"}

    compute_queue_state, compute_items = _safe_compute_items(
        include_queue=include_compute,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
        compute_analytics_type=compute_analytics_type,
        calculation_id_contains=calculation_id_contains,
        generated_at=generated_at,
    )
    lineage_queue_state, lineage_items = _safe_lineage_items(
        include_queue=include_lineage,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
        lineage_calculation_type=lineage_calculation_type,
        calculation_id_contains=calculation_id_contains,
        generated_at=generated_at,
    )

    return RuntimeWorkItemSnapshot(
        generated_at=generated_at,
        queue_filter=queue_filter,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
        calculation_id_contains=calculation_id_contains,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue_state,
        lineage_queue=lineage_queue_state,
        compute_items=compute_items,
        lineage_items=lineage_items,
    )


def _safe_compute_items(
    *,
    include_queue: bool,
    status_filter: str,
    limit: int,
    offset: int,
    min_age_seconds: float,
    compute_analytics_type: str | None,
    calculation_id_contains: str | None,
    generated_at: datetime,
) -> tuple[RuntimeWorkItemQueueState, list[ComputeQueueInspectionItem]]:
    if not include_queue:
        return RuntimeWorkItemQueueState(
            status="excluded", reason=None, total_count=0, returned_count=0, next_offset=None
        ), []
    try:
        page = compute_job_store.list_inspection_items(
            status_filter=status_filter,
            limit=limit,
            offset=offset,
            min_age_seconds=min_age_seconds,
            analytics_type=compute_analytics_type,
            calculation_id_contains=calculation_id_contains,
            now=generated_at,
        )
        return (
            RuntimeWorkItemQueueState(
                status="available",
                reason=None,
                total_count=page.total_count,
                returned_count=len(page.items),
                next_offset=page.next_offset,
            ),
            page.items,
        )
    except Exception as exc:
        return RuntimeWorkItemQueueState(
            status="unavailable",
            reason=type(exc).__name__,
            total_count=0,
            returned_count=0,
            next_offset=None,
        ), []


def _safe_lineage_items(
    *,
    include_queue: bool,
    status_filter: str,
    limit: int,
    offset: int,
    min_age_seconds: float,
    lineage_calculation_type: str | None,
    calculation_id_contains: str | None,
    generated_at: datetime,
) -> tuple[RuntimeWorkItemQueueState, list[LineageQueueInspectionItem]]:
    if not include_queue:
        return RuntimeWorkItemQueueState(
            status="excluded", reason=None, total_count=0, returned_count=0, next_offset=None
        ), []
    try:
        page = lineage_metadata_store.list_inspection_items(
            status_filter=status_filter,
            limit=limit,
            offset=offset,
            min_age_seconds=min_age_seconds,
            calculation_type=lineage_calculation_type,
            calculation_id_contains=calculation_id_contains,
            now=generated_at,
        )
        return (
            RuntimeWorkItemQueueState(
                status="available",
                reason=None,
                total_count=page.total_count,
                returned_count=len(page.items),
                next_offset=page.next_offset,
            ),
            page.items,
        )
    except Exception as exc:
        return RuntimeWorkItemQueueState(
            status="unavailable",
            reason=type(exc).__name__,
            total_count=0,
            returned_count=0,
            next_offset=None,
        ), []
