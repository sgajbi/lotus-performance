from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.models.contribution_analytics_requests import (
    ContributionAnalyticsRequest,
    ContributionInputMode,
    ContributionStatefulInput,
)
from app.models.contribution_requests import ContributionRequest, ResolvedContributionExecutionRequest
from app.services.currency_code_normalization import normalized_currency_code
from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import execution_stage_failure_detail
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION, EXECUTION_STAGE_RETRIEVAL
from app.services.input_mode_validation import require_stateful_input
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.service_identity import LOTUS_PERFORMANCE_CONSUMER_SYSTEM
from app.services.stateful_contribution_input_service import (
    StatefulContributionNormalizedInput,
    StatefulContributionSourceInput,
    build_stateful_contribution_input,
    retrieve_stateful_contribution_source_input,
)
from app.services.stateful_input_service import RetrievalMetadata


@dataclass(frozen=True)
class ResolvedContributionRequest:
    contribution_request: ContributionRequest
    input_mode: ContributionInputMode
    position_count: int
    portfolio_base_currency: str | None = None
    source_preconverted_reporting_currency: str | None = None


def resolved_contribution_identity_payload(
    request: ContributionRequest,
    *,
    portfolio_base_currency: str | None,
    source_preconverted_reporting_currency: str | None,
) -> ResolvedContributionExecutionRequest:
    """Bind published denomination provenance to the resolved calculation identity."""
    return ResolvedContributionExecutionRequest(
        contribution_request=request,
        portfolio_base_currency=portfolio_base_currency,
        source_preconverted_reporting_currency=source_preconverted_reporting_currency,
    )


async def resolve_contribution_request(
    request: ContributionAnalyticsRequest,
    *,
    settings: Settings,
) -> ResolvedContributionRequest:
    if request.input_mode == ContributionInputMode.STATELESS:
        return _resolved_stateless_contribution_request(request)

    stateful_input = require_stateful_input(request.stateful_input)
    source_input = await _retrieve_stateful_contribution_source_input(
        request=request,
        stateful_input=stateful_input,
        settings=settings,
    )
    normalized_input = _normalize_stateful_contribution_input(
        request=request,
        stateful_input=stateful_input,
        source_input=source_input,
    )
    return _resolved_stateful_contribution_request(request, normalized_input)


async def _retrieve_stateful_contribution_source_input(
    *,
    request: ContributionAnalyticsRequest,
    stateful_input: ContributionStatefulInput,
    settings: Settings,
) -> StatefulContributionSourceInput:
    stateful_input_service = build_stateful_input_service(settings=settings)
    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_RETRIEVAL)
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
            consumer_system=LOTUS_PERFORMANCE_CONSUMER_SYSTEM,
            dimensions=list(stateful_input.dimensions),
            include_cash_flows=stateful_input.include_cash_flows,
            filters=stateful_input.filters.model_dump(mode="python"),
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_RETRIEVAL,
            details=_contribution_retrieval_stage_details(source_input),
        )
    except Exception as exc:
        execution_registry.fail_stage(
            request.calculation_id,
            EXECUTION_STAGE_RETRIEVAL,
            execution_stage_failure_detail(exc),
        )
        raise
    return source_input


def _normalize_stateful_contribution_input(
    *,
    request: ContributionAnalyticsRequest,
    stateful_input: ContributionStatefulInput,
    source_input: StatefulContributionSourceInput,
) -> StatefulContributionNormalizedInput:
    execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION)
    try:
        normalized_input = build_stateful_contribution_input(
            source_input=source_input,
            metric_basis=stateful_input.metric_basis,
            currency_mode=request.currency_mode,
            fx=request.fx,
            reporting_currency=request.report_ccy,
            portfolio_base_currency=request.currency,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_NORMALIZATION,
            details=_contribution_normalization_stage_details(normalized_input),
        )
    except Exception as exc:
        execution_registry.fail_stage(request.calculation_id, EXECUTION_STAGE_NORMALIZATION, str(exc))
        raise
    return normalized_input


def _resolved_stateful_contribution_request(
    request: ContributionAnalyticsRequest,
    normalized_input: StatefulContributionNormalizedInput,
) -> ResolvedContributionRequest:
    contribution_request = request.to_stateless_contribution_request(
        portfolio_data=normalized_input.portfolio_data,
        positions_data=normalized_input.positions_data,
    )
    return ResolvedContributionRequest(
        contribution_request=contribution_request.model_copy(
            update={"currency": _resolved_stateful_contribution_currency(request, normalized_input)}
        ),
        input_mode=ContributionInputMode.STATEFUL,
        position_count=len(normalized_input.positions_data),
        portfolio_base_currency=_resolved_stateful_portfolio_base_currency(request, normalized_input),
        source_preconverted_reporting_currency=_resolved_stateful_source_reporting_currency(request, normalized_input),
    )


def _resolved_stateful_contribution_currency(
    request: ContributionAnalyticsRequest,
    normalized_input: StatefulContributionNormalizedInput,
) -> str:
    """Keep Core's selected reporting denomination attached to BASE_ONLY economics."""
    return normalized_currency_code(getattr(normalized_input, "valuation_currency", None)) or (
        _resolved_stateful_portfolio_base_currency(request, normalized_input)
    )


def _resolved_stateful_portfolio_base_currency(
    request: ContributionAnalyticsRequest,
    normalized_input: StatefulContributionNormalizedInput,
) -> str:
    return normalized_currency_code(getattr(normalized_input, "portfolio_currency", None)) or request.currency


def _resolved_stateful_source_reporting_currency(
    request: ContributionAnalyticsRequest,
    normalized_input: StatefulContributionNormalizedInput,
) -> str | None:
    portfolio_base_currency = _resolved_stateful_portfolio_base_currency(request, normalized_input)
    valuation_currency = normalized_currency_code(getattr(normalized_input, "valuation_currency", None))
    requested_reporting_currency = normalized_currency_code(request.report_ccy)
    core_reporting_currency = normalized_currency_code(getattr(normalized_input, "reporting_currency", None))
    if (request.currency_mode or "BASE_ONLY") != "BASE_ONLY":
        return None
    if requested_reporting_currency is None:
        return None
    if valuation_currency != portfolio_base_currency:
        return valuation_currency
    if _same_base_currency_has_source_preconverted_cash_flow(
        valuation_currency=valuation_currency,
        source_preconverted_cash_flow_conversion=getattr(
            normalized_input,
            "source_preconverted_cash_flow_conversion",
            False,
        ),
        requested_reporting_currency=requested_reporting_currency,
        core_reporting_currency=core_reporting_currency,
    ):
        # Core selected this same denomination and supplied a consumed foreign-flow conversion.
        # Retain that source provenance instead of hiding the applied pair merely because the
        # portfolio base and reporting currencies happen to be identical.
        return valuation_currency
    return None


def _same_base_currency_has_source_preconverted_cash_flow(
    *,
    valuation_currency: str | None,
    source_preconverted_cash_flow_conversion: bool,
    requested_reporting_currency: str,
    core_reporting_currency: str | None,
) -> bool:
    return (
        valuation_currency is not None
        and source_preconverted_cash_flow_conversion
        and requested_reporting_currency == valuation_currency
        and core_reporting_currency == valuation_currency
    )


def _resolved_stateless_contribution_request(
    request: ContributionAnalyticsRequest,
) -> ResolvedContributionRequest:
    contribution_request = request.to_stateless_contribution_request()
    return ResolvedContributionRequest(
        contribution_request=contribution_request,
        input_mode=ContributionInputMode.STATELESS,
        position_count=len(contribution_request.positions_data),
    )


def _contribution_retrieval_stage_details(source_input: StatefulContributionSourceInput) -> dict[str, int]:
    portfolio_metadata = _portfolio_retrieval_metadata(source_input)
    position_metadata = _position_retrieval_metadata(source_input)
    return {
        "portfolio_observations": len(source_input.portfolio_input.observations),
        "position_rows": len(source_input.position_rows),
        "portfolio_chunk_count": portfolio_metadata.chunk_count,
        "portfolio_page_count": portfolio_metadata.page_count,
        "position_chunk_count": position_metadata.chunk_count,
        "position_page_count": position_metadata.page_count,
    }


def _contribution_normalization_stage_details(
    normalized_input: StatefulContributionNormalizedInput,
) -> dict[str, int]:
    return {
        "portfolio_points": len(normalized_input.portfolio_data.valuation_points),
        "positions": len(normalized_input.positions_data),
    }


def _portfolio_retrieval_metadata(source_input: object) -> RetrievalMetadata:
    portfolio_input = getattr(source_input, "portfolio_input", None)
    metadata = getattr(portfolio_input, "retrieval_metadata", None)
    if isinstance(metadata, RetrievalMetadata):
        return metadata
    return RetrievalMetadata(chunk_count=1, page_count=1)


def _position_retrieval_metadata(source_input: object) -> RetrievalMetadata:
    metadata = getattr(source_input, "position_retrieval_metadata", None)
    if isinstance(metadata, RetrievalMetadata):
        return metadata
    return RetrievalMetadata(chunk_count=1, page_count=1)
