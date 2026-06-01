from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from app.core.config import Settings
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.services.execution_registry import execution_registry
from app.services.input_mode_validation import require_stateful_input
from app.services.mwr_fx_evidence_service import build_source_preconverted_mwr_currency_evidence
from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM
from app.services.stateful_mwr_input_service import MWRCurrencyEvidence, build_stateful_mwr_input_for_window
from app.services.stateful_performance_input_service import retrieve_stateful_portfolio_input


@dataclass(frozen=True)
class ResolvedMWRRequest:
    mwr_request: MoneyWeightedReturnRequest
    input_mode: MWRInputMode
    currency_evidence: MWRCurrencyEvidence | None = None


async def resolve_mwr_request(
    request: MoneyWeightedReturnAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedMWRRequest:
    if request.input_mode == MWRInputMode.STATELESS:
        mwr_request = request.to_stateless_mwr_request()
        return ResolvedMWRRequest(
            mwr_request=mwr_request,
            input_mode=MWRInputMode.STATELESS,
            currency_evidence=build_source_preconverted_mwr_currency_evidence(mwr_request),
        )

    stateful_input = require_stateful_input(request.stateful_input)

    execution_registry.start_stage(request.calculation_id, "retrieval")
    try:
        source_input = await retrieve_stateful_portfolio_input(
            settings=settings,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of,
            start_date=stateful_input.window_start_date,
            end_date=request.as_of,
            reporting_currency=request.report_ccy,
            consumer_system=LOTUS_PERFORMANCE_CONSUMER_SYSTEM,
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
        normalized_input = build_stateful_mwr_input_for_window(
            source_input=source_input,
            window_start_date=stateful_input.window_start_date,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            "normalization",
            details={"cashflows": len(normalized_input.cash_flows)},
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, "normalization", str(exc))
        raise

    return ResolvedMWRRequest(
        mwr_request=request.to_stateless_mwr_request(
            begin_mv=float(normalized_input.begin_mv),
            end_mv=float(normalized_input.end_mv),
            cash_flows=normalized_input.cash_flows,
            start_date=normalized_input.start_date,
        ),
        input_mode=MWRInputMode.STATEFUL,
        currency_evidence=normalized_input.currency_evidence,
    )
