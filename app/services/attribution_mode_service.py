from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.core.config import Settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION, EXECUTION_STAGE_RETRIEVAL
from app.services.input_mode_validation import require_stateful_input
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM
from app.services.stateful_attribution_input_service import (
    build_stateful_attribution_input,
    retrieve_stateful_attribution_source_input,
)


@dataclass(frozen=True)
class ResolvedAttributionRequest:
    attribution_request: AttributionRequest
    input_mode: AttributionInputMode
    input_count: int
    resolved_benchmark_id: str | None = None
    resolved_benchmark_return_source: str | None = None


async def resolve_attribution_request(
    request: AttributionAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedAttributionRequest:
    if request.input_mode == AttributionInputMode.STATELESS:
        attribution_request = request.to_stateless_attribution_request()
        return ResolvedAttributionRequest(
            attribution_request=attribution_request,
            input_mode=AttributionInputMode.STATELESS,
            input_count=_resolved_attribution_input_count(attribution_request),
        )

    stateful_input = require_stateful_input(request.stateful_input)

    stateful_input_service = build_stateful_input_service(settings=settings)
    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL)
    try:
        source_input = await retrieve_stateful_attribution_source_input(
            settings=settings,
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.report_end_date,
            report_start_date=request.report_start_date,
            report_end_date=request.report_end_date,
            reporting_currency=request.report_ccy,
            consumer_system=LOTUS_PERFORMANCE_CONSUMER_SYSTEM,
            group_by=request.group_by,
            dimensions=list(stateful_input.dimensions),
            include_cash_flows=stateful_input.include_cash_flows,
            filters=stateful_input.filters.model_dump(mode="python"),
            benchmark_id_override=stateful_input.benchmark_id,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_RETRIEVAL,
            details={
                "portfolio_observations": len(source_input.portfolio_input.observations),
                "position_rows": len(source_input.position_rows),
                "benchmark_components": source_input.benchmark_source_details.get("benchmark_components", 0),
                "benchmark_component_observations": len(source_input.benchmark_component_observations),
                "portfolio_chunk_count": source_input.portfolio_input.retrieval_metadata.chunk_count,
                "portfolio_page_count": source_input.portfolio_input.retrieval_metadata.page_count,
                "position_chunk_count": source_input.position_retrieval_metadata.chunk_count,
                "position_page_count": source_input.position_retrieval_metadata.page_count,
                "benchmark_chunk_count": source_input.benchmark_retrieval_metadata.chunk_count,
                "benchmark_page_count": source_input.benchmark_retrieval_metadata.page_count,
                "fx_pair_count": source_input.benchmark_source_details.get("fx_pair_count", 0),
                "fx_chunk_count": source_input.benchmark_source_details.get("fx_chunk_count", 0),
                "fx_page_count": source_input.benchmark_source_details.get("fx_page_count", 0),
                "index_request_count": source_input.index_retrieval_metadata.page_count,
            },
        )
    except HTTPException as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL, str(exc.detail))
        raise

    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION)
    try:
        normalized_input = build_stateful_attribution_input(
            source_input=source_input,
            mode=request.mode.value,
            group_by=request.group_by,
            metric_basis=stateful_input.metric_basis,
            currency_mode=request.currency_mode,
            fx=request.fx,
            reporting_currency=request.report_ccy,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_NORMALIZATION,
            details={
                "portfolio_points": len(normalized_input.portfolio_data.valuation_points),
                "instruments": len(normalized_input.instruments_data),
                "benchmark_groups": len(normalized_input.benchmark_groups_data),
                "source_alignment": normalized_input.source_alignment_evidence,
            },
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION, str(exc))
        raise

    return ResolvedAttributionRequest(
        attribution_request=request.to_stateless_attribution_request(
            portfolio_data=normalized_input.portfolio_data,
            instruments_data=normalized_input.instruments_data,
            benchmark_groups_data=normalized_input.benchmark_groups_data,
        ),
        input_mode=AttributionInputMode.STATEFUL,
        input_count=(len(normalized_input.instruments_data) + len(normalized_input.benchmark_groups_data)),
        resolved_benchmark_id=source_input.benchmark_id,
        resolved_benchmark_return_source=BenchmarkReturnSource.CALCULATED.value,
    )


def _resolved_attribution_input_count(request: AttributionRequest) -> int:
    return (
        len(request.instruments_data or [])
        + len(request.portfolio_groups_data or [])
        + len(request.benchmark_groups_data or [])
    )
