from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.recovery_drill_history import build_recovery_drill_history_query
from app.api.operator_context import resolve_operator_request_context
from app.models.recovery_drill_history import (
    RecoveryDrillHistoryQueryParams,
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
    query: Annotated[RecoveryDrillHistoryQueryParams, Depends(build_recovery_drill_history_query)],
) -> RecoveryDrillHistoryResponse:
    """Return retained recovery-drill history for operator assurance review."""
    snapshot = build_recovery_drill_history_snapshot(
        limit=query.limit,
        offset=query.offset,
        operator_id=query.operator_id,
        backup_identifier=query.backup_identifier,
        status_filter=query.status,
        generated_after=query.generated_after,
        generated_before=query.generated_before,
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
