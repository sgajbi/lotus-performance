from __future__ import annotations

from datetime import date
from typing import Literal, Protocol, TypedDict
from uuid import UUID

from app.core.config import Settings
from app.models.requests import PerformanceRequest
from app.services.inspection.source_availability import raise_inspection_source_unavailable

_INSPECTOR_CONSUMER_SYSTEM = "lotus-performance-inspector"


class _StatefulTimeseriesService(Protocol):
    async def get_portfolio_timeseries(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        calculation_id: UUID | None,
    ) -> tuple[int, dict[str, object]]: ...

    async def get_position_timeseries(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        calculation_id: UUID | None,
    ) -> tuple[int, dict[str, object]]: ...


class StatefulTimeseriesServiceFactory(Protocol):
    def __call__(self, *, settings: Settings) -> _StatefulTimeseriesService: ...


class _TimeseriesRequestArgs(TypedDict):
    portfolio_id: str
    as_of_date: date
    start_date: date
    end_date: date
    reporting_currency: str | None
    consumer_system: str
    calculation_id: UUID | None


TimeseriesKind = Literal["portfolio", "position"]


async def fetch_inspection_stateful_timeseries(
    *,
    performance_request: PerformanceRequest,
    portfolio_id: str,
    settings: Settings,
    service_factory: StatefulTimeseriesServiceFactory,
    timeseries_kind: TimeseriesKind,
    source_label: str,
    inspection_label: str,
) -> dict[str, object]:
    stateful_input_service = service_factory(settings=settings)
    request_args: _TimeseriesRequestArgs = {
        "portfolio_id": portfolio_id,
        "as_of_date": performance_request.report_end_date,
        "start_date": performance_request.performance_start_date,
        "end_date": performance_request.report_end_date,
        "reporting_currency": performance_request.report_ccy,
        "consumer_system": _INSPECTOR_CONSUMER_SYSTEM,
        "calculation_id": None,
    }
    if timeseries_kind == "portfolio":
        status_code, payload = await stateful_input_service.get_portfolio_timeseries(**request_args)
    else:
        status_code, payload = await stateful_input_service.get_position_timeseries(**request_args)

    if status_code >= 400:
        raise_inspection_source_unavailable(
            source_label=source_label,
            inspection_label=inspection_label,
            status_code=status_code,
        )
    return payload
