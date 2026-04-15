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
        "Returns the bounded lotus-performance operator control-plane snapshot for durable runtime health. "
        "Use this endpoint to inspect aggregate readiness, draining state, durable metadata availability, "
        "compute and lineage queue pressure, lineage storage capacity, recovery-drill assurance, "
        "runtime-retention assurance, degradation reasons, policy thresholds, and drilldown anchors before "
        "opening execution, lineage, runtime-work-item, or runtime-recovery detail views."
    ),
)
async def get_runtime_status(request: Request) -> RuntimeStatusResponse:
    snapshot = build_runtime_status_snapshot(is_draining=bool(getattr(request.app.state, "is_draining", False)))
    return build_runtime_status_response(snapshot)
