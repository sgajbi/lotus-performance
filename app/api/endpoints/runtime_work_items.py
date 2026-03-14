from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.models.runtime_work_items import RuntimeWorkItemsResponse, build_runtime_work_items_response
from app.services.runtime_work_item_service import build_runtime_work_item_snapshot

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-work-items",
    response_model=RuntimeWorkItemsResponse,
    summary="List filtered runtime work items",
    description=(
        "Returns concrete compute and lineage work items for operator drill-down, including exact calculation "
        "handles, lifecycle status, age, attempts, and durable failure context."
    ),
)
async def get_runtime_work_items(
    queue: Literal["both", "compute", "lineage"] = Query(
        default="both",
        description="Queue scope for operator work-item inspection.",
    ),
    status: Literal["active", "failed", "all", "reclaimable"] = Query(
        default="active",
        description=(
            "Work-item lifecycle filter applied to both compute and lineage queues. "
            "`reclaimable` returns work whose durable worker lease already expired and is eligible for recovery."
        ),
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of work items to return per queue.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Zero-based page offset applied to each selected queue before limiting.",
    ),
    min_age_seconds: float = Query(
        default=0.0,
        ge=0.0,
        description="Optional minimum work-item age filter, in seconds, for stale-item triage.",
    ),
    compute_analytics_type: str | None = Query(
        default=None,
        description="Optional compute analytics-type filter, such as ReturnsSeries or Attribution.",
    ),
    lineage_calculation_type: str | None = Query(
        default=None,
        description="Optional lineage calculation-type filter, such as TWR or Attribution.",
    ),
    calculation_id_contains: str | None = Query(
        default=None,
        description="Optional substring filter applied to calculation identifiers in the selected queues.",
    ),
) -> RuntimeWorkItemsResponse:
    snapshot = build_runtime_work_item_snapshot(
        queue_filter=queue,
        status_filter=status,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
        calculation_id_contains=calculation_id_contains,
    )
    return build_runtime_work_items_response(snapshot)
