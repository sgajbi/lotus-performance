from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest

from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_input_service import StatefulInputService

STATEFUL_PORTFOLIO_WINDOW_START = date(2024, 1, 1)
STATEFUL_PORTFOLIO_WINDOW_END = date(2033, 12, 31)
STATEFUL_PORTFOLIO_MEDIAN_MS_BUDGET = 250.0


class _StatefulCoreServiceStub:
    async def get_portfolio_analytics_timeseries(self, **kwargs):
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        page_token = kwargs.get("page_token")
        midpoint = start_date + (end_date - start_date) / 2
        if page_token is None:
            return 200, {
                "portfolio_open_date": "2024-01-01",
                "observations": _build_observations(start_date=start_date, end_date=midpoint, ending_market_value="101"),
                "page": {"next_page_token": "page-2"},
            }
        return 200, {
            "portfolio_open_date": "2024-01-01",
            "observations": _build_observations(
                start_date=midpoint + timedelta(days=1),
                end_date=end_date,
                ending_market_value="102",
            ),
        }

    async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
        return 200, {"benchmark_id": "BMK-CHAR"}

    async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
        return 200, {"points": []}

    async def get_risk_free_series(self, **kwargs):  # noqa: ARG002
        return 200, {"points": []}


def _build_observations(*, start_date: date, end_date: date, ending_market_value: str) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    cursor = start_date
    while cursor <= end_date:
        observations.append(
            {
                "valuation_date": cursor.isoformat(),
                "beginning_market_value": "100",
                "ending_market_value": ending_market_value,
            }
        )
        cursor += timedelta(days=1)
    return observations


@pytest.mark.asyncio
async def test_stateful_portfolio_timeseries_characterization_contract(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PF-CHAR",
        execution_mode="sync",
        requested_window={"mode": "EXPLICIT"},
    )
    service = StatefulInputService(
        core_service=_StatefulCoreServiceStub(),
        execution_store=execution_store,
        portfolio_chunk_days=90,
        reference_chunk_days=365,
        max_concurrent_chunks=4,
    )

    await service.get_portfolio_timeseries(
        portfolio_id="PF-CHAR",
        as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
        start_date=STATEFUL_PORTFOLIO_WINDOW_START,
        end_date=STATEFUL_PORTFOLIO_WINDOW_END,
        reporting_currency="USD",
        consumer_system="lotus-performance",
        calculation_id=calculation_id,
    )

    timings = []
    for _ in range(5):
        start = perf_counter()
        status_code, payload = await service.get_portfolio_timeseries(
            portfolio_id="PF-CHAR",
            as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
            start_date=STATEFUL_PORTFOLIO_WINDOW_START,
            end_date=STATEFUL_PORTFOLIO_WINDOW_END,
            reporting_currency="USD",
            consumer_system="lotus-performance",
            calculation_id=calculation_id,
        )
        timings.append((perf_counter() - start) * 1000)

    assert status_code == 200
    assert payload["portfolio_open_date"] == "2024-01-01"
    assert len(payload["observations"]) == (STATEFUL_PORTFOLIO_WINDOW_END - STATEFUL_PORTFOLIO_WINDOW_START).days + 1
    assert len(execution_store.list_upstream_snapshots(calculation_id)) > 0

    median_ms = median(timings)
    assert median_ms <= STATEFUL_PORTFOLIO_MEDIAN_MS_BUDGET, (
        f"Stateful portfolio retrieval median {median_ms:.2f}ms exceeded "
        f"budget {STATEFUL_PORTFOLIO_MEDIAN_MS_BUDGET:.2f}ms "
        f"for window {STATEFUL_PORTFOLIO_WINDOW_START}..{STATEFUL_PORTFOLIO_WINDOW_END}."
    )
