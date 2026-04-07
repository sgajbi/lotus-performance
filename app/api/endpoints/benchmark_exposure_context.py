from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.benchmark_exposure_context import BenchmarkExposureContextRequest, BenchmarkExposureContextResponse
from app.services.benchmark_exposure_context_service import build_benchmark_exposure_context
from app.services.portfolio_source_service import build_stateful_input_service

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
    stateful_input_service = build_stateful_input_service(settings=get_settings())
    return await build_benchmark_exposure_context(
        request=request,
        stateful_input_service=stateful_input_service,
    )
