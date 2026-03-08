from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.returns_series import ReturnsSeriesRequest
from app.services import returns_series_service, stateful_input_service
from app.services.execution_registry import ExecutionRegistry


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

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio)

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

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio)
    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)

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

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio)
    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_assignment", _missing_assignment)

    with pytest.raises(HTTPException) as exc_missing_id:
        await returns_series_service.calculate_returns_series(request)
    assert exc_missing_id.value.status_code == 422

    async def _assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK"}

    async def _bad_points(self, **kwargs):  # noqa: ARG001
        return 200, {"bad": []}

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)
    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_return_series", _bad_points)

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

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_portfolio_analytics_timeseries", _portfolio)
    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_assignment", _assignment)

    async def _benchmark_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_404)
    with pytest.raises(HTTPException) as exc_bmk_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_404.value.status_code == 404

    async def _benchmark_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_503)
    with pytest.raises(HTTPException) as exc_bmk_503:
        await returns_series_service.calculate_returns_series(request)
    assert exc_bmk_503.value.status_code == 503

    async def _benchmark_ok(self, **kwargs):  # noqa: ARG001
        return 200, {"points": [{"series_date": "2026-02-23", "benchmark_return": "0.01"}]}

    async def _risk_free_404(self, **kwargs):  # noqa: ARG001
        return 404, {}

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_benchmark_return_series", _benchmark_ok)
    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_risk_free_series", _risk_free_404)
    with pytest.raises(HTTPException) as exc_rf_404:
        await returns_series_service.calculate_returns_series(request)
    assert exc_rf_404.value.status_code == 404

    async def _risk_free_503(self, **kwargs):  # noqa: ARG001
        return 503, {}

    monkeypatch.setattr(returns_series_service.CoreIntegrationService, "get_risk_free_series", _risk_free_503)
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
