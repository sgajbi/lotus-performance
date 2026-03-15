from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.services.portfolio_source_service import build_stateful_input_service


@dataclass(frozen=True)
class StatefulPositionTimeseries:
    rows: list[dict[str, object]]


async def fetch_stateful_position_timeseries(
    *,
    settings: Settings,
    calculation_id: UUID | None,
    portfolio_id: str,
    as_of_date: date,
    start_date: date,
    end_date: date,
    reporting_currency: str | None,
    consumer_system: str,
    dimensions: list[str] | None = None,
    include_cash_flows: bool = True,
    filters: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    stateful_input_service = build_stateful_input_service(settings=settings)
    return await stateful_input_service.get_position_timeseries(
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        start_date=start_date,
        end_date=end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
        dimensions=dimensions,
        include_cash_flows=include_cash_flows,
        filters=filters,
        calculation_id=calculation_id,
    )


def parse_stateful_position_timeseries_payload(payload: dict[str, Any]) -> StatefulPositionTimeseries:
    rows_raw = payload.get("rows")
    rows = [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []
    return StatefulPositionTimeseries(rows=rows)
