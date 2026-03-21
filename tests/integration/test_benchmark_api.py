import os
import shutil
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services.async_result_store import async_result_store
from app.services.benchmark_mode_service import ResolvedBenchmarkRequest
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from core.repro import generate_canonical_hash
from main import app
from tests.conftest import drain_compute_queue


@pytest.fixture()
def client():
    settings = get_settings()
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    compute_job_store.create_schema()
    compute_job_store.clear_all_records()
    async_result_store.create_schema()
    async_result_store.clear_all_records()
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app) as c:
        yield c


def test_calculate_benchmark_endpoint_supports_stateless_calculated_mode(client):
    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATELESS_1",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily", "monthly"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "output": {"include_timeseries": True},
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.6,
                    "component_return": 0.02,
                    "component_return_local": 0.015,
                    "component_return_fx": 0.004926108374,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.4,
                    "component_return": 0.01,
                    "component_return_local": 0.01,
                    "component_return_fx": 0.0,
                },
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-03",
                    "weight_bop": 0.6,
                    "component_return": 0.01,
                    "component_return_local": 0.008,
                    "component_return_fx": 0.001984126984,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-03",
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
    assert itd["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(2.4128)
    assert itd["benchmark"]["summary"]["cumulative_return"]["base"] == pytest.approx(2.4128)
    assert itd["benchmark"]["breakdowns"]["daily"][1]["cumulative_return"]["base"] == pytest.approx(2.4128)
    assert itd["benchmark"]["breakdowns"]["monthly"][0]["period_return"]["base"] == pytest.approx(2.4128)
    assert len(itd["daily_returns"]) == 2
    assert len(itd["component_contributions"]) == 4
    assert itd["daily_returns"][0]["benchmark_return_local"] == pytest.approx(1.3)
    assert itd["daily_returns"][0]["benchmark_return_fx"] == pytest.approx(0.29556650244)


def test_calculate_benchmark_endpoint_supports_stateless_component_price_points(client):
    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATELESS_PRICE_1",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "output": {"include_timeseries": True},
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_price_points": [
                {"component_id": "IDX_A", "perf_date": "2026-01-01", "weight_bop": 0.6, "index_price": 100.0},
                {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "index_price": 102.0},
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.4,
                    "index_price": 100.0,
                    "component_currency": "EUR",
                    "fx_rate_to_benchmark": 1.2,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.4,
                    "index_price": 101.0,
                    "component_currency": "EUR",
                    "fx_rate_to_benchmark": 1.212,
                },
            ],
        },
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 200
    body = response.json()
    itd = body["results_by_period"]["ITD"]
    raw_request = BenchmarkAnalyticsRequest.model_validate(payload)
    raw_input_fingerprint, _ = generate_canonical_hash(raw_request, get_settings().APP_VERSION)
    assert itd["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(2.004)
    assert itd["daily_returns"][0]["benchmark_return_local"] == pytest.approx(1.6)
    assert itd["daily_returns"][0]["benchmark_return_fx"] == pytest.approx(0.4)
    assert len(itd["component_contributions"]) == 2
    assert body["meta"]["input_fingerprint"] != raw_input_fingerprint


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
        "stateful_input": {},
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 200
    body = response.json()
    itd = body["results_by_period"]["ITD"]
    assert body["input_mode"] == "stateful"
    assert body["benchmark_currency"] == "USD"
    assert itd["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(3.02506004, abs=1e-10)
    assert itd["daily_returns"][0]["benchmark_return_local"] == pytest.approx(1.6)
    assert itd["daily_returns"][0]["benchmark_return_fx"] == pytest.approx(0.4)
    assert len(itd["component_contributions"]) == 4
    assert body["audit"]["counts"]["component_observations"] == 4


def test_calculate_benchmark_endpoint_rejects_stateless_price_points_with_misaligned_component_dates(client):
    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATELESS_PRICE_BAD_DATES",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_price_points": [
                {"component_id": "IDX_A", "perf_date": "2026-01-01", "weight_bop": 0.6, "index_price": 100.0},
                {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "index_price": 102.0},
                {"component_id": "IDX_B", "perf_date": "2026-01-01", "weight_bop": 0.4, "index_price": 100.0},
                {"component_id": "IDX_B", "perf_date": "2026-01-03", "weight_bop": 0.4, "index_price": 101.0},
            ],
        },
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 422
    assert "same derived return-date set" in response.json()["detail"]


def test_calculate_benchmark_endpoint_rejects_stateless_price_points_with_duplicate_component_dates(client):
    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATELESS_PRICE_DUP_DATES",
        "benchmark_start_date": "2026-01-01",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_price_points": [
                {"component_id": "IDX_A", "perf_date": "2026-01-01", "weight_bop": 0.6, "index_price": 100.0},
                {"component_id": "IDX_A", "perf_date": "2026-01-01", "weight_bop": 0.6, "index_price": 101.0},
                {"component_id": "IDX_B", "perf_date": "2026-01-01", "weight_bop": 0.4, "index_price": 100.0},
                {"component_id": "IDX_B", "perf_date": "2026-01-02", "weight_bop": 0.4, "index_price": 101.0},
            ],
        },
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 422
    assert "strictly increasing unique dates" in response.json()["detail"]


def test_benchmark_results_endpoint_returns_async_stateful_result(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.BENCHMARK_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = 365
    settings.BENCHMARK_EXECUTOR_INPUT_COUNT = 1

    async def _mock_resolve_benchmark_request(request, *, settings):  # noqa: ARG001
        return ResolvedBenchmarkRequest(
            benchmark_request=BenchmarkPerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "benchmark_id": "BMK_ASYNC_1",
                    "benchmark_start_date": "2026-01-01",
                    "report_end_date": "2026-01-03",
                    "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2026-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2026-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_A",
                            "perf_date": "2026-01-03",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                    ],
                }
            ),
            input_mode=BenchmarkInputMode.STATEFUL,
            source_details={"component_observations": 3},
            input_count=3,
        )

    monkeypatch.setattr("app.api.endpoints.benchmark.resolve_benchmark_request", _mock_resolve_benchmark_request)

    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_ASYNC_1",
        "benchmark_start_date": "2026-01-01",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {},
        "output": {"include_timeseries": True},
    }

    try:
        response = client.post("/performance/benchmark", json=payload)
        assert response.status_code == 202
        calculation_id = response.json()["calculation_id"]

        pending = client.get(f"/performance/benchmark/results/{calculation_id}")
        assert pending.status_code == 202

        assert drain_compute_queue() == 1

        complete = client.get(f"/performance/benchmark/results/{calculation_id}")
        assert complete.status_code == 200
        body = complete.json()
        assert body["input_mode"] == "stateful"
        assert body["return_source"] == "calculated"
        assert body["benchmark_id"] == "BMK_ASYNC_1"
        assert body["results_by_period"]["YTD"]["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(
            3.0301
        )
        assert body["results_by_period"]["YTD"]["benchmark"]["breakdowns"]["daily"][-1]["cumulative_return"][
            "base"
        ] == pytest.approx(3.0301)
    finally:
        settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.BENCHMARK_EXECUTOR_INPUT_COUNT = original_input_threshold


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
        "stateful_input": {},
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
        "stateful_input": {},
    }

    response = client.post("/performance/benchmark", json=payload)

    assert response.status_code == 200
    body = response.json()
    itd = body["results_by_period"]["ITD"]
    assert body["return_source"] == "vendor_series"
    assert itd["benchmark"]["summary"]["period_return"]["base"] == pytest.approx(3.02)
    assert "component_contributions" not in itd


def test_calculate_benchmark_endpoint_promotes_stateful_benchmark_to_async_on_resolved_workload(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.BENCHMARK_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = 365
    settings.BENCHMARK_EXECUTOR_INPUT_COUNT = 4

    async def _mock_resolve_benchmark_request(request, *, settings):  # noqa: ARG001
        benchmark_request = BenchmarkPerformanceRequest.model_validate(
            {
                "calculation_id": str(request.calculation_id),
                "benchmark_id": request.benchmark_id,
                "benchmark_start_date": "2026-01-02",
                "report_end_date": "2026-01-03",
                "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                "return_source": "calculated",
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "component_return": 0.01},
                    {"component_id": "IDX_B", "perf_date": "2026-01-02", "weight_bop": 0.4, "component_return": 0.02},
                    {"component_id": "IDX_A", "perf_date": "2026-01-03", "weight_bop": 0.6, "component_return": 0.01},
                    {"component_id": "IDX_B", "perf_date": "2026-01-03", "weight_bop": 0.4, "component_return": 0.02},
                ],
            }
        )
        return ResolvedBenchmarkRequest(
            benchmark_request=benchmark_request,
            input_mode=request.input_mode,
            source_details={"benchmark_components": 2},
            input_count=4,
        )

    monkeypatch.setattr("app.api.endpoints.benchmark.resolve_benchmark_request", _mock_resolve_benchmark_request)

    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_STATEFUL_ASYNC",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {},
    }

    try:
        response = client.post("/performance/benchmark", json=payload)

        assert response.status_code == 202
        body = response.json()
        assert body["poll_path"].endswith(payload["calculation_id"])
        pending = client.get(body["result_path"])
        assert pending.status_code == 202
    finally:
        settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.BENCHMARK_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_benchmark_endpoint_generates_calculation_id_for_async_stateful_request(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.BENCHMARK_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = 365
    settings.BENCHMARK_EXECUTOR_INPUT_COUNT = 4

    async def _mock_resolve_benchmark_request(request, *, settings):  # noqa: ARG001
        benchmark_request = BenchmarkPerformanceRequest.model_validate(
            {
                "calculation_id": str(request.calculation_id),
                "benchmark_id": request.benchmark_id,
                "benchmark_start_date": "2026-01-02",
                "report_end_date": "2026-01-03",
                "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                "return_source": "calculated",
                "benchmark_currency": "USD",
                "component_observations": [
                    {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "component_return": 0.01},
                    {"component_id": "IDX_B", "perf_date": "2026-01-02", "weight_bop": 0.4, "component_return": 0.02},
                    {"component_id": "IDX_A", "perf_date": "2026-01-03", "weight_bop": 0.6, "component_return": 0.01},
                    {"component_id": "IDX_B", "perf_date": "2026-01-03", "weight_bop": 0.4, "component_return": 0.02},
                ],
            }
        )
        return ResolvedBenchmarkRequest(
            benchmark_request=benchmark_request,
            input_mode=request.input_mode,
            source_details={"benchmark_components": 2},
            input_count=4,
        )

    monkeypatch.setattr("app.api.endpoints.benchmark.resolve_benchmark_request", _mock_resolve_benchmark_request)

    payload = {
        "benchmark_id": "BMK_GENERATED_ASYNC",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {},
    }

    try:
        response = client.post("/performance/benchmark", json=payload)

        assert response.status_code == 202
        body = response.json()
        generated_calculation_id = body["calculation_id"]
        assert generated_calculation_id
        assert body["poll_path"].endswith(generated_calculation_id)
        assert body["result_path"].endswith(generated_calculation_id)
    finally:
        settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.BENCHMARK_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_benchmark_endpoint_offloads_large_stateless_benchmark_requests(client):
    settings = get_settings()
    original_input_threshold = settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    settings.BENCHMARK_EXECUTOR_INPUT_COUNT = 4

    payload = {
        "benchmark_id": "BMK_STATELESS_ASYNC",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateless",
        "return_source": "calculated",
        "output": {"include_timeseries": True},
        "stateless_input": {
            "benchmark_currency": "USD",
            "component_observations": [
                {"component_id": "IDX_A", "perf_date": "2026-01-02", "weight_bop": 0.6, "component_return": 0.02},
                {"component_id": "IDX_B", "perf_date": "2026-01-02", "weight_bop": 0.4, "component_return": 0.01},
                {"component_id": "IDX_A", "perf_date": "2026-01-03", "weight_bop": 0.6, "component_return": 0.01},
                {"component_id": "IDX_B", "perf_date": "2026-01-03", "weight_bop": 0.4, "component_return": 0.005},
            ],
        },
    }

    try:
        accepted = client.post("/performance/benchmark", json=payload)

        assert accepted.status_code == 202
        body = accepted.json()
        calculation_id = body["calculation_id"]
        assert body["poll_path"].endswith(calculation_id)
        assert body["result_path"].endswith(calculation_id)

        pending = client.get(body["result_path"])
        assert pending.status_code == 202

        assert drain_compute_queue() == 1

        complete = client.get(body["result_path"])
        assert complete.status_code == 200
        result_body = complete.json()
        assert result_body["input_mode"] == "stateless"
        assert result_body["benchmark_id"] == "BMK_STATELESS_ASYNC"
        assert result_body["results_by_period"]["ITD"]["benchmark"]["summary"]["period_return"][
            "base"
        ] == pytest.approx(2.4128)
    finally:
        settings.BENCHMARK_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_benchmark_async_result_missing_and_failed_contracts(client, monkeypatch):
    settings = get_settings()
    original_window_threshold = settings.BENCHMARK_EXECUTOR_WINDOW_DAYS
    original_attempts = settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS
    settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = 0
    settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = 1

    monkeypatch.setattr(
        "app.workers.compute_executor_worker.calculate_benchmark_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("explode")),
    )

    payload = {
        "benchmark_id": "BMK_ASYNC_FAIL",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {},
    }

    try:
        missing = client.get(f"/performance/benchmark/results/{uuid4()}")
        assert missing.status_code == 404

        accepted = client.post("/performance/benchmark", json=payload)
        assert accepted.status_code == 202
        calculation_id = accepted.json()["calculation_id"]

        from app.services.compute_job_store import compute_job_store

        compute_job_store.mark_failed(UUID(calculation_id), error_message="explode")
        failed = client.get(f"/performance/benchmark/results/{calculation_id}")
        assert failed.status_code == 409
        assert failed.json()["detail"] == "explode"
    finally:
        settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = original_attempts
