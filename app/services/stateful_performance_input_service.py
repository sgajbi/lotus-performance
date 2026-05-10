from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import Settings
from app.services.portfolio_source_service import (
    fetch_stateful_portfolio_timeseries,
    parse_stateful_portfolio_timeseries_payload,
)
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_upstream_errors import stateful_control_plane_unavailable_detail
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points


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
    if stateful_input_service is None:
        upstream_status, upstream_payload = await fetch_stateful_portfolio_timeseries(
            settings=settings,
            calculation_id=calculation_id,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
        )
    else:
        upstream_status, upstream_payload = await stateful_input_service.get_portfolio_timeseries(
            calculation_id=calculation_id,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
        )
    if upstream_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=stateful_control_plane_unavailable_detail(
                source_label="stateful portfolio timeseries source",
                upstream_status=upstream_status,
            ),
        )

    try:
        portfolio_source = parse_stateful_portfolio_timeseries_payload(
            upstream_payload,
            require_open_date=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not portfolio_source.observations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stateful source returned no observations.",
        )

    try:
        performance_start_date = date.fromisoformat(portfolio_source.portfolio_open_date or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid portfolio_open_date from stateful source.",
        ) from exc

    return StatefulPortfolioInput(
        performance_start_date=performance_start_date,
        observations=portfolio_source.observations,
        portfolio_currency=portfolio_source.portfolio_currency,
        reporting_currency=portfolio_source.reporting_currency,
        retrieval_metadata=_parse_retrieval_metadata(upstream_payload),
    )


def build_stateful_portfolio_valuation_input(
    source_input: StatefulPortfolioInput,
) -> StatefulPortfolioValuationInput:
    valuation_points = portfolio_timeseries_to_valuation_points(observations=source_input.observations)
    return StatefulPortfolioValuationInput(
        performance_start_date=source_input.performance_start_date,
        observations=source_input.observations,
        valuation_points=valuation_points,
    )


def _parse_retrieval_metadata(payload: dict[str, object]) -> RetrievalMetadata:
    metadata_raw = payload.get("retrieval_metadata")
    if not isinstance(metadata_raw, dict):
        return RetrievalMetadata(chunk_count=1, page_count=1)
    chunk_count = metadata_raw.get("chunk_count")
    page_count = metadata_raw.get("page_count")
    return RetrievalMetadata(
        chunk_count=int(chunk_count) if isinstance(chunk_count, int) and chunk_count > 0 else 1,
        page_count=int(page_count) if isinstance(page_count, int) and page_count > 0 else 1,
    )
