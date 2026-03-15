from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.contribution_analytics_requests import (
    ContributionAnalyticsRequest,
    ContributionInputMode,
)
from app.models.contribution_requests import ContributionRequest
from app.services.execution_registry import execution_registry
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.stateful_contribution_input_service import (
    build_stateful_contribution_input,
    retrieve_stateful_contribution_source_input,
)


@dataclass(frozen=True)
class ResolvedContributionRequest:
    contribution_request: ContributionRequest
    input_mode: ContributionInputMode


async def resolve_contribution_request(
    request: ContributionAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedContributionRequest:
    if request.input_mode == ContributionInputMode.STATELESS:
        return ResolvedContributionRequest(
            contribution_request=request.to_stateless_contribution_request(),
            input_mode=ContributionInputMode.STATELESS,
        )

    stateful_input = request.stateful_input
    if stateful_input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stateful_input is required when input_mode=stateful",
        )

    stateful_input_service = build_stateful_input_service(settings=settings)
    execution_registry.start_stage(request.calculation_id, "retrieval")
    try:
        source_input = await retrieve_stateful_contribution_source_input(
            settings=settings,
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.report_end_date,
            report_start_date=request.report_start_date,
            report_end_date=request.report_end_date,
            reporting_currency=request.report_ccy,
            consumer_system=stateful_input.consumer_system,
            dimensions=list(stateful_input.dimensions),
            include_cash_flows=stateful_input.include_cash_flows,
            filters=stateful_input.filters.model_dump(mode="python"),
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "retrieval",
            details={
                "portfolio_observations": len(source_input.portfolio_input.observations),
                "position_rows": len(source_input.position_rows),
                "portfolio_chunk_count": source_input.portfolio_input.retrieval_metadata.chunk_count,
                "portfolio_page_count": source_input.portfolio_input.retrieval_metadata.page_count,
                "position_chunk_count": source_input.position_retrieval_metadata.chunk_count,
                "position_page_count": source_input.position_retrieval_metadata.page_count,
            },
        )
    except HTTPException as exc:
        execution_registry.fail_stage(request.calculation_id, "retrieval", str(exc.detail))
        raise

    execution_registry.start_stage(request.calculation_id, "normalization")
    try:
        normalized_input = build_stateful_contribution_input(
            source_input=source_input,
            metric_basis=stateful_input.metric_basis,
            currency_mode=request.currency_mode,
            reporting_currency=request.report_ccy,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "normalization",
            details={
                "portfolio_points": len(normalized_input.portfolio_data.valuation_points),
                "positions": len(normalized_input.positions_data),
            },
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, "normalization", str(exc))
        raise

    return ResolvedContributionRequest(
        contribution_request=request.to_stateless_contribution_request(
            portfolio_data=normalized_input.portfolio_data,
            positions_data=normalized_input.positions_data,
        ),
        input_mode=ContributionInputMode.STATEFUL,
    )
