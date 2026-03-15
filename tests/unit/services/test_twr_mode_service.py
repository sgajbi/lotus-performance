from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.twr_requests import TWRAnalyticsRequest
from app.services.execution_registry import execution_registry
from app.services.twr_mode_service import resolve_twr_request


def _settings():
    return SimpleNamespace(
        CORE_QUERY_BASE_URL="http://core",
        CORE_TIMEOUT_SECONDS=5.0,
        CORE_MAX_RETRIES=2,
        CORE_RETRY_BACKOFF_SECONDS=0.1,
        STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS=90,
        STATEFUL_INPUT_REFERENCE_CHUNK_DAYS=365,
        STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS=4,
    )


@pytest.fixture(autouse=True)
def _execution_schema():
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    yield
    execution_registry.clear_all_records()


@pytest.mark.asyncio
async def test_resolve_twr_request_passthroughs_stateless_mode():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"day": 2, "perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
            ],
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateless"
    assert len(resolved.performance_request.valuation_points) == 2


@pytest.mark.asyncio
async def test_resolve_twr_request_sources_stateful_payload(monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-12-31",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {
                "consumer_system": "lotus-performance",
            },
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateful"
    assert [point.day for point in resolved.performance_request.valuation_points] == [1, 2]
    assert resolved.performance_request.valuation_points[1].end_mv == 1020.1
    assert str(resolved.performance_request.performance_start_date) == "2024-12-31"


@pytest.mark.asyncio
async def test_resolve_twr_request_raises_for_empty_stateful_observations(monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return 200, {"portfolio_open_date": "2024-12-31", "observations": []}

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="Stateful source returned no observations"):
        await resolve_twr_request(request, settings=_settings())


@pytest.mark.asyncio
async def test_resolve_twr_request_uses_upstream_open_date_over_request_start(monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-01-15",
                "observations": [
                    {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert str(resolved.performance_request.performance_start_date) == "2024-01-15"


@pytest.mark.asyncio
async def test_resolve_twr_request_fails_normalization_stage_for_invalid_observations(monkeypatch):
    async def _mock_fetch_stateful_portfolio_timeseries(**kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2024-01-15",
                "observations": [{"valuation_date": None}],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_performance_input_service.fetch_stateful_portfolio_timeseries",
        _mock_fetch_stateful_portfolio_timeseries,
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {"consumer_system": "lotus-performance"},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="No valid valuation observations"):
        await resolve_twr_request(request, settings=_settings())

    execution = execution_registry.get_execution(request.calculation_id)
    assert execution is not None
    stages = {stage.stage_name: stage for stage in execution.stages}
    assert stages["normalization"].status.value == "failed"
