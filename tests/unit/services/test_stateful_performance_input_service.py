from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.stateful_input_service import StatefulInputService
from app.services.stateful_performance_input_service import (
    _retrieve_portfolio_timeseries_response,
    _stateful_portfolio_input_from_payload,
)
from core.errors import APIError


@pytest.mark.asyncio
async def test_retrieve_portfolio_timeseries_response_uses_default_fetch(monkeypatch):
    calls: list[dict[str, Any]] = []

    async def _fetch_stateful_portfolio_timeseries(**kwargs):
        calls.append(kwargs)
        return 200, {"rows": []}

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _fetch_stateful_portfolio_timeseries,
    )
    calculation_id = uuid4()
    settings = Settings()

    status, payload = await _retrieve_portfolio_timeseries_response(
        settings=settings,
        stateful_input_service=None,
        calculation_id=calculation_id,
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 5),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 5),
        reporting_currency="USD",
        consumer_system="lotus-performance",
    )

    assert (status, payload) == (200, {"rows": []})
    assert len(calls) == 1
    assert calls[0].pop("settings") is settings
    assert calls[0] == {
        "calculation_id": calculation_id,
        "portfolio_id": "PORT_1",
        "as_of_date": date(2026, 1, 5),
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 5),
        "reporting_currency": "USD",
        "consumer_system": "lotus-performance",
    }


@pytest.mark.asyncio
async def test_retrieve_portfolio_timeseries_response_uses_injected_service(monkeypatch):
    default_fetch_called = False

    async def _fetch_stateful_portfolio_timeseries(**kwargs):
        nonlocal default_fetch_called
        default_fetch_called = True
        return 200, {"rows": []}

    class _InjectedStatefulInputService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def get_portfolio_timeseries(self, **kwargs):
            self.calls.append(kwargs)
            return 202, {"detail": "accepted"}

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _fetch_stateful_portfolio_timeseries,
    )
    calculation_id = uuid4()
    injected_service = _InjectedStatefulInputService()

    status, payload = await _retrieve_portfolio_timeseries_response(
        settings=Settings(),
        stateful_input_service=cast(StatefulInputService, injected_service),
        calculation_id=calculation_id,
        portfolio_id="PORT_2",
        as_of_date=date(2026, 2, 5),
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 5),
        reporting_currency=None,
        consumer_system="lotus-performance",
    )

    assert not default_fetch_called
    assert (status, payload) == (202, {"detail": "accepted"})
    assert injected_service.calls == [
        {
            "calculation_id": calculation_id,
            "portfolio_id": "PORT_2",
            "as_of_date": date(2026, 2, 5),
            "start_date": date(2026, 2, 1),
            "end_date": date(2026, 2, 5),
            "reporting_currency": None,
            "consumer_system": "lotus-performance",
        }
    ]


def test_stateful_portfolio_input_from_payload_projects_source_identity_and_retrieval_metadata():
    source_input = _stateful_portfolio_input_from_payload(
        {
            "portfolio_open_date": "2026-01-15",
            "portfolio_currency": "USD",
            "reporting_currency": "CHF",
            "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
            "observations": [
                {"valuation_date": "2026-01-15", "market_value": 100},
                "invalid-observation",
            ],
        }
    )

    assert source_input.performance_start_date == date(2026, 1, 15)
    assert source_input.portfolio_currency == "USD"
    assert source_input.reporting_currency == "CHF"
    assert source_input.observations == [{"valuation_date": "2026-01-15", "market_value": 100}]
    assert source_input.retrieval_metadata.chunk_count == 2
    assert source_input.retrieval_metadata.page_count == 3


def test_stateful_portfolio_input_from_payload_maps_invalid_source_contract_to_422():
    with pytest.raises(APIError) as exc:
        _stateful_portfolio_input_from_payload(
            {
                "portfolio_open_date": "bad-date",
                "observations": [{"valuation_date": "2026-01-15", "market_value": 100}],
            }
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Invalid portfolio_open_date from stateful source."
