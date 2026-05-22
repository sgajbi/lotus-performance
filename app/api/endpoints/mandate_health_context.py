from __future__ import annotations

from fastapi import APIRouter

from app.models.mandate_health import (
    MandatePerformanceHealthContextRequest,
    MandatePerformanceHealthContextResponse,
)
from app.services.mandate_health_context_service import (
    evaluate_mandate_performance_health_context,
)

router = APIRouter(tags=["Performance"])


@router.post(
    "/mandate-health-context",
    response_model=MandatePerformanceHealthContextResponse,
    summary="Evaluate source-owned mandate performance health context",
    description=(
        "Evaluates a bounded mandate performance health context using lotus-performance "
        "source-owned active-return interpretation. The response preserves threshold posture, "
        "methodology ownership, request lineage, and reason codes for downstream consumers such "
        "as lotus-manage without creating mandate actions, rebalance waves, client "
        "communications, orders, or execution."
    ),
)
def evaluate_mandate_performance_health_context_endpoint(
    request: MandatePerformanceHealthContextRequest,
) -> MandatePerformanceHealthContextResponse:
    return evaluate_mandate_performance_health_context(request)
