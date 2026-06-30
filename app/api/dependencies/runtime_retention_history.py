from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Query

from app.api.time_query_validation import validate_utc_query_timestamp_window
from app.models.runtime_retention_history import RuntimeRetentionHistoryQueryParams
from app.services.operator_action_history_pagination import OPERATOR_ACTION_HISTORY_DEFAULT_LIMIT

_RuntimeRetentionLimitQuery: TypeAlias = Annotated[
    int | None,
    Query(
        ge=1,
        le=100,
        description=(
            "Maximum number of retained runtime-retention cleanup entries to return. "
            "Defaults to 10 when omitted."
        ),
    ),
]
_RuntimeRetentionOffsetQuery: TypeAlias = Annotated[
    int,
    Query(ge=0, description="Zero-based offset into the filtered retained history."),
]
_RuntimeRetentionOperatorQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history by operator or automation identity.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RuntimeRetentionTriggerQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history by manual or scheduled trigger mode.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RuntimeRetentionJobQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history by scheduler or automation job identity.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RuntimeRetentionCleanupModeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history by cleanup mode.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RuntimeRetentionStatusQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history by execution outcome status.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RuntimeRetentionGeneratedAfterQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history to entries generated at or after this UTC timestamp."
    ),
]
_RuntimeRetentionGeneratedBeforeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained runtime-retention cleanup history to entries generated at or before this UTC timestamp."
    ),
]


def build_runtime_retention_history_query(
    limit: _RuntimeRetentionLimitQuery = OPERATOR_ACTION_HISTORY_DEFAULT_LIMIT,
    offset: _RuntimeRetentionOffsetQuery = 0,
    operator_id: _RuntimeRetentionOperatorQuery = None,
    trigger_mode: _RuntimeRetentionTriggerQuery = None,
    job_id: _RuntimeRetentionJobQuery = None,
    cleanup_mode: _RuntimeRetentionCleanupModeQuery = None,
    status: _RuntimeRetentionStatusQuery = None,
    generated_after: _RuntimeRetentionGeneratedAfterQuery = None,
    generated_before: _RuntimeRetentionGeneratedBeforeQuery = None,
) -> RuntimeRetentionHistoryQueryParams:
    validated_after, validated_before = validate_utc_query_timestamp_window(
        generated_after=generated_after,
        generated_before=generated_before,
    )
    return RuntimeRetentionHistoryQueryParams(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode=cleanup_mode,
        status=status,
        generated_after=validated_after,
        generated_before=validated_before,
    )
