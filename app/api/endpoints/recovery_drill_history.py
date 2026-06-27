from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.operator_context import resolve_operator_request_context
from app.api.time_query_validation import validate_utc_query_timestamp_window
from app.models.recovery_drill_history import (
    RecoveryDrillHistoryResponse,
    RecoveryDrillRunRequest,
    RecoveryDrillRunResponse,
    build_recovery_drill_history_response,
)
from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot
from app.services.recovery_drill_run_service import run_governed_recovery_drill

router = APIRouter(tags=["Integration"])


@router.get(
    "/recovery-drills",
    response_model=RecoveryDrillHistoryResponse,
    summary="Get retained durable recovery-drill history",
    description=(
        "Returns the retained durable recovery-drill history manifest for lotus-performance. Use this operator "
        "control-plane endpoint to inspect latest recovery assurance, retained evidence artifacts, retention "
        "policy, applied filters, deterministic paging, and time-windowed drill outcomes without shell access "
        "to the artifact directory."
    ),
)
async def get_recovery_drill_history(
    limit: Annotated[
        int | None, Query(ge=1, le=100, description="Maximum number of retained recovery-drill entries to return.")
    ] = None,
    offset: Annotated[
        int, Query(ge=0, description="Zero-based offset into the filtered retained recovery-drill history.")
    ] = 0,
    operator_id: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history by operator or automation identity.",
            min_length=1,
            pattern=r".*\S.*",
        ),
    ] = None,
    backup_identifier: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history by backup or restore-set identifier.",
            min_length=1,
            pattern=r".*\S.*",
        ),
    ] = None,
    status: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history by drill outcome status.",
            min_length=1,
            pattern=r".*\S.*",
        ),
    ] = None,
    generated_after: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history to entries generated at or after this ISO-8601 timestamp."
        ),
    ] = None,
    generated_before: Annotated[
        str | None,
        Query(
            description="Filter retained recovery-drill history to entries generated at or before this ISO-8601 timestamp."
        ),
    ] = None,
) -> RecoveryDrillHistoryResponse:
    """Return retained recovery-drill history for operator assurance review."""
    generated_after, generated_before = validate_utc_query_timestamp_window(
        generated_after=generated_after,
        generated_before=generated_before,
    )
    snapshot = build_recovery_drill_history_snapshot(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status,
        generated_after=generated_after,
        generated_before=generated_before,
    )
    return build_recovery_drill_history_response(snapshot)


@router.post(
    "/recovery-drills/run",
    response_model=RecoveryDrillRunResponse,
    summary="Run a governed durable recovery drill",
    description=(
        "Runs the governed service-owned durable recovery drill for a backup or restore-set identifier. The "
        "endpoint requires an operator identity, applies idempotent replay, cooldown, and stale-lease guards, "
        "retains the resulting evidence in recovery-drill history, and returns the immediate compute, lineage, "
        "schema, and artifact proof summary."
    ),
)
async def run_recovery_drill(
    request: Request,
    recovery_request: RecoveryDrillRunRequest,
) -> RecoveryDrillRunResponse:
    """Run or replay a governed recovery drill under operator lease controls."""
    operator_context = resolve_operator_request_context(request)
    result = run_governed_recovery_drill(
        operator_context=operator_context,
        backup_identifier=recovery_request.backup_identifier,
    )
    if result.idempotent_replay:
        return JSONResponse(
            status_code=200,
            content=result.response.model_dump(mode="json"),
            headers={"X-Idempotent-Replay": "true"},
        )
    return result.response
