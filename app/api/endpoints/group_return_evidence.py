from __future__ import annotations

from fastapi import APIRouter

from app.models.group_return_evidence import GroupReturnEvidenceRequest, GroupReturnEvidenceResponse
from app.services.group_return_evidence_workflow_service import calculate_group_return_evidence_response

router = APIRouter(tags=["Integration"])


@router.post(
    "/attribution/group-return-evidence/v1",
    response_model=GroupReturnEvidenceResponse,
    summary="Publish source-owned group-return evidence for empirical active-risk attribution",
    description=(
        "Publishes one admitted-tenant portfolio/benchmark economic source cut. It refuses incomplete, "
        "unreconciled, foreign, duplicate, calendar-misaligned, or currency-mismatched source facts rather than "
        "inferring missing returns or FX. lotus-performance publishes evidence only and does not calculate risk "
        "attribution; lotus-risk owns active-risk "
        "decomposition and qualification."
    ),
)
async def get_group_return_evidence(
    request: GroupReturnEvidenceRequest,
) -> GroupReturnEvidenceResponse:
    """Return reconciled group-return evidence from admitted stateful source authority."""
    return await calculate_group_return_evidence_response(request)
