from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Path, status

from app.models.source_corrections import (
    RetainedCalculationResult,
    SourceCorrectionRequest,
    SourceCorrectionResponse,
)
from app.services.source_correction_service import (
    cancel_source_correction,
    get_retained_calculation_result,
    get_source_correction,
    submit_source_correction,
)

router = APIRouter(tags=["Integration"])


@router.post(
    "/source-corrections",
    response_model=SourceCorrectionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Admit a versioned source correction",
    description=(
        "Persists a tenant-scoped, idempotent correction notice and schedules bounded recalculation of "
        "overlapping retained stateful calculations. Core remains the source correction authority."
    ),
)
async def create_source_correction(request: SourceCorrectionRequest) -> SourceCorrectionResponse:
    return submit_source_correction(request)


@router.get(
    "/source-corrections/{correction_id}",
    response_model=SourceCorrectionResponse,
    summary="Retrieve source-correction impact and recalculation state",
)
async def read_source_correction(
    correction_id: str = Path(min_length=1, max_length=128),
) -> SourceCorrectionResponse:
    return get_source_correction(correction_id)


@router.delete(
    "/source-corrections/{correction_id}",
    response_model=SourceCorrectionResponse,
    summary="Cancel source-correction work before worker acquisition",
)
async def cancel_source_correction_work(
    correction_id: str = Path(min_length=1, max_length=128),
) -> SourceCorrectionResponse:
    return cancel_source_correction(correction_id)


@router.get(
    "/executions/{calculation_id}/retained-result",
    response_model=RetainedCalculationResult,
    summary="Retrieve an immutable retained calculation result",
    description=(
        "Returns the original retained response under its calculation identity. A later correction does not "
        "rewrite this payload; correction status identifies any superseding calculation."
    ),
)
async def read_retained_calculation_result(
    calculation_id: UUID = Path(description="Tenant-scoped calculation identity."),
) -> RetainedCalculationResult:
    return get_retained_calculation_result(calculation_id)
