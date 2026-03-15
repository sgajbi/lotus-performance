from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.returns_series import ReturnsSeriesRequest
from app.services import portfolio_source_service, returns_series_service, stateful_input_service
from app.services.execution_registry import ExecutionRegistry
from core.repro import generate_canonical_hash


def _build_stateful_request(**overrides):
    payload = {
        "calculation_id": str(uuid4()),
        "portfolio_id": "P1",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": False},
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }
    payload.update(overrides)
    return ReturnsSeriesRequest.model_validate(payload)


def _seed_execution(monkeypatch, tmp_path, request):
    store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    store.create_schema()
    monkeypatch.setattr(returns_series_service, "execution_registry", store)
    monkeypatch.setattr(stateful_input_service, "execution_registry", store)
    store.create_execution(
        calculation_id=request.calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id=request.portfolio_id,
        execution_mode="sync",
        requested_window={},
    )
    return store


@pytest.mark.asyncio
async def test_calculate_returns_series_requires_open_date(monkeypatch, tmp_path):
    request = _build_stateful_request()
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"}
            ]
        }

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )

    with pytest.raises(HTTPException) as exc:
        await returns_series_service.calculate_returns_series(request)
    assert exc.value.status_code == 422
    assert exc.value.detail["message"] == "Stateful source missing portfolio_open_date."


@pytest.mark.asyncio
async def test_calculate_returns_series_maps_assignment_source_unavailable(monkeypatch, tmp_path):
    request = _build_stateful_request()
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-23",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"}
            ],
        }

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 503, {"detail": "down"}

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)

    with pytest.raises(HTTPException) as exc:
        await returns_series_service.calculate_returns_series(request)
    assert exc.value.status_code == 503
    assert "Benchmark assignment source unavailable" in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_calculate_returns_series_requires_benchmark_id_and_points(monkeypatch, tmp_path):
    request = _build_stateful_request()
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-23",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
                {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
            ],
        }

    async def _missing_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {}

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _missing_assignment
    )

    with pytest.raises(HTTPException) as exc_missing_id:
        await returns_series_service.calculate_returns_series(request)
    assert exc_missing_id.value.status_code == 422

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK"}

    async def _bad_points(self, **kwargs):  # noqa: ARG001
        return 200, {"bad": []}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _bad_points)

    with pytest.raises(HTTPException) as exc_bad_points:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bad_points.value.status_code == 422
    assert "benchmark series is empty" in exc_bad_points.value.detail["message"]


@pytest.mark.asyncio
async def test_calculate_returns_series_maps_benchmark_and_risk_free_errors(monkeypatch, tmp_path):
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
        reporting_currency="USD",
    )
    _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-23",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
                {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
            ],
        }

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK"}

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)

    async def _benchmark_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_404)
    with pytest.raises(HTTPException) as exc_bmk_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_404.value.status_code == 404

    async def _benchmark_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_503)
    with pytest.raises(HTTPException) as exc_bmk_503:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_503.value.status_code == 503

    async def _benchmark_ok(self, **kwargs):  # noqa: ARG001
        return 200, {"points": [{"series_date": "2026-02-23", "benchmark_return": "0.01"}]}

    async def _risk_free_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_ok)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_risk_free_series", _risk_free_404)
    with pytest.raises(HTTPException) as exc_rf_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_rf_404.value.status_code == 404

    async def _risk_free_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_risk_free_series", _risk_free_503)
    with pytest.raises(HTTPException) as exc_rf_503:
        await returns_series_service.calculate_returns_series(request)
    assert exc_rf_503.value.status_code == 503


@pytest.mark.asyncio
async def test_calculate_returns_series_handles_unexpected_exception_and_strict_intersection(monkeypatch, tmp_path):
    request = ReturnsSeriesRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "series_selection": {"include_portfolio": True, "include_benchmark": True, "include_risk_free": True},
            "data_policy": {"missing_data_policy": "STRICT_INTERSECTION"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.01"},
                    {"date": "2026-02-24", "return_value": "0.02"},
                ],
                "benchmark_returns": [
                    {"date": "2026-02-24", "return_value": "0.03"},
                    {"date": "2026-02-25", "return_value": "0.04"},
                ],
                "risk_free_returns": [
                    {"date": "2026-02-24", "return_value": "0.001"},
                    {"date": "2026-02-25", "return_value": "0.001"},
                ],
            },
        }
    )
    store = _seed_execution(monkeypatch, tmp_path, request)

    response = await returns_series_service.calculate_returns_series(request)
    assert len(response.series.portfolio_returns) == 1
    assert len(response.series.benchmark_returns or []) == 1
    assert len(response.series.risk_free_returns or []) == 1

    async def _boom(_request):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(
        returns_series_service, "resample_returns", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    failing_request = ReturnsSeriesRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "as_of_date": "2026-02-25",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
            "frequency": "DAILY",
            "metric_basis": "NET",
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [
                    {"date": "2026-02-23", "return_value": "0.01"},
                    {"date": "2026-02-24", "return_value": "0.02"},
                ]
            },
        }
    )
    store.create_execution(
        calculation_id=failing_request.calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="P1",
        execution_mode="sync",
        requested_window={},
    )
    with pytest.raises(RuntimeError, match="boom"):
        await returns_series_service.calculate_returns_series(failing_request)
    execution = store.get_execution(failing_request.calculation_id)
    assert execution is not None
    assert execution.status.value == "failed"


@pytest.mark.asyncio
async def test_calculate_returns_series_updates_stateful_identity_from_resolved_series(monkeypatch, tmp_path):
    request = _build_stateful_request(reporting_currency="USD")
    store = _seed_execution(monkeypatch, tmp_path, request)

    async def _portfolio(self, **kwargs):  # noqa: ARG001
        return 200, {
            "portfolio_open_date": "2026-02-20",
            "observations": [
                {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"},
                {"valuation_date": "2026-02-24", "beginning_market_value": "101", "ending_market_value": "102"},
                {"valuation_date": "2026-02-25", "beginning_market_value": "102", "ending_market_value": "103"},
            ],
        }

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_RESOLVED"}

    async def _benchmark(self, **kwargs):  # noqa: ARG001
        return 200, {
            "points": [
                {"series_date": "2026-02-23", "benchmark_return": "0.0010"},
                {"series_date": "2026-02-24", "benchmark_return": "0.0020"},
                {"series_date": "2026-02-25", "benchmark_return": "0.0030"},
            ]
        }

    monkeypatch.setattr(
        portfolio_source_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio
    )
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)
    monkeypatch.setattr(portfolio_source_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark)

    initial_input_fingerprint, initial_calculation_hash = generate_canonical_hash(request, "returns-series-v1")

    response = await returns_series_service.calculate_returns_series(request)

    resolved_payload = returns_series_service._build_stateful_resolved_returns_payload(
        request=request,
        resolved_window=response.resolved_window,
        portfolio_records=[point.model_dump(mode="json") for point in response.series.portfolio_returns],
        benchmark_records=[point.model_dump(mode="json") for point in (response.series.benchmark_returns or [])],
        risk_free_records=None,
        resolved_benchmark_id="BMK_RESOLVED",
    )
    expected_input_fingerprint, expected_calculation_hash = generate_canonical_hash(
        resolved_payload,
        "returns-series-v1",
    )

    assert response.provenance.input_fingerprint == expected_input_fingerprint
    assert response.provenance.calculation_hash == expected_calculation_hash
    assert response.provenance.input_fingerprint != initial_input_fingerprint
    assert response.provenance.calculation_hash != initial_calculation_hash

    execution = store.get_execution(request.calculation_id)
    assert execution is not None
    assert execution.input_fingerprint == expected_input_fingerprint
    assert execution.calculation_hash == expected_calculation_hash


@pytest.mark.asyncio
async def test_calculate_returns_series_uses_runtime_stateful_settings(monkeypatch, tmp_path):
    request = _build_stateful_request(
        series_selection={"include_portfolio": True, "include_benchmark": False, "include_risk_free": False},
        data_policy={"missing_data_policy": "ALLOW_PARTIAL"},
    )
    _seed_execution(monkeypatch, tmp_path, request)
    captured: dict[str, object] = {}

    class _FakeStatefulInputService:
        def __init__(self, *, core_service, portfolio_chunk_days, reference_chunk_days, max_concurrent_chunks):
            captured["core_init"] = {
                "base_url": getattr(core_service, "_base_url"),
                "timeout_seconds": getattr(core_service, "_timeout"),
                "max_retries": getattr(core_service, "_max_retries"),
                "retry_backoff_seconds": getattr(core_service, "_retry_backoff_seconds"),
            }
            captured["stateful_init"] = {
                "portfolio_chunk_days": portfolio_chunk_days,
                "reference_chunk_days": reference_chunk_days,
                "max_concurrent_chunks": max_concurrent_chunks,
            }

        async def get_portfolio_timeseries(self, **kwargs):
            return 200, {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "100", "ending_market_value": "101"}
                ],
            }

    monkeypatch.setattr(
        returns_series_service,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "CORE_QUERY_BASE_URL": "http://runtime-core",
                "CORE_TIMEOUT_SECONDS": 17.0,
                "CORE_MAX_RETRIES": 5,
                "CORE_RETRY_BACKOFF_SECONDS": 1.5,
                "STATEFUL_INPUT_PORTFOLIO_CHUNK_DAYS": 13,
                "STATEFUL_INPUT_REFERENCE_CHUNK_DAYS": 29,
                "STATEFUL_INPUT_MAX_CONCURRENT_CHUNKS": 7,
            },
        )(),
    )
    monkeypatch.setattr(portfolio_source_service, "StatefulInputService", _FakeStatefulInputService)
    monkeypatch.setattr(
        returns_series_service,
        "daily_ror_from_portfolio_timeseries",
        lambda **kwargs: __import__("pandas").DataFrame(
            {"date": __import__("pandas").to_datetime(["2026-02-23"]), "return_value": [0.01]}
        ),
    )

    response = await returns_series_service.calculate_returns_series(request)

    assert captured["core_init"] == {
        "base_url": "http://runtime-core",
        "timeout_seconds": 17.0,
        "max_retries": 5,
        "retry_backoff_seconds": 1.5,
    }
    assert captured["stateful_init"] == {
        "portfolio_chunk_days": 13,
        "reference_chunk_days": 29,
        "max_concurrent_chunks": 7,
    }
    assert len(response.series.portfolio_returns) == 1
