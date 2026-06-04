from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies.runtime_recoveries import build_runtime_recoveries_query
from app.models.runtime_recoveries import RuntimeRecoveriesQueryParams, RuntimeRecoveriesResponse
from app.services.runtime_recoveries_service import (
    RuntimeRecoveriesValidationError,
    build_runtime_recoveries_response_for_query,
)

router = APIRouter(tags=["Integration"])


@router.get(
    "/runtime-recoveries",
    response_model=RuntimeRecoveriesResponse,
    summary="List recent runtime recovery events",
    description=(
        "Returns durable compute and lineage recovery events for lotus-performance operator drill-down. "
        "Use this endpoint after runtime-status reports recovery activity or after runtime-work-items shows "
        "reclaimable work. It supports queue scoping, bounded offset paging, deterministic seek pagination, "
        "recovery-time windows, analytics-family filtering, calculation-handle search, queue-specific "
        "partial-failure status, and direct execution, lineage, and async-result navigation links."
    ),
)
async def get_runtime_recoveries(
    query: Annotated[RuntimeRecoveriesQueryParams, Depends(build_runtime_recoveries_query)],
) -> RuntimeRecoveriesResponse:
    """Return filtered durable recovery events for runtime queue remediation review."""
    try:
        return build_runtime_recoveries_response_for_query(
            queue=query.queue,
            limit=query.limit,
            offset=query.offset,
            recovered_after=query.recovered_after,
            recovered_before=query.recovered_before,
            cursor_recovered_before=query.cursor_recovered_before,
            cursor_calculation_id_before=query.cursor_calculation_id_before,
            calculation_id_contains=query.calculation_id_contains,
            compute_analytics_type=query.compute_analytics_type,
            lineage_calculation_type=query.lineage_calculation_type,
        )
    except RuntimeRecoveriesValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
