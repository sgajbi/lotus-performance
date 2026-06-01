from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.models.runtime_recoveries import RuntimeRecoveriesResponse, build_runtime_recoveries_response
from app.services.runtime_recovery_service import build_runtime_recovery_snapshot
from core.errors import HTTP_422_UNPROCESSABLE

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-recoveries",
    response_model=RuntimeRecoveriesResponse,
    summary="List recent runtime recovery events",
    description=(
        "Returns durable compute and lineage recovery events for lotus-performance operator drill-down. "
        "Use this endpoint after runtime-status reports recovery activity or after runtime-work-items shows "
        "reclaimable work. It supports queue scoping, bounded offset paging, deterministic seek pagination, "
        "recovery-time windows, analytics-family filtering, calculation-handle search, queue-specific "
        "partial-failure status, and direct execution, lineage, and async-result navigation links."
    ),
)
async def get_runtime_recoveries(
    queue: Literal["both", "compute", "lineage"] = Query(
        default="both",
        description="Queue scope for runtime recovery inspection.",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of recovery events to return per queue.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Zero-based page offset applied to each selected queue before limiting results.",
    ),
    recovered_after: datetime | None = Query(
        default=None,
        description="Optional inclusive lower UTC timestamp bound applied to recovery-event timestamps.",
    ),
    recovered_before: datetime | None = Query(
        default=None,
        description="Optional inclusive upper UTC timestamp bound applied to recovery-event timestamps.",
    ),
    cursor_recovered_before: datetime | None = Query(
        default=None,
        description="Optional cursor recovery timestamp used for deterministic seek pagination of older matching events.",
    ),
    cursor_calculation_id_before: str | None = Query(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional cursor calculation handle paired with the cursor recovery timestamp for seek pagination.",
    ),
    compute_analytics_type: str | None = Query(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional compute analytics-type filter, such as ReturnsSeries or Attribution.",
    ),
    lineage_calculation_type: str | None = Query(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional lineage calculation-type filter, such as TWR or Attribution.",
    ),
    calculation_id_contains: str | None = Query(
        default=None,
        min_length=1,
        pattern=r".*\S.*",
        description="Optional substring filter applied to calculation identifiers in the selected queues.",
    ),
) -> RuntimeRecoveriesResponse:
    if recovered_after is not None and recovered_before is not None and recovered_after > recovered_before:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": "invalid_recovery_time_window",
                "fields": ["recovered_after", "recovered_before"],
                "message": "recovered_after must be less than or equal to recovered_before.",
            },
        )
    if cursor_calculation_id_before is not None and cursor_recovered_before is None:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": "incomplete_recovery_cursor",
                "fields": ["cursor_recovered_before", "cursor_calculation_id_before"],
                "message": "cursor_calculation_id_before requires cursor_recovered_before.",
            },
        )
    snapshot = build_runtime_recovery_snapshot(
        queue_filter=queue,
        limit=limit,
        offset=offset,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before=cursor_calculation_id_before,
        calculation_id_contains=calculation_id_contains,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
    )
    return build_runtime_recoveries_response(snapshot)
