from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import pytest

from app.services.stateful_input_service import (
    DateChunk,
    StatefulInputService,
    _position_timeseries_request_payload,
)


class _PositionCoreServiceStub:
    def __init__(self) -> None:
        self.position_calls: list[dict[str, Any]] = []

    async def get_position_analytics_timeseries(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.position_calls.append(kwargs)
        return (
            200,
            {
                "rows": [
                    {
                        "valuation_date": "2026-01-02",
                        "position_id": "POS_1",
                        "market_value": "101.00",
                    }
                ]
            },
        )


@pytest.mark.asyncio
async def test_stateful_contribution_position_page_records_source_lineage_snapshot():
    core_service = _PositionCoreServiceStub()
    service = StatefulInputService(core_service=core_service)
    calculation_id = UUID("00000000-0000-0000-0000-000000000001")
    chunk = DateChunk(start_date=date(2026, 1, 1), end_date=date(2026, 1, 3))
    snapshot_batch: list[dict[str, Any]] = []
    existing_snapshot_ids: set[str] = set()

    page_result = await service._fetch_and_record_position_page(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        chunk=chunk,
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["sector"],
        include_cash_flows=True,
        filters={"asset_class": "Equity"},
        page_token="page-2",
        calculation_id=calculation_id,
        snapshot_batch=snapshot_batch,
        existing_snapshot_ids=existing_snapshot_ids,
    )

    expected_request_payload = _position_timeseries_request_payload(
        portfolio_id="PORT_1",
        chunk=chunk,
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["sector"],
        include_cash_flows=True,
        filters={"asset_class": "Equity"},
        page_token="page-2",
    )
    assert page_result.status_code == 200
    assert page_result.payload["rows"][0]["valuation_date"] == "2026-01-02"
    assert core_service.position_calls[-1]["page_token"] == "page-2"
    assert len(snapshot_batch) == 1
    assert snapshot_batch[0]["upstream_endpoint"] == "position_timeseries"
    assert snapshot_batch[0]["source_identifier"] == "PORT_1"
    assert snapshot_batch[0]["paging_metadata"] == expected_request_payload
    assert len(existing_snapshot_ids) == 1
