from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_input_service import StatefulInputService


class _CoreServiceStub:
    def __init__(self) -> None:
        self.portfolio_calls: list[dict] = []
        self.benchmark_calls: list[dict] = []
        self.risk_free_calls: list[dict] = []

    async def get_portfolio_analytics_timeseries(self, **kwargs):
        self.portfolio_calls.append(kwargs)
        page_token = kwargs.get("page_token")
        start_date = kwargs["start_date"]
        if start_date == date(2026, 1, 1) and page_token is None:
            return (
                200,
                {
                    "portfolio_open_date": "2025-12-31",
                    "observations": [
                        {
                            "valuation_date": "2026-01-01",
                            "beginning_market_value": "100",
                            "ending_market_value": "101",
                        }
                    ],
                    "page": {"next_page_token": "page-2"},
                },
            )
        if start_date == date(2026, 1, 1) and page_token == "page-2":
            return (
                200,
                {
                    "portfolio_open_date": "2025-12-31",
                    "observations": [
                        {
                            "valuation_date": "2026-01-02",
                            "beginning_market_value": "101",
                            "ending_market_value": "102",
                        }
                    ],
                },
            )
        return (
            200,
            {
                "portfolio_open_date": "2025-12-31",
                "observations": [
                    {
                        "valuation_date": "2026-01-03",
                        "beginning_market_value": "102",
                        "ending_market_value": "103",
                    },
                    {
                        "valuation_date": "2026-01-03",
                        "beginning_market_value": "102",
                        "ending_market_value": "103",
                    },
                ],
            },
        )

    async def get_benchmark_assignment(self, **kwargs):
        return 200, {"benchmark_id": "BMK_1"}

    async def get_benchmark_return_series(self, **kwargs):
        self.benchmark_calls.append(kwargs)
        return (
            200,
            {
                "points": [
                    {"series_date": str(kwargs["start_date"]), "benchmark_return": "0.0010"},
                    {"series_date": str(kwargs["end_date"]), "benchmark_return": "0.0020"},
                ]
            },
        )

    async def get_risk_free_series(self, **kwargs):
        self.risk_free_calls.append(kwargs)
        return (
            200,
            {
                "points": [
                    {"series_date": str(kwargs["start_date"]), "value": "0.0001"},
                    {"series_date": str(kwargs["end_date"]), "value": "0.0002"},
                ]
            },
        )


def test_plan_chunks_splits_window_deterministically():
    service = StatefulInputService(core_service=_CoreServiceStub(), portfolio_chunk_days=3)
    chunks = service.plan_chunks(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        chunk_days=3,
    )
    assert [(chunk.start_date, chunk.end_date) for chunk in chunks] == [
        (date(2026, 1, 1), date(2026, 1, 3)),
        (date(2026, 1, 4), date(2026, 1, 6)),
        (date(2026, 1, 7), date(2026, 1, 7)),
    ]


@pytest.mark.asyncio
async def test_get_portfolio_timeseries_merges_chunked_and_paginated_observations():
    core_service = _CoreServiceStub()
    service = StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=2,
        reference_chunk_days=10,
        max_concurrent_chunks=2,
    )

    status_code, payload = await service.get_portfolio_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
    )

    assert status_code == 200
    assert payload["portfolio_open_date"] == "2025-12-31"
    assert [item["valuation_date"] for item in payload["observations"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert len(core_service.portfolio_calls) == 3


@pytest.mark.asyncio
async def test_reference_series_merge_chunked_points():
    core_service = _CoreServiceStub()
    service = StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=10,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    benchmark_status, benchmark_payload = await service.get_benchmark_return_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )
    risk_free_status, risk_free_payload = await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )

    assert benchmark_status == 200
    assert risk_free_status == 200
    assert [point["series_date"] for point in benchmark_payload["points"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
    ]
    assert [point["series_date"] for point in risk_free_payload["points"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
    ]


@pytest.mark.asyncio
async def test_stateful_input_service_records_upstream_snapshots(tmp_path):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        portfolio_chunk_days=2,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    await service.get_portfolio_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        calculation_id=calculation_id,
    )
    await service.get_benchmark_return_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    snapshots = execution_store.list_upstream_snapshots(calculation_id)

    assert len(snapshots) >= 5
    assert {snapshot.upstream_endpoint for snapshot in snapshots} >= {
        "portfolio_timeseries",
        "benchmark_return_series",
    }
