from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.position_source_service import (
    StatefulPositionTimeseries,
    fetch_stateful_position_timeseries,
    parse_stateful_position_timeseries_payload,
)


class _PositionTimeseriesServiceStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def get_position_timeseries(self, **kwargs):
        self.calls.append(kwargs)
        return 200, {"rows": [{"portfolio_id": kwargs["portfolio_id"], "valuation_date": "2026-01-02"}]}


@pytest.mark.asyncio
async def test_fetch_stateful_position_timeseries_forwards_request_shape(monkeypatch: pytest.MonkeyPatch):
    stub = _PositionTimeseriesServiceStub()

    def _build_stateful_input_service(*, settings: Settings):
        assert settings.CORE_QUERY_BASE_URL == "http://core-query.dev.lotus"
        return stub

    monkeypatch.setattr(
        "app.services.position_source_service.build_stateful_input_service",
        _build_stateful_input_service,
    )

    calculation_id = uuid4()
    status_code, payload = await fetch_stateful_position_timeseries(
        settings=Settings(),
        calculation_id=calculation_id,
        portfolio_id="PORT-1",
        as_of_date=date(2026, 1, 10),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 5),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["instrument_id", "sector"],
        include_cash_flows=False,
        filters={"instrument_id": ["ABC"]},
    )

    assert status_code == 200
    assert payload["rows"][0]["portfolio_id"] == "PORT-1"
    assert stub.calls == [
        {
            "portfolio_id": "PORT-1",
            "as_of_date": date(2026, 1, 10),
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 5),
            "reporting_currency": "USD",
            "consumer_system": "lotus-performance",
            "dimensions": ["instrument_id", "sector"],
            "include_cash_flows": False,
            "filters": {"instrument_id": ["ABC"]},
            "calculation_id": calculation_id,
        }
    ]


def test_parse_stateful_position_timeseries_payload_filters_non_mapping_rows():
    parsed = parse_stateful_position_timeseries_payload(
        {
            "rows": [
                {"instrument_id": "ABC", "valuation_date": "2026-01-02"},
                "skip-me",
                123,
                {"instrument_id": "XYZ", "valuation_date": "2026-01-03"},
            ]
        }
    )

    assert parsed == StatefulPositionTimeseries(
        rows=[
            {"instrument_id": "ABC", "valuation_date": "2026-01-02"},
            {"instrument_id": "XYZ", "valuation_date": "2026-01-03"},
        ]
    )


def test_parse_stateful_position_timeseries_payload_defaults_missing_rows_to_empty():
    assert parse_stateful_position_timeseries_payload({}) == StatefulPositionTimeseries(rows=[])
    assert parse_stateful_position_timeseries_payload({"rows": "not-a-list"}) == StatefulPositionTimeseries(rows=[])
