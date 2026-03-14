from statistics import median
from time import perf_counter
from uuid import uuid4

import pytest

import app.services.returns_series_service as returns_series_service
import app.services.stateful_input_service as stateful_input_service
from app.models.returns_series import ReturnsSeriesRequest
from app.services.execution_registry import ExecutionRegistry
from tests.benchmarks.test_stateful_input_performance import (
    STATEFUL_PORTFOLIO_WINDOW_END,
    STATEFUL_PORTFOLIO_WINDOW_START,
    _StatefulCoreServiceStub,
)

RETURNS_SERIES_ORCHESTRATION_MEDIAN_MS_BUDGET = 1000.0


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

    core_service_stub = _StatefulCoreServiceStub()
    monkeypatch.setattr(
        returns_series_service.CoreIntegrationService,
        "get_portfolio_analytics_timeseries",
        core_service_stub.get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        returns_series_service.CoreIntegrationService,
        "get_benchmark_assignment",
        core_service_stub.get_benchmark_assignment,
    )
    monkeypatch.setattr(
        returns_series_service.CoreIntegrationService,
        "get_benchmark_return_series",
        core_service_stub.get_benchmark_return_series,
    )
    monkeypatch.setattr(
        returns_series_service.CoreIntegrationService,
        "get_risk_free_series",
        core_service_stub.get_risk_free_series,
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
            "stateful_input": {"consumer_system": "lotus-performance"},
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

    assert len(response.series.portfolio_returns) == 3653
    assert len(response.series.benchmark_returns or []) == 3653
    assert len(response.series.risk_free_returns or []) == 3653

    median_ms = median(timings)
    assert median_ms <= RETURNS_SERIES_ORCHESTRATION_MEDIAN_MS_BUDGET, (
        f"Stateful returns-series orchestration median {median_ms:.2f}ms exceeded "
        f"budget {RETURNS_SERIES_ORCHESTRATION_MEDIAN_MS_BUDGET:.2f}ms "
        f"for window {STATEFUL_PORTFOLIO_WINDOW_START}..{STATEFUL_PORTFOLIO_WINDOW_END}."
    )
