from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.benchmark_analytics_requests import BenchmarkInputMode
from app.models.twr_requests import TWRAnalyticsRequest
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION
from app.services.twr_mode_service import (
    _build_resolved_twr_benchmark_request,
    _resolve_default_stateful_benchmark_input,
    resolve_twr_request,
)


def _settings():
    return SimpleNamespace(
        CORE_CONTROL_PLANE_BASE_URL="http://core-control",
        CORE_QUERY_BASE_URL="http://core",
        resolved_core_control_plane_base_url="http://core-control",
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
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
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
            "stateful_input": {},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateful"
    assert [point.perf_date.isoformat() for point in resolved.performance_request.valuation_points] == [
        "2025-01-01",
        "2025-01-02",
    ]
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
            "stateful_input": {},
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
async def test_resolve_twr_request_allows_missing_stateful_start_date(monkeypatch):
    class _StatefulPortfolioStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 200, {"portfolio_open_date": "2024-01-15"}

        async def get_portfolio_timeseries(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "portfolio_open_date": "2024-01-15",
                    "observations": [
                        {
                            "valuation_date": "2025-01-01",
                            "beginning_market_value": "1000",
                            "ending_market_value": "1010",
                        },
                    ],
                },
            )

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _StatefulPortfolioStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
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
            "stateful_input": {},
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
    assert stages[EXECUTION_STAGE_NORMALIZATION].status.value == "failed"


@pytest.mark.asyncio
async def test_resolve_twr_request_builds_stateless_benchmark_request():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
            ],
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2025-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.02,
                        },
                    ],
                },
            },
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateless"
    assert resolved.benchmark_request is not None
    assert resolved.resolved_benchmark_id == "BMK_1"
    assert resolved.benchmark_request.benchmark_currency == "USD"
    assert len(resolved.benchmark_request.component_observations) == 2


@pytest.mark.asyncio
async def test_resolve_twr_request_sources_stateful_benchmark_assignment(monkeypatch):
    class _StatefulBenchmarkStub:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_ASSIGNED"}

        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "benchmark_id": "BMK_ASSIGNED",
                    "benchmark_currency": "USD",
                    "segments": [
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "1.0",
                            "composition_effective_from": "2024-12-31",
                            "composition_effective_to": "2025-01-31",
                        }
                    ],
                },
            )

        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "points": [
                        {"series_date": "2024-12-31", "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2025-01-01", "index_price": "101", "series_currency": "USD"},
                        {"series_date": "2025-01-02", "index_price": "102.01", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )

        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 200, {"points": []}

        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "unused"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _StatefulBenchmarkStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
            ],
            "benchmark": {
                "input_mode": "stateful",
                "return_source": "calculated",
                "stateful_input": {},
            },
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateless"
    assert resolved.resolved_benchmark_id == "BMK_ASSIGNED"
    assert resolved.benchmark_request is not None
    assert resolved.benchmark_request.benchmark_currency == "USD"
    assert len(resolved.benchmark_request.component_observations) == 2


@pytest.mark.asyncio
async def test_resolve_twr_request_sources_default_stateful_benchmark_assignment_when_include_benchmark_enabled(
    monkeypatch,
):
    class _StatefulBenchmarkStub:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_ASSIGNED"}

        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "benchmark_id": "BMK_ASSIGNED",
                    "benchmark_currency": "USD",
                    "segments": [
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "1.0",
                            "composition_effective_from": "2024-12-31",
                            "composition_effective_to": "2025-01-31",
                        }
                    ],
                },
            )

        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "points": [
                        {"series_date": "2024-12-31", "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2025-01-01", "index_price": "101", "series_currency": "USD"},
                        {"series_date": "2025-01-02", "index_price": "102.01", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )

        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 200, {"points": []}

        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "unused"}

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
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _StatefulBenchmarkStub(),  # noqa: ARG005
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
            "stateful_input": {},
            "include_benchmark": True,
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    resolved = await resolve_twr_request(request, settings=_settings())

    assert resolved.input_mode.value == "stateful"
    assert resolved.resolved_benchmark_id == "BMK_ASSIGNED"
    assert resolved.benchmark_request is not None
    assert resolved.benchmark_input_mode == BenchmarkInputMode.STATEFUL


@pytest.mark.asyncio
async def test_resolve_twr_request_fails_when_stateful_portfolio_reference_is_unavailable(monkeypatch):
    class _UnavailablePortfolioStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "unavailable"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _UnavailablePortfolioStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="portfolio reference source unavailable"):
        await resolve_twr_request(request, settings=_settings())


@pytest.mark.asyncio
async def test_resolve_twr_request_404_reference_error_mentions_control_plane(monkeypatch):
    class _UnavailablePortfolioStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "missing"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _UnavailablePortfolioStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_twr_request(request, settings=_settings())

    assert "CORE_CONTROL_PLANE_BASE_URL" in str(exc_info.value.detail)
    assert "query-control-plane" in str(exc_info.value.detail)
    assert "stale container env" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_resolve_twr_request_fails_when_stateful_portfolio_reference_date_is_invalid(monkeypatch):
    class _InvalidPortfolioReferenceStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 200, {"portfolio_open_date": "not-a-date"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _InvalidPortfolioReferenceStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="Invalid portfolio_open_date"):
        await resolve_twr_request(request, settings=_settings())


@pytest.mark.asyncio
async def test_resolve_twr_request_fails_when_assignment_lookup_cannot_resolve_benchmark_id(monkeypatch):
    class _MissingBenchmarkAssignmentStub:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _MissingBenchmarkAssignmentStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
            ],
            "benchmark": {
                "input_mode": "stateful",
                "return_source": "calculated",
                "stateful_input": {},
            },
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="benchmark assignment payload missing benchmark_id"):
        await resolve_twr_request(request, settings=_settings())


@pytest.mark.asyncio
async def test_resolve_twr_request_fails_when_assignment_lookup_is_missing(monkeypatch):
    class _NotFoundBenchmarkAssignmentStub:
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "missing"}

    monkeypatch.setattr(
        "app.services.twr_mode_service.build_stateful_input_service",
        lambda settings: _NotFoundBenchmarkAssignmentStub(),  # noqa: ARG005
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
            ],
            "benchmark": {
                "input_mode": "stateful",
                "return_source": "calculated",
                "stateful_input": {},
            },
        }
    )
    execution_registry.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="TWR",
        portfolio_id=request.portfolio_id,
    )

    with pytest.raises(HTTPException, match="No benchmark assignment found"):
        await resolve_twr_request(request, settings=_settings())


def test_twr_benchmark_helpers_reject_missing_stateless_and_stateful_benchmark_inputs():
    with pytest.raises(ValidationError, match="benchmark configuration is required when include_benchmark=true"):
        TWRAnalyticsRequest.model_validate(
            {
                "calculation_id": str(uuid4()),
                "portfolio_id": "PORT_1",
                "performance_start_date": "2024-12-31",
                "metric_basis": "NET",
                "report_end_date": "2025-01-02",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                ],
                "include_benchmark": True,
            }
        )

    request = TWRAnalyticsRequest.model_construct(
        calculation_id=uuid4(),
        portfolio_id="PORT_1",
        metric_basis="NET",
        report_end_date="2025-01-02",
        analyses=[],
        include_benchmark=True,
        stateful_input=None,
    )
    with pytest.raises(HTTPException, match="stateful_input is required when include_benchmark=true in stateful mode"):
        _resolve_default_stateful_benchmark_input(request)


def test_twr_benchmark_helpers_reject_stateless_benchmark_without_required_payload():
    with pytest.raises(ValidationError, match="benchmark.stateless_input is required"):
        TWRAnalyticsRequest.model_validate(
            {
                "calculation_id": str(uuid4()),
                "portfolio_id": "PORT_1",
                "performance_start_date": "2024-12-31",
                "metric_basis": "NET",
                "report_end_date": "2025-01-02",
                "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                "valuation_points": [
                    {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
                ],
                "benchmark": {
                    "benchmark_id": "BMK_1",
                    "input_mode": "stateless",
                    "return_source": "calculated",
                },
            }
        )


def test_build_resolved_twr_benchmark_request_passthroughs_resolution():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
            ],
        }
    )
    resolved_request = request.to_stateless_performance_request()
    benchmark_request = None

    assert (
        _build_resolved_twr_benchmark_request(
            request=request,
            benchmark_resolution=benchmark_request,
            benchmark_start_date=resolved_request.performance_start_date,
        )
        is None
    )
