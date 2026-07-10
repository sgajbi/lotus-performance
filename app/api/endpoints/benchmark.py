from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.async_openapi import async_result_responses, async_submission_responses
from app.api.http_response_adapter import to_fastapi_response
from app.api.mappers.analytics_workflow_requests import map_benchmark_request
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest
from app.models.benchmark_responses import (
    BenchmarkAcceptedResponse,
    BenchmarkPerformanceResponse,
)
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_BENCHMARK
from app.services.async_result_service import resolve_async_result
from app.services.benchmark_calculation_workflow_service import (
    accepted_benchmark_response,
    calculate_benchmark_workflow,
)

router = APIRouter(tags=["Performance"])


BENCHMARK_ENDPOINT_DESCRIPTION = """
Calculate benchmark performance for a named benchmark. Use this endpoint when a caller needs the
benchmark's own return path, component contribution detail, lineage, and async execution handling.

Use `input_mode="stateless"` when the caller supplies benchmark component observations, component
price points, or vendor return points. Use `input_mode="stateful"` when lotus-performance should
source benchmark composition, index prices, return series, and FX inputs from the governed lotus-core
contracts. The default `return_source="calculated"` path derives benchmark returns from component
weights and returns; `return_source="vendor_series"` consumes authored benchmark return points.

Do not use this endpoint as a generic return-series feed for risk engines or downstream analytics
that only need aligned portfolio/benchmark/risk-free series; use `POST /integration/returns/series`
for that purpose.
"""

BENCHMARK_RESULT_ENDPOINT_DESCRIPTION = """
Retrieve a benchmark calculation that previously returned `202 Accepted`. Poll
`/performance/executions/{calculation_id}` for lifecycle status and use this result endpoint for the
completed benchmark payload.
"""


@router.post(
    "/benchmark",
    response_model=BenchmarkPerformanceResponse | BenchmarkAcceptedResponse,
    response_model_exclude_none=True,
    summary="Calculate benchmark performance",
    description=BENCHMARK_ENDPOINT_DESCRIPTION,
    responses=async_submission_responses(
        accepted_model=BenchmarkAcceptedResponse,
        analytics_name="benchmark performance",
        result_path_template="/performance/benchmark/results/{calculation_id}",
    ),
)
async def calculate_benchmark_endpoint(
    request: BenchmarkAnalyticsRequest,
) -> BenchmarkPerformanceResponse | JSONResponse:
    """Calculate or enqueue benchmark performance using stateless or stateful inputs."""
    return to_fastapi_response(await calculate_benchmark_workflow(map_benchmark_request(request)))


@router.get(
    "/benchmark/results/{calculation_id}",
    response_model=BenchmarkPerformanceResponse | BenchmarkAcceptedResponse,
    response_model_exclude_none=True,
    summary="Retrieve async benchmark result",
    description=BENCHMARK_RESULT_ENDPOINT_DESCRIPTION,
    responses=async_result_responses(
        accepted_model=BenchmarkAcceptedResponse,
        analytics_name="benchmark performance",
        result_path_template="/performance/benchmark/results/{calculation_id}",
        not_found_detail="Async benchmark result not found for the given calculation_id.",
        failed_detail="Async benchmark execution failed.",
    ),
)
async def get_benchmark_result(calculation_id: UUID, request: Request) -> BenchmarkPerformanceResponse | JSONResponse:
    """Return a completed async benchmark calculation or its accepted/failed status."""
    return to_fastapi_response(
        resolve_async_result(
            calculation_id=calculation_id,
            expected_analytics_type=ANALYTICS_WORKFLOW_BENCHMARK,
            response_model=BenchmarkPerformanceResponse,
            accepted_response_factory=accepted_benchmark_response,
            not_found_detail="Async benchmark result not found for the given calculation_id.",
            failed_detail="Async benchmark execution failed.",
            request_headers=request.headers,
        )
    )
