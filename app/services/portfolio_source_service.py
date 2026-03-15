from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.services.core_integration_service import CoreIntegrationService
from app.services.stateful_input_service import StatefulInputService


@dataclass(frozen=True)
class StatefulPortfolioTimeseries:
    portfolio_open_date: str | None
    observations: list[dict[str, object]]


def build_stateful_input_service(*, settings: Settings) -> StatefulInputService:
    core_service = CoreIntegrationService(
        base_url=settings.CORE_QUERY_BASE_URL,
        timeout_seconds=settings.CORE_TIMEOUT_SECONDS,
        max_retries=settings.CORE_MAX_RETRIES,
        retry_backoff_seconds=settings.CORE_RETRY_BACKOFF_SECONDS,
    )
    return StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=settings.STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS,
        reference_chunk_days=settings.STATEFUL_INPUT_REFERENCE_CHUNK_DAYS,
        max_concurrent_chunks=settings.STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS,
    )


async def fetch_stateful_portfolio_timeseries(
    *,
    settings: Settings,
    calculation_id: UUID | None,
    portfolio_id: str,
    as_of_date: date,
    start_date: date,
    end_date: date,
    reporting_currency: str | None,
    consumer_system: str,
) -> tuple[int, dict[str, Any]]:
    stateful_input_service = build_stateful_input_service(settings=settings)
    return await stateful_input_service.get_portfolio_timeseries(
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        start_date=start_date,
        end_date=end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
        calculation_id=calculation_id,
    )


def parse_stateful_portfolio_timeseries_payload(
    payload: dict[str, Any],
    *,
    require_open_date: bool,
) -> StatefulPortfolioTimeseries:
    observations_raw = payload.get("observations")
    observations = [
        observation
        for observation in observations_raw
        if isinstance(observation, dict)
    ] if isinstance(observations_raw, list) else []
    portfolio_open_date_raw = payload.get("portfolio_open_date")
    portfolio_open_date = portfolio_open_date_raw if isinstance(portfolio_open_date_raw, str) else None
    if require_open_date and portfolio_open_date is None:
        raise ValueError("Stateful source missing portfolio_open_date.")
    return StatefulPortfolioTimeseries(
        portfolio_open_date=portfolio_open_date,
        observations=observations,
    )
