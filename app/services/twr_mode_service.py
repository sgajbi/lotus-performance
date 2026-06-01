from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource, BenchmarkStatefulInput
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION, EXECUTION_STAGE_RETRIEVAL
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateful_input_service import StatefulInputService
from app.services.stateful_performance_input_service import (
    build_stateful_portfolio_valuation_input,
    retrieve_stateful_portfolio_input,
)
from app.services.stateful_upstream_errors import (
    raise_for_stateful_control_plane_unavailable,
    raise_for_stateful_source_unavailable,
)
from app.services.stateless_benchmark_input_service import normalize_stateless_component_observations
from core.errors import HTTP_422_UNPROCESSABLE


@dataclass(frozen=True)
class ResolvedTWRRequest:
    performance_request: PerformanceRequest
    input_mode: TWRInputMode
    benchmark_request: BenchmarkPerformanceRequest | None = None
    benchmark_input_mode: BenchmarkInputMode | None = None
    resolved_benchmark_id: str | None = None


def _benchmark_requested(request: TWRAnalyticsRequest) -> bool:
    return request.include_benchmark or request.benchmark is not None


async def resolve_twr_request(
    request: TWRAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedTWRRequest:
    needs_retrieval = request.input_mode == TWRInputMode.STATEFUL or (
        _benchmark_requested(request) and _get_requested_benchmark_mode(request) == BenchmarkInputMode.STATEFUL
    )

    if not needs_retrieval:
        benchmark_start_date = _resolve_benchmark_start_date_from_request(request)
        return ResolvedTWRRequest(
            performance_request=request.to_stateless_performance_request(),
            input_mode=TWRInputMode.STATELESS,
            benchmark_request=_resolve_stateless_twr_benchmark_request(
                request,
                benchmark_start_date=benchmark_start_date,
            ),
            benchmark_input_mode=_get_requested_benchmark_mode(request),
            resolved_benchmark_id=_get_requested_benchmark_id(request),
        )

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL)
    retrieval_details: dict[str, object] = {}
    portfolio_input = None
    benchmark_resolution = None
    stateful_input_service = build_stateful_input_service(settings=settings)
    benchmark_start_date = None

    try:
        if request.input_mode == TWRInputMode.STATEFUL:
            stateful_input = request.stateful_input
            if stateful_input is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="stateful_input is required when input_mode=stateful",
                )
            derived_start_date = None
            if request.performance_start_date is None:
                derived_start_date = await _resolve_stateful_portfolio_start_date(
                    request=request,
                    stateful_input_service=stateful_input_service,
                )
            resolved_start_date = derived_start_date or request.performance_start_date
            if resolved_start_date is None:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE,
                    detail="Unable to derive a performance_start_date for the stateful TWR request.",
                )
            portfolio_input = await retrieve_stateful_portfolio_input(
                settings=settings,
                stateful_input_service=(stateful_input_service if derived_start_date is not None else None),
                calculation_id=request.calculation_id,
                portfolio_id=request.portfolio_id,
                as_of_date=request.report_end_date,
                start_date=resolved_start_date,
                end_date=request.report_end_date,
                reporting_currency=request.report_ccy,
                consumer_system=LOTUS_PERFORMANCE_CONSUMER_SYSTEM,
            )
            retrieval_details.update(
                {
                    "portfolio_observations": len(portfolio_input.observations),
                    "portfolio_chunk_count": portfolio_input.retrieval_metadata.chunk_count,
                    "portfolio_page_count": portfolio_input.retrieval_metadata.page_count,
                }
            )
            benchmark_start_date = _resolve_benchmark_start_date_from_stateful_source(portfolio_input.observations)

        if _benchmark_requested(request):
            if benchmark_start_date is None:
                benchmark_start_date = _resolve_benchmark_start_date_from_request(request)
            benchmark_resolution = await _resolve_twr_benchmark_source_input(
                request=request,
                stateful_input_service=stateful_input_service,
                benchmark_start_date=benchmark_start_date,
            )
            if benchmark_resolution is not None and benchmark_resolution.source_details:
                retrieval_details.update(benchmark_resolution.source_details)

        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_RETRIEVAL,
            details=retrieval_details,
        )
    except HTTPException as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL, str(exc.detail))
        raise

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION)
    try:
        resolved_input = (
            build_stateful_portfolio_valuation_input(
                source_input=portfolio_input,
                report_end_date=request.report_end_date,
            )
            if portfolio_input is not None
            else None
        )
        benchmark_start_date = benchmark_start_date or _resolve_benchmark_start_date_from_request(request)
        benchmark_request = (
            _build_resolved_twr_benchmark_request(
                request=request,
                benchmark_resolution=benchmark_resolution,
                benchmark_start_date=benchmark_start_date,
            )
            if _benchmark_requested(request)
            else None
        )
        normalization_details: dict[str, object] = {}
        if resolved_input is not None:
            normalization_details["valuation_points"] = len(resolved_input.valuation_points)
        if benchmark_request is not None:
            normalization_details["benchmark_component_observations"] = len(benchmark_request.component_observations)
            normalization_details["benchmark_return_points"] = len(benchmark_request.benchmark_return_points)
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_NORMALIZATION,
            details=normalization_details,
        )
    except Exception as exc:
        execution_registry.fail_stage(
            request.calculation_id,
            EXECUTION_STAGE_NORMALIZATION,
            str(exc),
        )
        raise

    if resolved_input is None:
        performance_request = request.to_stateless_performance_request()
        input_mode = TWRInputMode.STATELESS
    else:
        performance_request = PerformanceRequest.model_validate(
            {
                **request.model_dump(
                    exclude={
                        "input_mode",
                        "stateless_input",
                        "stateful_input",
                        "valuation_points",
                        "benchmark",
                        "include_benchmark",
                    },
                    mode="python",
                ),
                "performance_start_date": resolved_input.performance_start_date,
                "valuation_points": resolved_input.valuation_points,
                "source_quality_evidence": resolved_input.source_quality_evidence,
            }
        )
        input_mode = TWRInputMode.STATEFUL

    return ResolvedTWRRequest(
        performance_request=performance_request,
        input_mode=input_mode,
        benchmark_request=benchmark_request if _benchmark_requested(request) else None,
        benchmark_input_mode=_get_requested_benchmark_mode(request),
        resolved_benchmark_id=(
            benchmark_resolution.benchmark_id
            if benchmark_resolution is not None
            else _get_requested_benchmark_id(request)
            if _benchmark_requested(request)
            else None
        ),
    )


def _resolve_stateless_twr_benchmark_request(
    request: TWRAnalyticsRequest,
    *,
    benchmark_start_date=None,
) -> BenchmarkPerformanceRequest | None:
    benchmark = request.benchmark
    if not _benchmark_requested(request) or _get_requested_benchmark_mode(request) != BenchmarkInputMode.STATELESS:
        return None
    if benchmark is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="benchmark configuration is required when include_benchmark=true in stateless mode.",
        )
    stateless_input = benchmark.stateless_input
    if stateless_input is None or benchmark.benchmark_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="benchmark stateless mode requires benchmark_id and stateless_input.",
        )
    return BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": request.calculation_id,
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_start_date": benchmark_start_date or request.performance_start_date,
            "report_start_date": request.report_start_date,
            "report_end_date": request.report_end_date,
            "analyses": [analysis.model_dump(mode="python") for analysis in request.analyses],
            "return_source": benchmark.return_source.value,
            "benchmark_currency": stateless_input.benchmark_currency,
            "component_observations": (
                normalize_stateless_component_observations(
                    benchmark_currency=stateless_input.benchmark_currency,
                    stateless_input=stateless_input,
                )
                if benchmark.return_source == BenchmarkReturnSource.CALCULATED
                else []
            ),
            "benchmark_return_points": [
                point.model_dump(mode="python") for point in stateless_input.benchmark_return_points
            ],
            "precision_mode": request.precision_mode,
            "rounding_precision": request.rounding_precision,
            "calendar": request.calendar.model_dump(mode="python"),
            "annualization": request.annualization.model_dump(mode="python"),
            "output": request.output.model_dump(mode="python"),
        }
    )


async def _resolve_stateful_portfolio_start_date(
    *,
    request: TWRAnalyticsRequest,
    stateful_input_service: StatefulInputService,
) -> date:
    upstream_status, upstream_payload = await stateful_input_service.get_portfolio_reference(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        as_of_date=request.report_end_date,
    )
    raise_for_stateful_control_plane_unavailable(
        source_label="stateful portfolio reference source",
        upstream_status=upstream_status,
    )
    portfolio_open_date = upstream_payload.get("portfolio_open_date")
    if not isinstance(portfolio_open_date, str):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="Stateful source missing portfolio_open_date.",
        )
    try:
        return date.fromisoformat(portfolio_open_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="Invalid portfolio_open_date from stateful source.",
        ) from exc


@dataclass(frozen=True)
class _ResolvedTWRBenchmarkSourceInput:
    benchmark_id: str
    benchmark_request: BenchmarkPerformanceRequest
    source_details: dict[str, int]


async def _resolve_twr_benchmark_source_input(
    *,
    request: TWRAnalyticsRequest,
    stateful_input_service: StatefulInputService,
    benchmark_start_date,
) -> _ResolvedTWRBenchmarkSourceInput | None:
    benchmark = request.benchmark
    if not _benchmark_requested(request) or _get_requested_benchmark_mode(request) != BenchmarkInputMode.STATEFUL:
        return None
    stateful_input = benchmark.stateful_input if benchmark is not None else None
    if stateful_input is None:
        stateful_input = _resolve_default_stateful_benchmark_input(request)
    benchmark_id = benchmark.benchmark_id if benchmark is not None else None
    source_details: dict[str, int] = {}
    if benchmark_id is None:
        assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
            portfolio_id=request.portfolio_id,
            as_of_date=request.report_end_date,
            reporting_currency=request.report_ccy,
            calculation_id=request.calculation_id,
        )
        if assignment_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No benchmark assignment found for portfolio_id={request.portfolio_id}.",
            )
        if assignment_status >= status.HTTP_400_BAD_REQUEST:
            raise_for_stateful_source_unavailable(
                source_label="benchmark assignment",
                upstream_status=assignment_status,
            )
        benchmark_id_raw = assignment_payload.get("benchmark_id")
        if not isinstance(benchmark_id_raw, str) or not benchmark_id_raw:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail="benchmark assignment payload missing benchmark_id.",
            )
        benchmark_id = benchmark_id_raw
        source_details["resolved_benchmark_assignment"] = 1

    normalized_input = await build_stateful_benchmark_input(
        stateful_input_service=stateful_input_service,
        calculation_id=request.calculation_id,
        benchmark_id=benchmark_id,
        as_of_date=request.report_end_date,
        start_date=benchmark_start_date,
        end_date=request.report_end_date,
        return_source=_get_requested_benchmark_return_source(request),
    )
    source_details.update(normalized_input.source_details)
    benchmark_request = BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": request.calculation_id,
            "benchmark_id": benchmark_id,
            "benchmark_start_date": benchmark_start_date,
            "report_start_date": request.report_start_date,
            "report_end_date": request.report_end_date,
            "analyses": [analysis.model_dump(mode="python") for analysis in request.analyses],
            "return_source": _get_requested_benchmark_return_source(request).value,
            "benchmark_currency": normalized_input.benchmark_currency,
            "component_observations": [
                item.model_dump(mode="python") for item in normalized_input.component_observations
            ],
            "benchmark_return_points": [
                item.model_dump(mode="python") for item in normalized_input.benchmark_return_points
            ],
            "precision_mode": request.precision_mode,
            "rounding_precision": request.rounding_precision,
            "calendar": request.calendar.model_dump(mode="python"),
            "annualization": request.annualization.model_dump(mode="python"),
            "output": request.output.model_dump(mode="python"),
        }
    )
    return _ResolvedTWRBenchmarkSourceInput(
        benchmark_id=benchmark_id,
        benchmark_request=benchmark_request,
        source_details={key: int(value) for key, value in source_details.items()},
    )


def _build_resolved_twr_benchmark_request(
    *,
    request: TWRAnalyticsRequest,
    benchmark_resolution: _ResolvedTWRBenchmarkSourceInput | None,
    benchmark_start_date,
) -> BenchmarkPerformanceRequest | None:
    if benchmark_resolution is None:
        return _resolve_stateless_twr_benchmark_request(request, benchmark_start_date=benchmark_start_date)
    return benchmark_resolution.benchmark_request


def _get_requested_benchmark_mode(request: TWRAnalyticsRequest) -> BenchmarkInputMode | None:
    if request.benchmark is not None:
        return request.benchmark.input_mode
    if request.include_benchmark and request.input_mode == TWRInputMode.STATEFUL:
        return BenchmarkInputMode.STATEFUL
    return None


def _get_requested_benchmark_id(request: TWRAnalyticsRequest) -> str | None:
    return request.benchmark.benchmark_id if request.benchmark is not None else None


def _get_requested_benchmark_return_source(request: TWRAnalyticsRequest) -> BenchmarkReturnSource:
    if request.benchmark is not None:
        return request.benchmark.return_source
    return BenchmarkReturnSource.CALCULATED


def _resolve_default_stateful_benchmark_input(request: TWRAnalyticsRequest) -> BenchmarkStatefulInput:
    stateful_input = request.stateful_input
    if stateful_input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stateful_input is required when include_benchmark=true in stateful mode",
        )
    return BenchmarkStatefulInput()


def _resolve_benchmark_start_date_from_request(request: TWRAnalyticsRequest):
    performance_request = (
        request.to_stateless_performance_request() if request.input_mode == TWRInputMode.STATELESS else None
    )
    if performance_request is not None and performance_request.valuation_points:
        return min(point.perf_date for point in performance_request.valuation_points)
    return request.performance_start_date or request.report_end_date


def _resolve_benchmark_start_date_from_stateful_source(observations: list[dict]) -> date | None:
    dates = [
        date.fromisoformat(observation["valuation_date"])
        for observation in observations
        if isinstance(observation, dict) and isinstance(observation.get("valuation_date"), str)
    ]
    if dates:
        return min(dates)
    return None
