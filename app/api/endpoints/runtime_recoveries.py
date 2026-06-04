from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.models.runtime_recoveries import RuntimeRecoveriesResponse
from app.services.runtime_recoveries_service import (
    RuntimeRecoveriesValidationError,
    build_runtime_recoveries_response_for_query,
)

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
    """Return filtered durable recovery events for runtime queue remediation review."""
    try:
        return build_runtime_recoveries_response_for_query(
            queue=queue,
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
    except RuntimeRecoveriesValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
