from __future__ import annotations

from fastapi import APIRouter

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
        "artifact, configured retention limit, and summarized retained drill entries."
    ),
)
async def get_recovery_drill_history() -> RecoveryDrillHistoryResponse:
    snapshot = build_recovery_drill_history_snapshot()
    return build_recovery_drill_history_response(snapshot)
