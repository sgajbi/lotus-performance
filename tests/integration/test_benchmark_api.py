from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_calculate_benchmark_endpoint_supports_stateless_calculated_mode(client):
    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATELESS_1",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "output": {"include_timeseries": True},
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_A",
                    "date": "2026-01-02",
                    "weight_bop": 0.6,
                    "component_return": 0.02,
                    "component_return_local": 0.015,
                    "component_return_fx": 0.004926108374,
                },
                {
                    "component_id": "IDX_B",
                    "date": "2026-01-02",
                    "weight_bop": 0.4,
                    "component_return": 0.01,
                    "component_return_local": 0.01,
                    "component_return_fx": 0.0,
                },
                {
                    "component_id": "IDX_A",
                    "date": "2026-01-03",
                    "weight_bop": 0.6,
                    "component_return": 0.01,
                    "component_return_local": 0.008,
                    "component_return_fx": 0.001984126984,
                },
                {
                    "component_id": "IDX_B",
                    "date": "2026-01-03",
                    "weight_bop": 0.4,
                    "component_return": 0.005,
                    "component_return_local": 0.005,
                    "component_return_fx": 0.0,
                },
            ],
        },
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 200
    body = response.json()
    itd = body["results_by_period"]["ITD"]
    assert body["input_mode"] == "stateless"
    assert body["return_source"] == "calculated"
    assert itd["benchmark_return"] == pytest.approx(0.024128)
    assert len(itd["daily_returns"]) == 2
    assert len(itd["component_contributions"]) == 4
    assert itd["daily_returns"][0]["benchmark_return_local"] == pytest.approx(0.013)
    assert itd["daily_returns"][0]["benchmark_return_fx"] == pytest.approx(0.0029556650244)


def test_calculate_benchmark_endpoint_supports_stateful_calculated_mode(client, monkeypatch):
    async def _mock_get_benchmark_composition_window(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "benchmark_id": "BMK_STATEFUL_1",
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX_USD",
                        "composition_weight": "0.6",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": "2026-01-31",
                    },
                    {
                        "index_id": "IDX_EUR",
                        "composition_weight": "0.4",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": "2026-01-31",
                    },
                ],
            },
        )

    async def _mock_get_index_price_series(self, **kwargs):  # noqa: ARG001
        index_id = kwargs["index_id"]
        if index_id == "IDX_USD":
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2026-01-02", "index_price": "102", "series_currency": "USD"},
                        {"series_date": "2026-01-03", "index_price": "103.02", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-01-01", "index_price": "100", "series_currency": "EUR"},
                    {"series_date": "2026-01-02", "index_price": "101", "series_currency": "EUR"},
                    {"series_date": "2026-01-03", "index_price": "101.505", "series_currency": "EUR"},
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )

    async def _mock_get_fx_rates(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-01-01", "fx_rate": "1.20"},
                    {"series_date": "2026-01-02", "fx_rate": "1.212"},
                    {"series_date": "2026-01-03", "fx_rate": "1.21806"},
                ],
                "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_composition_window",
        _mock_get_benchmark_composition_window,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_index_price_series",
        _mock_get_index_price_series,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_fx_rates",
        _mock_get_fx_rates,
    )

    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATEFUL_1",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "output": {"include_timeseries": True},
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 200
    body = response.json()
    itd = body["results_by_period"]["ITD"]
    assert body["input_mode"] == "stateful"
    assert body["benchmark_currency"] == "USD"
    assert itd["benchmark_return"] == pytest.approx(0.0302506004, abs=1e-10)
    assert itd["daily_returns"][0]["benchmark_return_local"] == pytest.approx(0.016)
    assert itd["daily_returns"][0]["benchmark_return_fx"] == pytest.approx(0.004)
    assert len(itd["component_contributions"]) == 4
    assert body["audit"]["counts"]["component_observations"] == 4


def test_calculate_benchmark_endpoint_records_http_failure_detail_in_execution_status(client, monkeypatch):
    calculation_id = str(uuid4())

    async def _mock_get_benchmark_composition_window(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "benchmark_id": "BMK_BAD_WINDOW",
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX_A",
                        "composition_weight": "1.0",
                        "composition_effective_from": "2026-01-03",
                        "composition_effective_to": "2026-01-31",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_composition_window",
        _mock_get_benchmark_composition_window,
    )

    payload = {
        "calculation_id": calculation_id,
        "benchmark_id": "BMK_BAD_WINDOW",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 422
    assert "does not cover requested date 2026-01-02" in response.json()["detail"]

    execution_response = client.get(f"/performance/executions/{calculation_id}")
    assert execution_response.status_code == 200
    body = execution_response.json()
    assert body["status"] == "failed"
    assert "does not cover requested date 2026-01-02" in body["error_message"]
    retrieval_stage = {stage["stage_name"]: stage for stage in body["stages"]}["retrieval"]
    assert retrieval_stage["status"] == "failed"
    assert "does not cover requested date 2026-01-02" in retrieval_stage["error_message"]


def test_calculate_benchmark_endpoint_supports_explicit_vendor_series_mode(client, monkeypatch):
    async def _mock_get_benchmark_definition(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "benchmark_id": "BMK_VENDOR_1",
                "benchmark_currency": "USD",
                "components": [
                    {
                        "index_id": "IDX_A",
                        "composition_weight": "1.0",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": None,
                    }
                ],
            },
        )

    async def _mock_get_benchmark_return_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-01-02", "benchmark_return": "0.0100"},
                    {"series_date": "2026-01-03", "benchmark_return": "0.0200"},
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_definition",
        _mock_get_benchmark_definition,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_benchmark_return_series",
        _mock_get_benchmark_return_series,
    )

    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_VENDOR_1",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "vendor_series",
        "output": {"include_timeseries": True},
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 200
    body = response.json()
    itd = body["results_by_period"]["ITD"]
    assert body["return_source"] == "vendor_series"
    assert itd["benchmark_return"] == pytest.approx(0.0302)
    assert "component_contributions" not in itd
