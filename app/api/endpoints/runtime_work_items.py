from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies.runtime_work_items import build_runtime_work_items_query
from app.models.runtime_work_items import (
    RuntimeWorkItemsQueryParams,
    RuntimeWorkItemsResponse,
    build_runtime_work_items_response,
)
from app.services.runtime_work_item_service import build_runtime_work_item_snapshot

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-work-items",
    response_model=RuntimeWorkItemsResponse,
    summary="List filtered runtime work items",
    description=(
        "Returns the concrete compute and lineage work items behind lotus-performance runtime queue pressure. "
        "Use this operator drill-down endpoint after the runtime-status snapshot reports active, failed, or "
        "reclaimable backlog. It supports queue scoping, lifecycle filtering, bounded paging, stale-item "
        "filtering, analytics-family filtering, calculation-handle search, queue-specific partial-failure "
        "status, and direct execution, lineage, and async-result navigation links."
    ),
)
async def get_runtime_work_items(
    query: Annotated[RuntimeWorkItemsQueryParams, Depends(build_runtime_work_items_query)],
) -> RuntimeWorkItemsResponse:
    """Return filtered compute and lineage queue work items for operator drill-down."""
    snapshot = build_runtime_work_item_snapshot(
        queue_filter=query.queue,
        status_filter=query.status,
        limit=query.limit,
        offset=query.offset,
        min_age_seconds=query.min_age_seconds,
        compute_analytics_type=query.compute_analytics_type,
        lineage_calculation_type=query.lineage_calculation_type,
        calculation_id_contains=query.calculation_id_contains,
    )
    return build_runtime_work_items_response(snapshot)
