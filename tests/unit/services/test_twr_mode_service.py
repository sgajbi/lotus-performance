from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkStatefulInput
from app.models.benchmark_requests import BenchmarkReturnPoint
from app.models.twr_requests import TWRAnalyticsRequest
from app.services.execution_registry import execution_registry
from app.services.execution_stage_names import EXECUTION_STAGE_NORMALIZATION
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from app.services.stateful_performance_input_service import StatefulPortfolioInput
from app.services.twr_mode_service import (
    _build_resolved_twr_benchmark_request,
    _build_resolved_twr_performance_input,
    _build_stateful_twr_benchmark_request,
    _build_twr_normalization_resolution,
    _requested_stateful_twr_benchmark_input,
    _resolve_benchmark_start_date_from_request,
    _resolve_default_stateful_benchmark_input,
    _resolve_stateless_twr_benchmark_request,
    _resolve_stateless_valuation_start_date,
    _resolve_twr_portfolio_source_input,
    _resolve_twr_portfolio_start_date,
    _resolve_twr_retrieval_inputs,
    _resolved_twr_benchmark_id,
    _ResolvedTWRBenchmarkSourceInput,
    _twr_normalization_details,
    _twr_request_needs_retrieval,
    _twr_retrieval_details,
    _TWRRetrievalResolution,
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


def test_twr_request_needs_retrieval_for_stateful_portfolio_mode():
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

    assert _twr_request_needs_retrieval(request) is True


def test_twr_request_needs_retrieval_skips_plain_stateless_mode():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2025-01-01",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000, "end_mv": 1010}],
        }
    )

    assert _twr_request_needs_retrieval(request) is False


def test_twr_request_needs_retrieval_for_stateful_benchmark_mode():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2025-01-01",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000, "end_mv": 1010}],
            "benchmark": {
                "input_mode": "stateful",
                "return_source": "calculated",
                "stateful_input": {},
            },
        }
    )

    assert _twr_request_needs_retrieval(request) is True


def test_resolve_stateless_valuation_start_date_uses_earliest_valuation_point():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
                {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
            ],
        }
    )

    assert _resolve_stateless_valuation_start_date(request) == date(2025, 1, 1)
    assert _resolve_benchmark_start_date_from_request(request) == date(2025, 1, 1)


def test_resolve_benchmark_start_date_from_request_prefers_request_start_for_stateful_mode():
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

    assert _resolve_stateless_valuation_start_date(request) is None
    assert _resolve_benchmark_start_date_from_request(request) == date(2024, 12, 31)


def test_resolve_benchmark_start_date_from_request_uses_report_end_without_request_start():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    assert _resolve_benchmark_start_date_from_request(request) == date(2025, 1, 2)


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


def test_build_twr_normalization_resolution_projects_stateful_valuation_details():
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

    resolution = _build_twr_normalization_resolution(
        request=request,
        retrieval_resolution=_TWRRetrievalResolution(
            portfolio_input=StatefulPortfolioInput(
                performance_start_date=request.report_end_date,
                observations=[
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    }
                ],
            ),
            benchmark_resolution=None,
            benchmark_start_date=request.report_end_date,
            retrieval_details={},
        ),
    )

    assert resolution.resolved_input is not None
    assert len(resolution.resolved_input.valuation_points) == 1
    assert resolution.benchmark_request is None
    assert resolution.normalization_details == {"valuation_points": 1}


def test_twr_normalization_details_projects_portfolio_and_benchmark_counts():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                        {"perf_date": "2025-01-02", "benchmark_return": 0.02},
                    ],
                },
            },
        }
    )
    resolution = _build_twr_normalization_resolution(
        request=request,
        retrieval_resolution=_TWRRetrievalResolution(
            portfolio_input=StatefulPortfolioInput(
                performance_start_date=request.report_end_date,
                observations=[
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    }
                ],
            ),
            benchmark_resolution=None,
            benchmark_start_date=request.report_end_date,
            retrieval_details={},
        ),
    )

    assert _twr_normalization_details(
        resolved_input=resolution.resolved_input,
        benchmark_request=resolution.benchmark_request,
    ) == {
        "valuation_points": 1,
        "benchmark_component_observations": 0,
        "benchmark_return_points": 2,
    }


def test_twr_retrieval_details_merges_portfolio_and_benchmark_sources():
    benchmark_resolution = _ResolvedTWRBenchmarkSourceInput(
        benchmark_id="BMK_1",
        benchmark_request=_resolve_stateless_twr_benchmark_request(
            TWRAnalyticsRequest.model_validate(
                {
                    "calculation_id": str(uuid4()),
                    "portfolio_id": "PORT_1",
                    "performance_start_date": "2025-01-01",
                    "metric_basis": "NET",
                    "report_end_date": "2025-01-02",
                    "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                    "valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000, "end_mv": 1010}],
                    "benchmark": {
                        "benchmark_id": "BMK_1",
                        "input_mode": "stateless",
                        "return_source": "vendor_series",
                        "stateless_input": {
                            "benchmark_currency": "USD",
                            "benchmark_return_points": [{"perf_date": "2025-01-02", "benchmark_return": 0.01}],
                        },
                    },
                }
            )
        ),
        source_details={"benchmark_source": "stateful", "shared": "benchmark"},
    )

    assert _twr_retrieval_details(
        portfolio_retrieval_details={"portfolio_source": "stateful", "shared": "portfolio"},
        benchmark_resolution=benchmark_resolution,
    ) == {
        "portfolio_source": "stateful",
        "benchmark_source": "stateful",
        "shared": "benchmark",
    }
    assert _twr_retrieval_details(
        portfolio_retrieval_details={"portfolio_source": "stateful"},
        benchmark_resolution=None,
    ) == {"portfolio_source": "stateful"}


def test_build_resolved_twr_performance_input_projects_stateful_request_fields():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
            "include_benchmark": True,
        }
    )
    normalization_resolution = _build_twr_normalization_resolution(
        request=request,
        retrieval_resolution=_TWRRetrievalResolution(
            portfolio_input=StatefulPortfolioInput(
                performance_start_date=request.report_end_date,
                observations=[
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    }
                ],
            ),
            benchmark_resolution=None,
            benchmark_start_date=request.report_end_date,
            retrieval_details={},
        ),
    )

    performance_input = _build_resolved_twr_performance_input(
        request=request,
        resolved_input=normalization_resolution.resolved_input,
    )

    assert performance_input.input_mode.value == "stateful"
    assert performance_input.performance_request.portfolio_id == "PORT_1"
    assert performance_input.performance_request.performance_start_date == request.report_end_date
    assert len(performance_input.performance_request.valuation_points) == 1
    assert not hasattr(performance_input.performance_request, "include_benchmark")


def test_resolved_twr_benchmark_id_prefers_resolved_assignment_over_requested_id():
    no_benchmark_request = TWRAnalyticsRequest.model_validate(
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
    explicit_benchmark_request = TWRAnalyticsRequest.model_validate(
        {
            **no_benchmark_request.model_dump(mode="python"),
            "benchmark": {
                "benchmark_id": "BMK_REQUESTED",
                "input_mode": "stateless",
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [{"perf_date": "2025-01-01", "benchmark_return": 0.01}],
                },
            },
        }
    )
    benchmark_request = _resolve_stateless_twr_benchmark_request(explicit_benchmark_request)
    assert benchmark_request is not None
    resolved_assignment = _ResolvedTWRBenchmarkSourceInput(
        benchmark_id="BMK_RESOLVED",
        benchmark_request=benchmark_request,
        source_details={},
    )

    assert _resolved_twr_benchmark_id(request=no_benchmark_request, benchmark_resolution=None) is None
    assert _resolved_twr_benchmark_id(request=explicit_benchmark_request, benchmark_resolution=None) == "BMK_REQUESTED"
    assert (
        _resolved_twr_benchmark_id(
            request=explicit_benchmark_request,
            benchmark_resolution=resolved_assignment,
        )
        == "BMK_RESOLVED"
    )


def test_resolve_stateless_twr_benchmark_request_projects_vendor_return_points():
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
                "return_source": "vendor_series",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "benchmark_return_points": [
                        {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                        {"perf_date": "2025-01-02", "benchmark_return": 0.02},
                    ],
                },
            },
        }
    )

    benchmark_request = _resolve_stateless_twr_benchmark_request(request)

    assert benchmark_request is not None
    assert benchmark_request.benchmark_id == "BMK_1"
    assert benchmark_request.return_source == "vendor_series"
    assert benchmark_request.component_observations == []
    assert [point.benchmark_return for point in benchmark_request.benchmark_return_points] == [0.01, 0.02]


def test_build_stateful_twr_benchmark_request_projects_normalized_vendor_points():
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
                "return_source": "vendor_series",
                "stateful_input": {},
            },
        }
    )
    normalized_input = StatefulBenchmarkNormalizedInput(
        benchmark_currency="USD",
        component_observations=[],
        benchmark_return_points=[
            BenchmarkReturnPoint(perf_date=date(2025, 1, 1), benchmark_return=0.01),
            BenchmarkReturnPoint(perf_date=date(2025, 1, 2), benchmark_return=0.02),
        ],
        source_details={"benchmark_return_points": 2},
    )

    benchmark_request = _build_stateful_twr_benchmark_request(
        request=request,
        benchmark_id="BMK_ASSIGNED",
        benchmark_start_date=date(2024, 12, 31),
        normalized_input=normalized_input,
    )

    assert benchmark_request.benchmark_id == "BMK_ASSIGNED"
    assert benchmark_request.return_source == "vendor_series"
    assert benchmark_request.benchmark_currency == "USD"
    assert benchmark_request.component_observations == []
    assert [point.benchmark_return for point in benchmark_request.benchmark_return_points] == [0.01, 0.02]


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
async def test_resolve_twr_portfolio_source_input_reports_retrieval_details_from_derived_start():
    class _StatefulPortfolioStub:
        captured_start_date = None

        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 200, {"portfolio_open_date": "2024-01-15"}

        async def get_portfolio_timeseries(self, **kwargs):
            self.captured_start_date = kwargs["start_date"]
            return (
                200,
                {
                    "portfolio_open_date": "2024-01-15",
                    "observations": [
                        {
                            "valuation_date": "2025-01-02",
                            "beginning_market_value": "1010",
                            "ending_market_value": "1020.1",
                        },
                        {
                            "valuation_date": "2025-01-01",
                            "beginning_market_value": "1000",
                            "ending_market_value": "1010",
                        },
                    ],
                    "retrieval_metadata": {"chunk_count": 3, "page_count": 2},
                },
            )

    stateful_input_service = _StatefulPortfolioStub()
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

    resolved = await _resolve_twr_portfolio_source_input(
        request=request,
        settings=_settings(),
        stateful_input_service=stateful_input_service,
    )

    assert stateful_input_service.captured_start_date.isoformat() == "2024-01-15"
    assert resolved.benchmark_start_date.isoformat() == "2025-01-01"
    assert resolved.retrieval_details == {
        "portfolio_observations": 2,
        "portfolio_chunk_count": 3,
        "portfolio_page_count": 2,
    }


@pytest.mark.asyncio
async def test_resolve_twr_portfolio_start_date_prefers_explicit_request_date():
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

    assert await _resolve_twr_portfolio_start_date(
        request=request,
        stateful_input_service=object(),
    ) == date(2024, 12, 31)


@pytest.mark.asyncio
async def test_resolve_twr_portfolio_start_date_uses_upstream_open_date_when_missing():
    class _StatefulPortfolioStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 200, {"portfolio_id": "PORT_1", "portfolio_open_date": "2024-01-15"}

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

    assert await _resolve_twr_portfolio_start_date(
        request=request,
        stateful_input_service=_StatefulPortfolioStub(),
    ) == date(2024, 1, 15)


@pytest.mark.asyncio
async def test_resolve_twr_portfolio_start_date_rejects_missing_derived_start():
    class _StatefulPortfolioStub:
        async def get_portfolio_reference(self, **kwargs):  # noqa: ARG002
            return 200, {"portfolio_id": "PORT_1"}

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

    with pytest.raises(HTTPException, match="Stateful source missing portfolio_open_date"):
        await _resolve_twr_portfolio_start_date(
            request=request,
            stateful_input_service=_StatefulPortfolioStub(),
        )


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
async def test_resolve_twr_retrieval_inputs_carries_portfolio_details(monkeypatch):
    portfolio_input = object()

    async def _portfolio_resolution(**kwargs):  # noqa: ARG001
        return SimpleNamespace(
            portfolio_input=portfolio_input,
            benchmark_start_date=None,
            retrieval_details={"portfolio_observations": 2, "portfolio_chunk_count": 1},
        )

    monkeypatch.setattr(
        "app.services.twr_mode_service._resolve_twr_portfolio_source_input",
        _portfolio_resolution,
    )

    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    resolution = await _resolve_twr_retrieval_inputs(
        request=request,
        settings=_settings(),
        stateful_input_service=object(),
    )

    assert resolution.portfolio_input is portfolio_input
    assert resolution.benchmark_resolution is None
    assert resolution.retrieval_details == {"portfolio_observations": 2, "portfolio_chunk_count": 1}


@pytest.mark.asyncio
async def test_resolve_twr_retrieval_inputs_uses_request_benchmark_start_when_portfolio_not_retrieved(monkeypatch):
    captured: dict[str, object] = {}

    async def _benchmark_resolution(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            benchmark_id="BMK_1",
            benchmark_request=object(),
            source_details={"benchmark_components": 1},
        )

    monkeypatch.setattr(
        "app.services.twr_mode_service._resolve_twr_benchmark_source_input",
        _benchmark_resolution,
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

    resolution = await _resolve_twr_retrieval_inputs(
        request=request,
        settings=_settings(),
        stateful_input_service=object(),
    )

    assert resolution.portfolio_input is None
    assert resolution.benchmark_resolution is not None
    assert resolution.benchmark_start_date.isoformat() == "2025-01-01"
    assert captured["benchmark_start_date"].isoformat() == "2025-01-01"
    assert resolution.retrieval_details == {"benchmark_components": 1}


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


def test_requested_stateful_twr_benchmark_input_prefers_explicit_benchmark_input():
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
                "benchmark_id": "BMK_1",
                "input_mode": "stateful",
                "return_source": "calculated",
                "stateful_input": {},
            },
        }
    )

    assert _requested_stateful_twr_benchmark_input(request) is request.benchmark.stateful_input


def test_requested_stateful_twr_benchmark_input_uses_default_stateful_input():
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORT_1",
            "performance_start_date": "2024-12-31",
            "metric_basis": "NET",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "include_benchmark": True,
            "stateful_input": {},
        }
    )

    assert _requested_stateful_twr_benchmark_input(request) == BenchmarkStatefulInput()


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
