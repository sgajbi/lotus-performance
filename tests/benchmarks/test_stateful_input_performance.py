from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateful_input_service import StatefulInputService

STATEFUL_PORTFOLIO_WINDOW_START = date(2024, 1, 1)
STATEFUL_PORTFOLIO_WINDOW_END = date(2033, 12, 31)
STATEFUL_PORTFOLIO_MEDIAN_MS_BUDGET = 250.0
STATEFUL_REFERENCE_MEDIAN_MS_BUDGET = 25.0
STATEFUL_CALCULATED_BENCHMARK_MEDIAN_MS_BUDGET = 2800.0


class _StatefulCoreServiceStub:
    async def get_portfolio_analytics_timeseries(self, **kwargs):
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        page_token = kwargs.get("page_token")
        midpoint = start_date + (end_date - start_date) / 2
        if page_token is None:
            return 200, {
                "portfolio_open_date": "2024-01-01",
                "observations": _build_observations(
                    start_date=start_date, end_date=midpoint, ending_market_value="101"
                ),
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
        return 200, {
            "points": _build_reference_points(
                start_date=kwargs["start_date"],
                end_date=kwargs["end_date"],
                value_key="benchmark_return",
                value="0.0010",
            )
        }

    async def get_risk_free_series(self, **kwargs):  # noqa: ARG002
        return 200, {
            "points": _build_reference_points(
                start_date=kwargs["start_date"],
                end_date=kwargs["end_date"],
                value_key="value",
                value="0.0001",
            )
        }


class _StatefulBenchmarkCoreServiceStub(_StatefulCoreServiceStub):
    async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
        midpoint = (
            STATEFUL_PORTFOLIO_WINDOW_START + (STATEFUL_PORTFOLIO_WINDOW_END - STATEFUL_PORTFOLIO_WINDOW_START) / 2
        )
        segments: list[dict[str, str]] = []
        segment_definitions = [
            ("IDX_USD", "0.40", "0.35"),
            ("IDX_EUR", "0.30", "0.30"),
            ("IDX_GBP", "0.20", "0.20"),
            ("IDX_JPY", "0.10", "0.15"),
        ]
        for index_id, weight_first, weight_second in segment_definitions:
            segments.append(
                {
                    "index_id": index_id,
                    "composition_weight": weight_first,
                    "composition_effective_from": STATEFUL_PORTFOLIO_WINDOW_START.isoformat(),
                    "composition_effective_to": midpoint.isoformat(),
                }
            )
            segments.append(
                {
                    "index_id": index_id,
                    "composition_weight": weight_second,
                    "composition_effective_from": (midpoint + timedelta(days=1)).isoformat(),
                    "composition_effective_to": STATEFUL_PORTFOLIO_WINDOW_END.isoformat(),
                }
            )
        return 200, {
            "benchmark_id": kwargs["benchmark_id"],
            "benchmark_currency": "USD",
            "segments": segments,
        }

    async def get_index_price_series(self, **kwargs):  # noqa: ARG002
        index_id = kwargs["index_id"]
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        series_currency = {
            "IDX_USD": "USD",
            "IDX_EUR": "EUR",
            "IDX_GBP": "GBP",
            "IDX_JPY": "JPY",
        }[index_id]
        daily_step = {
            "IDX_USD": 0.0003,
            "IDX_EUR": 0.00025,
            "IDX_GBP": 0.0002,
            "IDX_JPY": 0.00015,
        }[index_id]
        base_price = {
            "IDX_USD": 100.0,
            "IDX_EUR": 95.0,
            "IDX_GBP": 110.0,
            "IDX_JPY": 9800.0,
        }[index_id]
        points: list[dict[str, str]] = []
        cursor = start_date
        day_index = 0
        while cursor <= end_date:
            points.append(
                {
                    "series_date": cursor.isoformat(),
                    "index_price": f"{base_price * ((1 + daily_step) ** day_index):.10f}",
                    "series_currency": series_currency,
                }
            )
            cursor += timedelta(days=1)
            day_index += 1
        return 200, {"points": points}

    async def get_fx_rates(self, **kwargs):  # noqa: ARG002
        from_currency = kwargs["from_currency"]
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        base_rate = {
            "EUR": 1.10,
            "GBP": 1.28,
            "JPY": 0.0092,
        }[from_currency]
        daily_step = {
            "EUR": 0.00005,
            "GBP": 0.00004,
            "JPY": 0.00003,
        }[from_currency]
        rates: list[dict[str, str]] = []
        cursor = start_date
        day_index = 0
        while cursor <= end_date:
            rates.append(
                {
                    "rate_date": cursor.isoformat(),
                    "rate": f"{base_rate * ((1 + daily_step) ** day_index):.10f}",
                }
            )
            cursor += timedelta(days=1)
            day_index += 1
        return 200, {"rates": rates}


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


def _build_reference_points(
    *,
    start_date: date,
    end_date: date,
    value_key: str,
    value: str,
) -> list[dict[str, str]]:
    points: list[dict[str, str]] = []
    cursor = start_date
    while cursor <= end_date:
        points.append(
            {
                "series_date": cursor.isoformat(),
                value_key: value,
            }
        )
        cursor += timedelta(days=1)
    return points


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


@pytest.mark.asyncio
async def test_stateful_benchmark_reference_characterization_contract(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'benchmark-execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PF-BMK-CHAR",
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

    await service.get_benchmark_return_series(
        benchmark_id="BMK-CHAR",
        as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
        start_date=STATEFUL_PORTFOLIO_WINDOW_START,
        end_date=STATEFUL_PORTFOLIO_WINDOW_END,
        calculation_id=calculation_id,
    )

    timings = []
    for _ in range(5):
        start = perf_counter()
        status_code, payload = await service.get_benchmark_return_series(
            benchmark_id="BMK-CHAR",
            as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
            start_date=STATEFUL_PORTFOLIO_WINDOW_START,
            end_date=STATEFUL_PORTFOLIO_WINDOW_END,
            calculation_id=calculation_id,
        )
        timings.append((perf_counter() - start) * 1000)

    assert status_code == 200
    assert len(payload["points"]) == (STATEFUL_PORTFOLIO_WINDOW_END - STATEFUL_PORTFOLIO_WINDOW_START).days + 1
    median_ms = median(timings)
    assert median_ms <= STATEFUL_REFERENCE_MEDIAN_MS_BUDGET, (
        f"Stateful benchmark retrieval median {median_ms:.2f}ms exceeded "
        f"budget {STATEFUL_REFERENCE_MEDIAN_MS_BUDGET:.2f}ms."
    )


@pytest.mark.asyncio
async def test_stateful_risk_free_reference_characterization_contract(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'riskfree-execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PF-RF-CHAR",
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

    await service.get_risk_free_series(
        currency="USD",
        as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
        start_date=STATEFUL_PORTFOLIO_WINDOW_START,
        end_date=STATEFUL_PORTFOLIO_WINDOW_END,
        calculation_id=calculation_id,
    )

    timings = []
    for _ in range(5):
        start = perf_counter()
        status_code, payload = await service.get_risk_free_series(
            currency="USD",
            as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
            start_date=STATEFUL_PORTFOLIO_WINDOW_START,
            end_date=STATEFUL_PORTFOLIO_WINDOW_END,
            calculation_id=calculation_id,
        )
        timings.append((perf_counter() - start) * 1000)

    assert status_code == 200
    assert len(payload["points"]) == (STATEFUL_PORTFOLIO_WINDOW_END - STATEFUL_PORTFOLIO_WINDOW_START).days + 1
    median_ms = median(timings)
    assert median_ms <= STATEFUL_REFERENCE_MEDIAN_MS_BUDGET, (
        f"Stateful risk-free retrieval median {median_ms:.2f}ms exceeded "
        f"budget {STATEFUL_REFERENCE_MEDIAN_MS_BUDGET:.2f}ms."
    )


@pytest.mark.asyncio
async def test_stateful_calculated_benchmark_characterization_contract(tmp_path):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'benchmark-calculated-execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BENCHMARK",
        portfolio_id="BMK-CHAR",
        execution_mode="sync",
        requested_window={"mode": "EXPLICIT"},
    )
    service = StatefulInputService(
        core_service=_StatefulBenchmarkCoreServiceStub(),
        execution_store=execution_store,
        portfolio_chunk_days=90,
        reference_chunk_days=365,
        max_concurrent_chunks=4,
    )

    await build_stateful_benchmark_input(
        stateful_input_service=service,
        calculation_id=calculation_id,
        benchmark_id="BMK-CHAR",
        as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
        start_date=STATEFUL_PORTFOLIO_WINDOW_START,
        end_date=STATEFUL_PORTFOLIO_WINDOW_END,
        return_source=BenchmarkReturnSource.CALCULATED,
    )

    timings = []
    for _ in range(5):
        start = perf_counter()
        normalized_input = await build_stateful_benchmark_input(
            stateful_input_service=service,
            calculation_id=calculation_id,
            benchmark_id="BMK-CHAR",
            as_of_date=STATEFUL_PORTFOLIO_WINDOW_END,
            start_date=STATEFUL_PORTFOLIO_WINDOW_START,
            end_date=STATEFUL_PORTFOLIO_WINDOW_END,
            return_source=BenchmarkReturnSource.CALCULATED,
        )
        timings.append((perf_counter() - start) * 1000)

    expected_days = (STATEFUL_PORTFOLIO_WINDOW_END - STATEFUL_PORTFOLIO_WINDOW_START).days + 1
    assert normalized_input.benchmark_currency == "USD"
    assert len(normalized_input.component_observations) == expected_days * 4
    assert normalized_input.source_details["benchmark_components"] == 4
    assert normalized_input.source_details["benchmark_segments"] == 8
    assert normalized_input.source_details["fx_pair_count"] == 3
    assert normalized_input.source_details["component_observations"] == expected_days * 4
    assert len(execution_store.list_upstream_snapshots(calculation_id)) > 0

    median_ms = median(timings)
    assert median_ms <= STATEFUL_CALCULATED_BENCHMARK_MEDIAN_MS_BUDGET, (
        f"Stateful calculated benchmark normalization median {median_ms:.2f}ms exceeded "
        f"budget {STATEFUL_CALCULATED_BENCHMARK_MEDIAN_MS_BUDGET:.2f}ms "
        f"for window {STATEFUL_PORTFOLIO_WINDOW_START}..{STATEFUL_PORTFOLIO_WINDOW_END}."
    )
