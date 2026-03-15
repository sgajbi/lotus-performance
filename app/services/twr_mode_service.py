from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.requests import PerformanceRequest
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode
from app.services.execution_registry import execution_registry
from app.services.stateful_performance_input_service import (
    build_stateful_portfolio_valuation_input,
    retrieve_stateful_portfolio_input,
)


@dataclass(frozen=True)
class ResolvedTWRRequest:
    performance_request: PerformanceRequest
    input_mode: TWRInputMode


async def resolve_twr_request(
    request: TWRAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedTWRRequest:
    if request.input_mode == TWRInputMode.STATELESS:
        return ResolvedTWRRequest(
            performance_request=request.to_stateless_performance_request(),
            input_mode=TWRInputMode.STATELESS,
        )

    execution_registry.start_stage(request.calculation_id, "retrieval")
    stateful_input = request.stateful_input
    if stateful_input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stateful_input is required when input_mode=stateful",
        )

    try:
        source_input = await retrieve_stateful_portfolio_input(
            settings=settings,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.report_end_date,
            start_date=request.performance_start_date,
            end_date=request.report_end_date,
            reporting_currency=request.report_ccy,
            consumer_system=stateful_input.consumer_system,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "retrieval",
            details={
                "portfolio_observations": len(source_input.observations),
                "portfolio_chunk_count": source_input.retrieval_metadata.chunk_count,
                "portfolio_page_count": source_input.retrieval_metadata.page_count,
            },
        )
    except HTTPException as exc:
        execution_registry.fail_stage(request.calculation_id, "retrieval", str(exc.detail))
        raise

    execution_registry.start_stage(request.calculation_id, "normalization")
    try:
        resolved_input = build_stateful_portfolio_valuation_input(source_input)
        execution_registry.complete_stage(
            request.calculation_id,
            "normalization",
            details={"valuation_points": len(resolved_input.valuation_points)},
        )
    except Exception as exc:
        execution_registry.fail_stage(
            request.calculation_id,
            "normalization",
            str(exc),
        )
        raise

    performance_request = PerformanceRequest.model_validate(
        {
            **request.model_dump(
                exclude={"input_mode", "stateless_input", "stateful_input", "valuation_points"},
                mode="python",
            ),
            "performance_start_date": resolved_input.performance_start_date,
            "valuation_points": resolved_input.valuation_points,
        }
    )
    return ResolvedTWRRequest(
        performance_request=performance_request,
        input_mode=TWRInputMode.STATEFUL,
    )
