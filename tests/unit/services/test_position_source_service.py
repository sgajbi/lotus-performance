from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.services.position_source_service import (
    fetch_stateful_position_timeseries,
    parse_stateful_position_timeseries_payload,
)


@pytest.mark.asyncio
async def test_fetch_stateful_position_timeseries_delegates_to_shared_input_service(monkeypatch):
    calls: list[dict] = []

    class _StubService:
        async def get_position_timeseries(self, **kwargs):
            calls.append(kwargs)
            return 200, {"rows": []}

    monkeypatch.setattr(
        "app.services.position_source_service.build_stateful_input_service",
        lambda settings: _StubService(),
    )

    status_code, payload = await fetch_stateful_position_timeseries(
        settings=object(),
        calculation_id=uuid4(),
        portfolio_id="P1",
        as_of_date=date(2025, 1, 31),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["sector"],
        include_cash_flows=False,
        filters={"security_ids": ["SEC_1"]},
    )

    assert status_code == 200
    assert payload == {"rows": []}
    assert calls[0]["dimensions"] == ["sector"]
    assert calls[0]["include_cash_flows"] is False


def test_parse_stateful_position_timeseries_payload_filters_non_dict_rows():
    parsed = parse_stateful_position_timeseries_payload({"rows": [{"position_id": "POS_1"}, "bad"]})
    assert parsed.rows == [{"position_id": "POS_1"}]
