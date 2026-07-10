from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from fastapi import Query

from app.models.runtime_work_items import RuntimeWorkItemsQueryParams
from app.services.calculation_id_filtering import (
    CALCULATION_ID_PREFIX_DESCRIPTION,
    CALCULATION_ID_PREFIX_MAX_LENGTH,
    CALCULATION_ID_PREFIX_MIN_LENGTH,
    CALCULATION_ID_PREFIX_PATTERN,
    normalize_calculation_id_prefix,
)

_RuntimeWorkItemsQueueQuery: TypeAlias = Annotated[
    Literal["both", "compute", "lineage"],
    Query(description="Queue scope for operator work-item inspection."),
]
_RuntimeWorkItemsStatusQuery: TypeAlias = Annotated[
    Literal["active", "failed", "all", "reclaimable"],
    Query(
        description=(
            "Work-item lifecycle filter applied to both compute and lineage queues. "
            "`reclaimable` returns work whose durable worker lease already expired and is eligible for recovery."
        ),
    ),
]
_RuntimeWorkItemsLimitQuery: TypeAlias = Annotated[
    int,
    Query(ge=1, le=100, description="Maximum number of work items to return per queue."),
]
_RuntimeWorkItemsOffsetQuery: TypeAlias = Annotated[
    int,
    Query(ge=0, description="Zero-based page offset applied to each selected queue before limiting."),
]
_RuntimeWorkItemsMinAgeQuery: TypeAlias = Annotated[
    float,
    Query(ge=0.0, description="Optional minimum work-item age filter, in seconds, for stale-item triage."),
]
_RuntimeWorkItemsComputeAnalyticsTypeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=1,
        pattern=r".*\S.*",
        description="Optional compute analytics-type filter, such as ReturnsSeries or Attribution.",
    ),
]
_RuntimeWorkItemsLineageCalculationTypeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=1,
        pattern=r".*\S.*",
        description="Optional lineage calculation-type filter, such as TWR or Attribution.",
    ),
]
_RuntimeWorkItemsCalculationIdContainsQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=CALCULATION_ID_PREFIX_MIN_LENGTH,
        max_length=CALCULATION_ID_PREFIX_MAX_LENGTH,
        pattern=CALCULATION_ID_PREFIX_PATTERN,
        description=CALCULATION_ID_PREFIX_DESCRIPTION,
    ),
]


def build_runtime_work_items_query(
    queue: _RuntimeWorkItemsQueueQuery = "both",
    status: _RuntimeWorkItemsStatusQuery = "active",
    limit: _RuntimeWorkItemsLimitQuery = 10,
    offset: _RuntimeWorkItemsOffsetQuery = 0,
    min_age_seconds: _RuntimeWorkItemsMinAgeQuery = 0.0,
    compute_analytics_type: _RuntimeWorkItemsComputeAnalyticsTypeQuery = None,
    lineage_calculation_type: _RuntimeWorkItemsLineageCalculationTypeQuery = None,
    calculation_id_contains: _RuntimeWorkItemsCalculationIdContainsQuery = None,
) -> RuntimeWorkItemsQueryParams:
    return RuntimeWorkItemsQueryParams(
        queue=queue,
        status=status,
        limit=limit,
        offset=offset,
        min_age_seconds=min_age_seconds,
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
        calculation_id_contains=normalize_calculation_id_prefix(calculation_id_contains),
    )
