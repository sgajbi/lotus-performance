from statistics import median
from time import perf_counter
from uuid import uuid4

import pandas as pd
import pytest

import app.services.portfolio_source_service as portfolio_source_service
import app.services.returns_series_service as returns_series_service
import app.services.stateful_input_service as stateful_input_service
from app.models.returns_series import ReturnsSeriesRequest
from app.services.execution_registry import ExecutionRegistry
from tests.benchmarks.test_stateful_input_performance import (
    STATEFUL_PORTFOLIO_WINDOW_END,
    STATEFUL_PORTFOLIO_WINDOW_START,
    _StatefulBenchmarkCoreServiceStub,
)

RETURNS_SERIES_ORCHESTRATION_MEDIAN_MS_BUDGET = 7000.0


@pytest.mark.asyncio
async def test_returns_series_stateful_orchestration_characterization_contract(tmp_path, monkeypatch):
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'returns-series-execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PF-CHAR",
        execution_mode="sync",
        requested_window={"mode": "EXPLICIT"},
    )

    original_returns_series_registry = returns_series_service.execution_registry
    original_stateful_input_registry = stateful_input_service.execution_registry
    returns_series_service.execution_registry = execution_store
    stateful_input_service.execution_registry = execution_store

    core_service_stub = _StatefulBenchmarkCoreServiceStub()
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService,
        "get_portfolio_analytics_timeseries",
        core_service_stub.get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService,
        "get_benchmark_assignment",
        core_service_stub.get_benchmark_assignment,
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService,
        "get_benchmark_composition_window",
        core_service_stub.get_benchmark_composition_window,
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService,
        "get_index_price_series",
        core_service_stub.get_index_price_series,
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService,
        "get_fx_rates",
        core_service_stub.get_fx_rates,
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_risk_free_series", core_service_stub.get_risk_free_series
    )

    request = ReturnsSeriesRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "portfolio_id": "PF-CHAR",
            "as_of_date": str(STATEFUL_PORTFOLIO_WINDOW_END),
            "window": {
                "mode": "EXPLICIT",
                "from_date": str(STATEFUL_PORTFOLIO_WINDOW_START),
                "to_date": str(STATEFUL_PORTFOLIO_WINDOW_END),
            },
            "frequency": "DAILY",
            "metric_basis": "NET",
            "reporting_currency": "USD",
            "series_selection": {
                "include_portfolio": True,
                "include_benchmark": True,
                "include_risk_free": True,
            },
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    try:
        await returns_series_service.calculate_returns_series(request)

        timings = []
        for _ in range(5):
            start = perf_counter()
            response = await returns_series_service.calculate_returns_series(request)
            timings.append((perf_counter() - start) * 1000)
    finally:
        returns_series_service.execution_registry = original_returns_series_registry
        stateful_input_service.execution_registry = original_stateful_input_registry

    expected_points = len(pd.bdate_range(STATEFUL_PORTFOLIO_WINDOW_START, STATEFUL_PORTFOLIO_WINDOW_END))
    assert len(response.series.portfolio_returns) == expected_points
    assert len(response.series.benchmark_returns or []) == expected_points
    assert len(response.series.risk_free_returns or []) == expected_points

    median_ms = median(timings)
    assert median_ms <= RETURNS_SERIES_ORCHESTRATION_MEDIAN_MS_BUDGET, (
        f"Stateful returns-series orchestration median {median_ms:.2f}ms exceeded "
        f"budget {RETURNS_SERIES_ORCHESTRATION_MEDIAN_MS_BUDGET:.2f}ms "
        f"for window {STATEFUL_PORTFOLIO_WINDOW_START}..{STATEFUL_PORTFOLIO_WINDOW_END}."
    )
