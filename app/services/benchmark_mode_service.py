from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.benchmark_analytics_requests import (
    BenchmarkAnalyticsRequest,
    BenchmarkInputMode,
)
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services.execution_registry import execution_registry
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateless_benchmark_input_service import normalize_stateless_component_observations


@dataclass(frozen=True)
class ResolvedBenchmarkRequest:
    benchmark_request: BenchmarkPerformanceRequest
    input_mode: BenchmarkInputMode
    source_details: dict[str, int]
    input_count: int


async def resolve_benchmark_request(
    request: BenchmarkAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedBenchmarkRequest:
    if request.input_mode == BenchmarkInputMode.STATELESS:
        if request.stateless_input is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="stateless_input is required when input_mode=stateless",
            )
        return ResolvedBenchmarkRequest(
            benchmark_request=request.to_benchmark_performance_request(
                benchmark_currency=request.stateless_input.benchmark_currency,
                component_observations=(
                    normalize_stateless_component_observations(
                        benchmark_currency=request.stateless_input.benchmark_currency,
                        stateless_input=request.stateless_input,
                    )
                    if request.return_source.value == "calculated"
                    else None
                ),
            ),
            input_mode=BenchmarkInputMode.STATELESS,
            source_details={
                "component_observations": len(request.stateless_input.component_observations),
                "component_price_points": len(request.stateless_input.component_price_points),
                "benchmark_return_points": len(request.stateless_input.benchmark_return_points),
            },
            input_count=(
                len(request.stateless_input.component_observations)
                or len(request.stateless_input.component_price_points)
                or len(request.stateless_input.benchmark_return_points)
            ),
        )

    stateful_input = request.stateful_input
    if stateful_input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stateful_input is required when input_mode=stateful",
        )

    execution_registry.start_stage(request.calculation_id, "retrieval")
    stateful_input_service = build_stateful_input_service(settings=settings)
    try:
        normalized_input = await build_stateful_benchmark_input(
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            benchmark_id=request.benchmark_id,
            as_of_date=request.report_end_date,
            start_date=request.benchmark_start_date,
            end_date=request.report_end_date,
            return_source=request.return_source,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "retrieval",
            details=normalized_input.source_details,
        )
    except HTTPException as exc:
        execution_registry.fail_stage(request.calculation_id, "retrieval", str(exc.detail))
        raise

    execution_registry.start_stage(request.calculation_id, "normalization")
    try:
        benchmark_request = request.to_benchmark_performance_request(
            benchmark_currency=normalized_input.benchmark_currency,
            component_observations=[
                observation.model_dump(mode="python") for observation in normalized_input.component_observations
            ],
            benchmark_return_points=[
                point.model_dump(mode="python") for point in normalized_input.benchmark_return_points
            ],
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "normalization",
            details={
                "component_observations": len(normalized_input.component_observations),
                "benchmark_return_points": len(normalized_input.benchmark_return_points),
            },
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, "normalization", str(exc))
        raise

    return ResolvedBenchmarkRequest(
        benchmark_request=benchmark_request,
        input_mode=BenchmarkInputMode.STATEFUL,
        source_details=normalized_input.source_details,
        input_count=(
            len(normalized_input.component_observations)
            if request.return_source.value == "calculated"
            else len(normalized_input.benchmark_return_points)
        ),
    )
