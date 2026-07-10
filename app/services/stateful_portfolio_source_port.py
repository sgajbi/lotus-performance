from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from app.services.core_integration_service import CoreIntegrationService


class StatefulPortfolioSourcePort(Protocol):
    async def fetch_reference(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
    ) -> tuple[int, dict[str, Any]]:
        """Fetch the point-in-time portfolio reference payload from the governed source."""

    async def fetch_timeseries_page(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        page_token: str | None,
    ) -> tuple[int, dict[str, Any]]:
        """Fetch one portfolio timeseries page for a bounded date window."""


class CoreStatefulPortfolioSourceAdapter:
    def __init__(self, *, core_service: CoreIntegrationService) -> None:
        self._core_service = core_service

    async def fetch_reference(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
    ) -> tuple[int, dict[str, Any]]:
        return await self._core_service.get_portfolio_analytics_reference(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )

    async def fetch_timeseries_page(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        page_token: str | None,
    ) -> tuple[int, dict[str, Any]]:
        return await self._core_service.get_portfolio_analytics_timeseries(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
            page_token=page_token,
        )
