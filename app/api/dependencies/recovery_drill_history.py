from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Query

from app.api.time_query_validation import validate_utc_query_timestamp_window
from app.models.recovery_drill_history import RecoveryDrillHistoryQueryParams
from app.services.operator_action_history_pagination import OPERATOR_ACTION_HISTORY_DEFAULT_LIMIT

_RecoveryDrillLimitQuery: TypeAlias = Annotated[
    int | None,
    Query(
        ge=1,
        le=100,
        description="Maximum number of retained recovery-drill entries to return. Defaults to 10 when omitted.",
    ),
]
_RecoveryDrillOffsetQuery: TypeAlias = Annotated[
    int,
    Query(ge=0, description="Zero-based offset into the filtered retained recovery-drill history."),
]
_RecoveryDrillOperatorQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained recovery-drill history by operator or automation identity.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RecoveryDrillBackupQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained recovery-drill history by backup or restore-set identifier.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RecoveryDrillStatusQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained recovery-drill history by drill outcome status.",
        min_length=1,
        pattern=r".*\S.*",
    ),
]
_RecoveryDrillGeneratedAfterQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained recovery-drill history to entries generated at or after this ISO-8601 timestamp."
    ),
]
_RecoveryDrillGeneratedBeforeQuery: TypeAlias = Annotated[
    str | None,
    Query(
        description="Filter retained recovery-drill history to entries generated at or before this ISO-8601 timestamp."
    ),
]


def build_recovery_drill_history_query(
    limit: _RecoveryDrillLimitQuery = OPERATOR_ACTION_HISTORY_DEFAULT_LIMIT,
    offset: _RecoveryDrillOffsetQuery = 0,
    operator_id: _RecoveryDrillOperatorQuery = None,
    backup_identifier: _RecoveryDrillBackupQuery = None,
    status: _RecoveryDrillStatusQuery = None,
    generated_after: _RecoveryDrillGeneratedAfterQuery = None,
    generated_before: _RecoveryDrillGeneratedBeforeQuery = None,
) -> RecoveryDrillHistoryQueryParams:
    validated_after, validated_before = validate_utc_query_timestamp_window(
        generated_after=generated_after,
        generated_before=generated_before,
    )
    return RecoveryDrillHistoryQueryParams(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status=status,
        generated_after=validated_after,
        generated_before=validated_before,
    )
