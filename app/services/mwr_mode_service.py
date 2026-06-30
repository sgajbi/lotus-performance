from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException

from app.core.config import Settings
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.models.mwr_requests import MoneyWeightedReturnRequest
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION, EXECUTION_STAGE_RETRIEVAL
from app.services.input_mode_validation import require_stateful_input
from app.services.mwr_cash_flow_window_validation import validate_mwr_cash_flow_window
from app.services.mwr_fx_evidence_service import build_source_preconverted_mwr_currency_evidence
from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM
from app.services.stateful_mwr_input_service import (
    MWRCurrencyEvidence,
    StatefulMWRInput,
    build_stateful_mwr_input_for_window,
)
from app.services.stateful_performance_input_service import StatefulPortfolioInput, retrieve_stateful_portfolio_input


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
        return _resolve_stateless_mwr_request(request)

    stateful_input = require_stateful_input(request.stateful_input)
    source_input = await _retrieve_stateful_mwr_source_input(
        request=request,
        window_start_date=stateful_input.window_start_date,
        settings=settings,
    )
    normalized_input = _normalize_stateful_mwr_input(
        request=request,
        source_input=source_input,
        window_start_date=stateful_input.window_start_date,
    )
    return _resolved_stateful_mwr_request(request=request, normalized_input=normalized_input)


def _resolve_stateless_mwr_request(request: MoneyWeightedReturnAnalyticsRequest) -> ResolvedMWRRequest:
    mwr_request = request.to_stateless_mwr_request()
    _validate_resolved_mwr_request_window(mwr_request)
    return ResolvedMWRRequest(
        mwr_request=mwr_request,
        input_mode=MWRInputMode.STATELESS,
        currency_evidence=build_source_preconverted_mwr_currency_evidence(mwr_request),
    )


async def _retrieve_stateful_mwr_source_input(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    window_start_date: date,
    settings: Settings,
) -> StatefulPortfolioInput:
    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL)
    try:
        source_input = await retrieve_stateful_portfolio_input(
            settings=settings,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of,
            start_date=window_start_date,
            end_date=request.as_of,
            reporting_currency=request.report_ccy,
            consumer_system=LOTUS_PERFORMANCE_CONSUMER_SYSTEM,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_RETRIEVAL,
            details={
                "portfolio_observations": len(source_input.observations),
                "portfolio_chunk_count": source_input.retrieval_metadata.chunk_count,
                "portfolio_page_count": source_input.retrieval_metadata.page_count,
            },
        )
    except HTTPException as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL, str(exc.detail))
        raise
    return source_input


def _normalize_stateful_mwr_input(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    source_input: StatefulPortfolioInput,
    window_start_date: date,
) -> StatefulMWRInput:
    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION)
    try:
        normalized_input = build_stateful_mwr_input_for_window(
            source_input=source_input,
            window_start_date=window_start_date,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_NORMALIZATION,
            details={"cashflows": len(normalized_input.cash_flows)},
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION, str(exc))
        raise
    return normalized_input


def _resolved_stateful_mwr_request(
    *,
    request: MoneyWeightedReturnAnalyticsRequest,
    normalized_input: StatefulMWRInput,
) -> ResolvedMWRRequest:
    mwr_request = request.to_stateless_mwr_request(
        begin_mv=float(normalized_input.begin_mv),
        end_mv=float(normalized_input.end_mv),
        cash_flows=normalized_input.cash_flows,
        start_date=normalized_input.start_date,
    )
    _validate_resolved_mwr_request_window(mwr_request)
    return ResolvedMWRRequest(
        mwr_request=mwr_request,
        input_mode=MWRInputMode.STATEFUL,
        currency_evidence=normalized_input.currency_evidence,
    )


def _validate_resolved_mwr_request_window(mwr_request: MoneyWeightedReturnRequest) -> None:
    resolved_start_date = mwr_request.start_date
    if resolved_start_date is None:
        cash_flow_dates = [cash_flow.date for cash_flow in mwr_request.cash_flows]
        resolved_start_date = min(cash_flow_dates) if cash_flow_dates else mwr_request.as_of
    validate_mwr_cash_flow_window(
        cash_flows=mwr_request.cash_flows,
        start_date=resolved_start_date,
        end_date=mwr_request.as_of,
    )
