from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query

from app.models.runtime_recoveries import RuntimeRecoveriesResponse, build_runtime_recoveries_response
from app.services.runtime_recovery_service import build_runtime_recovery_snapshot

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-recoveries",
    response_model=RuntimeRecoveriesResponse,
    summary="List recent runtime recovery events",
    description=(
        "Returns recent compute and lineage recovery events for operator drill-down, including queue-specific "
        "availability, matched counts, recovery kind, and calculation handles."
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
) -> RuntimeRecoveriesResponse:
    snapshot = build_runtime_recovery_snapshot(
        queue_filter=queue,
        limit=limit,
        offset=offset,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        calculation_id_contains=calculation_id_contains,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
    )
    return build_runtime_recoveries_response(snapshot)
