from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from app.services.compute_job_store import ComputeQueueInspectionItem, compute_job_store
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    check_durable_metadata_schema_ready,
)
from app.services.lineage_metadata_store import LineageQueueInspectionItem, lineage_metadata_store
from app.services.runtime_unavailability import durable_metadata_unavailable_reason

_RuntimeWorkItemT = TypeVar("_RuntimeWorkItemT")


class _RuntimeWorkItemPage(Protocol[_RuntimeWorkItemT]):
    total_count: int
    next_offset: int | None
    items: list[_RuntimeWorkItemT]


@dataclass(frozen=True)
class _RuntimeWorkItemListRequest:
    status_filter: str
    limit: int
    offset: int
    min_age_seconds: float
    calculation_id_contains: str | None
    generated_at: datetime


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
    durability_status = check_durable_metadata_schema_ready()

    if not durability_status.is_ready:
        return _unavailable_runtime_work_item_snapshot(
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
        )

    return _available_runtime_work_item_snapshot(
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
    )


def _available_runtime_work_item_snapshot(
    *,
    generated_at: datetime,
    queue_filter: str,
    status_filter: str,
    limit: int,
    offset: int,
    min_age_seconds: float,
    compute_analytics_type: str | None,
    lineage_calculation_type: str | None,
    calculation_id_contains: str | None,
    durable_metadata_store: DurabilityHealthStatus,
) -> RuntimeWorkItemSnapshot:
    include_compute = queue_filter in {"both", "compute"}
    include_lineage = queue_filter in {"both", "lineage"}
    list_request = _RuntimeWorkItemListRequest(
        status_filter=status_filter,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
        calculation_id_contains=calculation_id_contains,
        generated_at=generated_at,
    )

    compute_queue_state, compute_items = _safe_compute_items(
        include_queue=include_compute,
        list_request=list_request,
        compute_analytics_type=compute_analytics_type,
    )
    lineage_queue_state, lineage_items = _safe_lineage_items(
        include_queue=include_lineage,
        list_request=list_request,
        lineage_calculation_type=lineage_calculation_type,
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
        durable_metadata_store=durable_metadata_store,
        compute_queue=compute_queue_state,
        lineage_queue=lineage_queue_state,
        compute_items=compute_items,
        lineage_items=lineage_items,
    )


def _unavailable_runtime_work_item_snapshot(
    *,
    generated_at: datetime,
    queue_filter: str,
    status_filter: str,
    limit: int,
    offset: int,
    min_age_seconds: float,
    compute_analytics_type: str | None,
    lineage_calculation_type: str | None,
    calculation_id_contains: str | None,
    durable_metadata_store: DurabilityHealthStatus,
) -> RuntimeWorkItemSnapshot:
    unavailable_queue = _queue_state(
        status="unavailable",
        reason=durable_metadata_unavailable_reason(durable_metadata_store),
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
        durable_metadata_store=durable_metadata_store,
        compute_queue=unavailable_queue,
        lineage_queue=unavailable_queue,
        compute_items=[],
        lineage_items=[],
    )


def _safe_compute_items(
    *,
    include_queue: bool,
    list_request: _RuntimeWorkItemListRequest,
    compute_analytics_type: str | None,
) -> tuple[RuntimeWorkItemQueueState, list[ComputeQueueInspectionItem]]:
    return _safe_runtime_work_items(
        include_queue=include_queue,
        load_page=lambda: compute_job_store.list_inspection_items(
            **_runtime_work_item_page_kwargs(list_request),
            analytics_type=compute_analytics_type,
        ),
    )


def _safe_lineage_items(
    *,
    include_queue: bool,
    list_request: _RuntimeWorkItemListRequest,
    lineage_calculation_type: str | None,
) -> tuple[RuntimeWorkItemQueueState, list[LineageQueueInspectionItem]]:
    return _safe_runtime_work_items(
        include_queue=include_queue,
        load_page=lambda: lineage_metadata_store.list_inspection_items(
            **_runtime_work_item_page_kwargs(list_request),
            calculation_type=lineage_calculation_type,
        ),
    )


def _runtime_work_item_page_kwargs(list_request: _RuntimeWorkItemListRequest) -> dict[str, object]:
    return {
        "status_filter": list_request.status_filter,
        "limit": list_request.limit,
        "offset": list_request.offset,
        "min_age_seconds": list_request.min_age_seconds,
        "calculation_id_contains": list_request.calculation_id_contains,
        "now": list_request.generated_at,
    }


def _safe_runtime_work_items(
    *,
    include_queue: bool,
    load_page: Callable[[], _RuntimeWorkItemPage[_RuntimeWorkItemT]],
) -> tuple[RuntimeWorkItemQueueState, list[_RuntimeWorkItemT]]:
    if not include_queue:
        return _queue_state(status="excluded"), []
    try:
        page = load_page()
        return (
            _queue_state(
                status="available",
                total_count=page.total_count,
                returned_count=len(page.items),
                next_offset=page.next_offset,
            ),
            page.items,
        )
    except Exception as exc:
        return _queue_state(status="unavailable", reason=type(exc).__name__), []


def _queue_state(
    *,
    status: str,
    reason: str | None = None,
    total_count: int = 0,
    returned_count: int = 0,
    next_offset: int | None = None,
) -> RuntimeWorkItemQueueState:
    return RuntimeWorkItemQueueState(
        status=status,
        reason=reason,
        total_count=total_count,
        returned_count=returned_count,
        next_offset=next_offset,
    )
