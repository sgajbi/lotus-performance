from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from fastapi import Query

from app.models.runtime_recoveries import RuntimeRecoveriesQueryParams
from app.services.calculation_id_filtering import (
    CALCULATION_ID_PREFIX_DESCRIPTION,
    CALCULATION_ID_PREFIX_MAX_LENGTH,
    CALCULATION_ID_PREFIX_MIN_LENGTH,
    CALCULATION_ID_PREFIX_PATTERN,
    normalize_calculation_id_prefix,
)

_RuntimeRecoveriesQueueQuery: TypeAlias = Annotated[
    Literal["both", "compute", "lineage"],
    Query(description="Queue scope for runtime recovery inspection."),
]
_RuntimeRecoveriesLimitQuery: TypeAlias = Annotated[
    int,
    Query(ge=1, le=100, description="Maximum number of recovery events to return per queue."),
]
_RuntimeRecoveriesOffsetQuery: TypeAlias = Annotated[
    int,
    Query(
        ge=0,
        description="Zero-based page offset applied to each selected queue before limiting results.",
    ),
]
_RuntimeRecoveriesRecoveredAfterQuery: TypeAlias = Annotated[
    datetime | None,
    Query(description="Optional inclusive lower UTC timestamp bound applied to recovery-event timestamps."),
]
_RuntimeRecoveriesRecoveredBeforeQuery: TypeAlias = Annotated[
    datetime | None,
    Query(description="Optional inclusive upper UTC timestamp bound applied to recovery-event timestamps."),
]
_RuntimeRecoveriesCursorRecoveredBeforeQuery: TypeAlias = Annotated[
    datetime | None,
    Query(
        description="Optional cursor recovery timestamp used for deterministic seek pagination of older matching events.",
    ),
]
_RuntimeRecoveriesCursorCalculationIdQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=1,
        pattern=r".*\S.*",
        description="Optional cursor calculation handle paired with the cursor recovery timestamp for seek pagination.",
    ),
]
_RuntimeRecoveriesComputeAnalyticsTypeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=1,
        pattern=r".*\S.*",
        description="Optional compute analytics-type filter, such as ReturnsSeries or Attribution.",
    ),
]
_RuntimeRecoveriesLineageCalculationTypeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=1,
        pattern=r".*\S.*",
        description="Optional lineage calculation-type filter, such as TWR or Attribution.",
    ),
]
_RuntimeRecoveriesCalculationIdContainsQuery: TypeAlias = Annotated[
    str | None,
    Query(
        min_length=CALCULATION_ID_PREFIX_MIN_LENGTH,
        max_length=CALCULATION_ID_PREFIX_MAX_LENGTH,
        pattern=CALCULATION_ID_PREFIX_PATTERN,
        description=CALCULATION_ID_PREFIX_DESCRIPTION,
    ),
]


def build_runtime_recoveries_query(
    queue: _RuntimeRecoveriesQueueQuery = "both",
    limit: _RuntimeRecoveriesLimitQuery = 10,
    offset: _RuntimeRecoveriesOffsetQuery = 0,
    recovered_after: _RuntimeRecoveriesRecoveredAfterQuery = None,
    recovered_before: _RuntimeRecoveriesRecoveredBeforeQuery = None,
    cursor_recovered_before: _RuntimeRecoveriesCursorRecoveredBeforeQuery = None,
    cursor_calculation_id_before: _RuntimeRecoveriesCursorCalculationIdQuery = None,
    compute_analytics_type: _RuntimeRecoveriesComputeAnalyticsTypeQuery = None,
    lineage_calculation_type: _RuntimeRecoveriesLineageCalculationTypeQuery = None,
    calculation_id_contains: _RuntimeRecoveriesCalculationIdContainsQuery = None,
) -> RuntimeRecoveriesQueryParams:
    return RuntimeRecoveriesQueryParams(
        queue=queue,
        limit=limit,
        offset=offset,
        recovered_after=recovered_after,
        recovered_before=recovered_before,
        cursor_recovered_before=cursor_recovered_before,
        cursor_calculation_id_before=cursor_calculation_id_before,
        calculation_id_contains=normalize_calculation_id_prefix(calculation_id_contains),
        compute_analytics_type=compute_analytics_type,
        lineage_calculation_type=lineage_calculation_type,
    )
