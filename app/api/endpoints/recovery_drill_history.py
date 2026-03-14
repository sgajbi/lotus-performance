from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.recovery_drill_history import (
    RecoveryDrillHistoryResponse,
    build_recovery_drill_history_response,
)
from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot

router = APIRouter(tags=["Integration"])


@router.get(
    "/recovery-drills",
    response_model=RecoveryDrillHistoryResponse,
    summary="Get retained durable recovery-drill history",
    description=(
        "Returns the retained durable recovery-drill history manifest for lotus-performance, including the latest "
        "artifact, configured retention policy, and summarized retained drill entries. Optional query filters allow "
        "operators to narrow the history by operator, backup identifier, status, and bounded result count."
    ),
)
async def get_recovery_drill_history(
    limit: Annotated[int | None, Query(ge=1, le=100, description="Maximum number of retained recovery-drill entries to return.")] = None,
    operator_id: Annotated[str | None, Query(description="Filter retained recovery-drill history by operator or automation identity.")] = None,
    backup_identifier: Annotated[str | None, Query(description="Filter retained recovery-drill history by backup or restore-set identifier.")] = None,
    status: Annotated[str | None, Query(description="Filter retained recovery-drill history by drill outcome status.")] = None,
) -> RecoveryDrillHistoryResponse:
    snapshot = build_recovery_drill_history_snapshot(
        limit=limit,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status,
    )
    return build_recovery_drill_history_response(snapshot)
