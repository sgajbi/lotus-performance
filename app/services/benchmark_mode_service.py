from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.models.benchmark_analytics_requests import (
    BenchmarkAnalyticsRequest,
    BenchmarkInputMode,
    BenchmarkReturnSource,
    BenchmarkStatelessInput,
)
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import execution_stage_failure_detail
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION, EXECUTION_STAGE_RETRIEVAL
from app.services.input_mode_validation import require_stateful_input, require_stateless_input
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.stateful_benchmark_input_service import (
    StatefulBenchmarkNormalizedInput,
    build_stateful_benchmark_input,
)
from app.services.stateless_benchmark_input_service import normalize_stateless_component_observations


@dataclass(frozen=True)
class ResolvedBenchmarkRequest:
    benchmark_request: BenchmarkPerformanceRequest
    input_mode: BenchmarkInputMode
    source_details: dict[str, int]
    input_count: int


def _benchmark_stateless_source_details(stateless_input: BenchmarkStatelessInput) -> dict[str, int]:
    return {
        "component_observations": len(stateless_input.component_observations),
        "component_price_points": len(stateless_input.component_price_points),
        "benchmark_return_points": len(stateless_input.benchmark_return_points),
    }


def _resolve_stateless_benchmark_request(request: BenchmarkAnalyticsRequest) -> ResolvedBenchmarkRequest:
    stateless_input = require_stateless_input(request.stateless_input)
    component_observations = None
    if request.return_source == BenchmarkReturnSource.CALCULATED:
        component_observations = normalize_stateless_component_observations(
            benchmark_currency=stateless_input.benchmark_currency,
            stateless_input=stateless_input,
        )
    source_details = _benchmark_stateless_source_details(stateless_input)
    return ResolvedBenchmarkRequest(
        benchmark_request=request.to_benchmark_performance_request(
            benchmark_currency=stateless_input.benchmark_currency,
            component_observations=component_observations,
        ),
        input_mode=BenchmarkInputMode.STATELESS,
        source_details=source_details,
        input_count=(
            source_details["component_observations"]
            or source_details["component_price_points"]
            or source_details["benchmark_return_points"]
        ),
    )


def _stateful_benchmark_performance_request(
    request: BenchmarkAnalyticsRequest,
    normalized_input: StatefulBenchmarkNormalizedInput,
) -> BenchmarkPerformanceRequest:
    return request.to_benchmark_performance_request(
        benchmark_currency=normalized_input.benchmark_currency,
        component_observations=[
            observation.model_dump(mode="python") for observation in normalized_input.component_observations
        ],
        benchmark_return_points=[point.model_dump(mode="python") for point in normalized_input.benchmark_return_points],
    )


def _stateful_benchmark_input_count(
    request: BenchmarkAnalyticsRequest,
    normalized_input: StatefulBenchmarkNormalizedInput,
) -> int:
    if request.return_source.value == "calculated":
        return len(normalized_input.component_observations)
    return len(normalized_input.benchmark_return_points)


async def resolve_benchmark_request(
    request: BenchmarkAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedBenchmarkRequest:
    if request.input_mode == BenchmarkInputMode.STATELESS:
        return _resolve_stateless_benchmark_request(request)

    require_stateful_input(request.stateful_input)

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL)
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
            EXECUTION_STAGE_RETRIEVAL,
            details=normalized_input.source_details,
        )
    except Exception as exc:
        execution_registry.fail_stage(
            request.calculation_id,
            EXECUTION_STAGE_RETRIEVAL,
            execution_stage_failure_detail(exc),
        )
        raise

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION)
    try:
        benchmark_request = _stateful_benchmark_performance_request(request, normalized_input)
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_NORMALIZATION,
            details={
                "component_observations": len(normalized_input.component_observations),
                "benchmark_return_points": len(normalized_input.benchmark_return_points),
            },
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION, str(exc))
        raise

    return ResolvedBenchmarkRequest(
        benchmark_request=benchmark_request,
        input_mode=BenchmarkInputMode.STATEFUL,
        source_details=normalized_input.source_details,
        input_count=_stateful_benchmark_input_count(request, normalized_input),
    )
