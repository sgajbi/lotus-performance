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
    status: Literal["active", "failed", "all"] = Query(
        default="active",
        description="Work-item lifecycle filter applied to both compute and lineage queues.",
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
) -> RuntimeWorkItemsResponse:
    snapshot = build_runtime_work_item_snapshot(
        queue_filter=queue,
        status_filter=status,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
    )
    return build_runtime_work_items_response(snapshot)
