from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import Query

from app.models.runtime_recoveries import RuntimeRecoveriesQueryParams


def build_runtime_recoveries_query(
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
) -> RuntimeRecoveriesQueryParams:
    return RuntimeRecoveriesQueryParams(
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
