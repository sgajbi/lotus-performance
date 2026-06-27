from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from fastapi import HTTPException

from app.core.config import Settings
from app.models.source_quality import PerformanceSourceQualityEvidence
from app.services.portfolio_source_service import (
    fetch_stateful_portfolio_timeseries,
    parse_stateful_portfolio_timeseries_payload,
)
from app.services.source_quality_evidence import build_portfolio_source_quality_evidence
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_retrieval_metadata import parse_retrieval_metadata
from app.services.stateful_upstream_errors import raise_for_stateful_control_plane_unavailable
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points
from core.errors import HTTP_422_UNPROCESSABLE


@dataclass(frozen=True)
class StatefulPortfolioInput:
    performance_start_date: date
    observations: list[dict[str, object]]
    portfolio_currency: str | None = None
    reporting_currency: str | None = None
    retrieval_metadata: RetrievalMetadata = field(
        default_factory=lambda: RetrievalMetadata(chunk_count=1, page_count=1)
    )


@dataclass(frozen=True)
class StatefulPortfolioValuationInput:
    performance_start_date: date
    observations: list[dict[str, object]]
    valuation_points: list[dict[str, object]]
    source_quality_evidence: PerformanceSourceQualityEvidence


async def retrieve_stateful_portfolio_input(
    *,
    settings: Settings,
    stateful_input_service: StatefulInputService | None = None,
    calculation_id: UUID | None,
    portfolio_id: str,
    as_of_date: date,
    start_date: date,
    end_date: date,
    reporting_currency: str | None,
    consumer_system: str,
) -> StatefulPortfolioInput:
    upstream_status, upstream_payload = await _retrieve_portfolio_timeseries_response(
        settings=settings,
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        start_date=start_date,
        end_date=end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
    )
    raise_for_stateful_control_plane_unavailable(
        source_label="stateful portfolio timeseries source",
        upstream_status=upstream_status,
    )
    return _stateful_portfolio_input_from_payload(upstream_payload)


def _stateful_portfolio_input_from_payload(upstream_payload: dict[str, object]) -> StatefulPortfolioInput:
    try:
        portfolio_source = parse_stateful_portfolio_timeseries_payload(
            upstream_payload,
            require_open_date=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=str(exc),
        ) from exc

    if not portfolio_source.observations:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="Stateful source returned no observations.",
        )

    try:
        performance_start_date = date.fromisoformat(portfolio_source.portfolio_open_date or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="Invalid portfolio_open_date from stateful source.",
        ) from exc

    return StatefulPortfolioInput(
        performance_start_date=performance_start_date,
        observations=portfolio_source.observations,
        portfolio_currency=portfolio_source.portfolio_currency,
        reporting_currency=portfolio_source.reporting_currency,
        retrieval_metadata=parse_retrieval_metadata(upstream_payload),
    )


async def _retrieve_portfolio_timeseries_response(
    *,
    settings: Settings,
    stateful_input_service: StatefulInputService | None,
    calculation_id: UUID | None,
    portfolio_id: str,
    as_of_date: date,
    start_date: date,
    end_date: date,
    reporting_currency: str | None,
    consumer_system: str,
) -> tuple[int, dict[str, object]]:
    if stateful_input_service is None:
        return await fetch_stateful_portfolio_timeseries(
            settings=settings,
            calculation_id=calculation_id,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
        )
    return await stateful_input_service.get_portfolio_timeseries(
        calculation_id=calculation_id,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        start_date=start_date,
        end_date=end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
    )


def build_stateful_portfolio_valuation_input(
    *,
    source_input: StatefulPortfolioInput,
    report_end_date: date,
) -> StatefulPortfolioValuationInput:
    valuation_points = portfolio_timeseries_to_valuation_points(observations=source_input.observations)
    return StatefulPortfolioValuationInput(
        performance_start_date=source_input.performance_start_date,
        observations=source_input.observations,
        valuation_points=valuation_points,
        source_quality_evidence=build_portfolio_source_quality_evidence(
            observations=source_input.observations,
            valid_valuation_point_count=len(valuation_points),
            report_end_date=report_end_date,
            input_mode="stateful",
            source_owner="lotus-core",
            source_product="PortfolioTimeseriesInput",
        ),
    )
