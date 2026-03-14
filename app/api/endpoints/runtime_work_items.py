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
) -> RuntimeWorkItemsResponse:
    snapshot = build_runtime_work_item_snapshot(status_filter=status, limit=limit)
    return build_runtime_work_items_response(snapshot)
