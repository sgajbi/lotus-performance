from __future__ import annotations

from fastapi import APIRouter, Request

from app.models.runtime_status import RuntimeStatusResponse, build_runtime_status_response
from app.services.runtime_status_service import build_runtime_status_snapshot

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-status",
    response_model=RuntimeStatusResponse,
    summary="Get lotus-performance runtime status",
    description=(
        "Returns an operational snapshot of lotus-performance durable runtime state, including draining status, "
        "durable metadata store availability, and current compute and lineage queue backlog details."
    ),
)
async def get_runtime_status(request: Request) -> RuntimeStatusResponse:
    snapshot = build_runtime_status_snapshot(is_draining=bool(getattr(request.app.state, "is_draining", False)))
    return build_runtime_status_response(snapshot)
