from __future__ import annotations

from fastapi import APIRouter

from app.models.benchmark_exposure_context import BenchmarkExposureContextRequest, BenchmarkExposureContextResponse
from app.services.benchmark_exposure_context_workflow_service import calculate_benchmark_exposure_context_response

router = APIRouter(tags=["Integration"])


@router.post(
    "/benchmarks/exposure-context",
    response_model=BenchmarkExposureContextResponse,
    summary="Get benchmark exposure context for downstream risk attribution",
    description=(
        "Returns benchmark exposure history aligned to the benchmark performance context. "
        "lotus-performance exposes this as a derived view backed by lotus-core benchmark composition lineage; "
        "lotus-core remains the authoritative system of record."
    ),
)
async def get_benchmark_exposure_context(
    request: BenchmarkExposureContextRequest,
) -> BenchmarkExposureContextResponse:
    """Build benchmark exposure context from governed stateful benchmark sourcing."""
    return await calculate_benchmark_exposure_context_response(request)
