from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.runtime_retention_history import (
    RuntimeRetentionHistoryResponse,
    build_runtime_retention_history_response,
)
from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-retention-cleanups",
    response_model=RuntimeRetentionHistoryResponse,
    summary="Get retained runtime-retention cleanup history",
    description=(
        "Returns the retained runtime-retention cleanup history manifest for lotus-performance, including the latest "
        "artifact, configured retention policy, and summarized retained cleanup entries. Optional query filters allow "
        "operators to narrow the history by operator, trigger mode, job identity, cleanup mode, status, and bounded result count."
    ),
)
async def get_runtime_retention_history(
    limit: Annotated[
        int | None, Query(ge=1, le=100, description="Maximum number of retained runtime-retention cleanup entries to return.")
    ] = None,
    offset: Annotated[
        int, Query(ge=0, description="Zero-based offset into the filtered retained runtime-retention cleanup history.")
    ] = 0,
    operator_id: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by operator or automation identity.")
    ] = None,
    trigger_mode: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by manual or scheduled trigger mode.")
    ] = None,
    job_id: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by scheduler or automation job identity.")
    ] = None,
    cleanup_mode: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by cleanup mode.")
    ] = None,
    status: Annotated[
        str | None, Query(description="Filter retained runtime-retention cleanup history by execution outcome status.")
    ] = None,
    generated_after: Annotated[
        str | None,
        Query(description="Filter retained runtime-retention cleanup history to entries generated at or after this ISO-8601 timestamp."),
    ] = None,
    generated_before: Annotated[
        str | None,
        Query(description="Filter retained runtime-retention cleanup history to entries generated at or before this ISO-8601 timestamp."),
    ] = None,
) -> RuntimeRetentionHistoryResponse:
    snapshot = build_runtime_retention_history_snapshot(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode=cleanup_mode,
        status_filter=status,
        generated_after=generated_after,
        generated_before=generated_before,
    )
    return build_runtime_retention_history_response(snapshot)
