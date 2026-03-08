import os
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from main import app
from tests.conftest import drain_compute_queue, drain_lineage_queue

settings = get_settings()


@pytest.fixture()
def client():
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    compute_job_store.create_schema()
    compute_job_store.clear_all_records()
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app) as c:
        yield c

    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    compute_job_store.clear_all_records()
    execution_registry.clear_all_records()
    lineage_metadata_store.clear_all_records()


def test_execution_api_tracks_twr_and_lineage_completion(client):
    payload = {
        "portfolio_id": "EXEC_TEST",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"day": 1, "perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1010.0}],
    }

    twr_response = client.post("/performance/twr", json=payload)

    assert twr_response.status_code == 200
    calculation_id = twr_response.json()["calculation_id"]

    execution_response = client.get(f"/performance/executions/{calculation_id}")
    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["status"] == "complete"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["execution"]["status"] == "complete"
    assert stages["lineage_materialization"]["status"] == "in_progress"

    assert drain_lineage_queue() >= 1

    execution_response_after_worker = client.get(f"/performance/executions/{calculation_id}")
    assert execution_response_after_worker.status_code == 200
    execution_body_after_worker = execution_response_after_worker.json()
    stages_after_worker = {stage["stage_name"]: stage for stage in execution_body_after_worker["stages"]}
    assert stages_after_worker["lineage_materialization"]["status"] == "complete"
    assert "request.json" in stages_after_worker["lineage_materialization"]["details"]["artifact_names"]


def test_execution_api_returns_404_for_missing_calculation(client):
    response = client.get(f"/performance/executions/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Execution data not found for the given calculation_id."


def test_execution_api_tracks_returns_series_stateful_stages(client, monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1015"},
                    {
                        "valuation_date": "2026-02-25",
                        "beginning_market_value": "1015",
                        "ending_market_value": "1012.46",
                    },
                ],
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_GLOBAL_1"}

    async def _mock_get_benchmark_return_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-02-23", "benchmark_return": "0.0010"},
                    {"series_date": "2026-02-24", "benchmark_return": "0.0012"},
                    {"series_date": "2026-02-25", "benchmark_return": "-0.0004"},
                ]
            },
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.api.endpoints.returns_series.CoreIntegrationService.get_benchmark_return_series",
        _mock_get_benchmark_return_series,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True},
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/integration/returns/series", json=payload)

    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    execution_response = client.get(f"/performance/executions/{calculation_id}")

    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["analytics_type"] == "ReturnsSeries"
    assert execution_body["status"] == "complete"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["retrieval"]["status"] == "complete"
    assert stages["normalization"]["status"] == "complete"
    assert stages["execution"]["status"] == "complete"
    assert stages["retrieval"]["details"]["portfolio_observations"] == 3
    assert stages["normalization"]["details"]["benchmark_points"] == 3
    assert len(execution_body["upstream_snapshots"]) >= 2
    assert {snapshot["upstream_endpoint"] for snapshot in execution_body["upstream_snapshots"]} >= {
        "portfolio_timeseries",
        "benchmark_return_series",
    }


def test_execution_api_tracks_async_returns_series_job_state(client, monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 1

    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2026-02-23",
                "observations": [
                    {"valuation_date": "2026-02-23", "beginning_market_value": "1000", "ending_market_value": "1010"},
                    {"valuation_date": "2026-02-24", "beginning_market_value": "1010", "ending_market_value": "1015"},
                    {
                        "valuation_date": "2026-02-25",
                        "beginning_market_value": "1015",
                        "ending_market_value": "1012.46",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.returns_series_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    try:
        response = client.post("/integration/returns/series", json=payload)
        assert response.status_code == 202
        calculation_id = response.json()["calculation_id"]

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        execution_body = execution_response.json()
        assert execution_body["execution_mode"] == "async"
        assert execution_body["status"] == "pending"
        assert execution_body["compute_job"]["job_status"] == "pending"

        assert drain_compute_queue() == 1

        execution_response_after_worker = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response_after_worker.status_code == 200
        execution_body_after_worker = execution_response_after_worker.json()
        assert execution_body_after_worker["status"] == "complete"
        assert execution_body_after_worker["compute_job"]["job_status"] == "complete"
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_execution_api_tracks_async_contribution_job_state(client, happy_path_payload):
    original_threshold = settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT
    settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = 0

    try:
        response = client.post("/performance/contribution", json=happy_path_payload)
        assert response.status_code == 202
        calculation_id = response.json()["calculation_id"]

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        execution_body = execution_response.json()
        assert execution_body["analytics_type"] == "Contribution"
        assert execution_body["execution_mode"] == "async"
        assert execution_body["status"] == "pending"
        assert execution_body["compute_job"]["job_status"] == "pending"
        submission_stage = {stage["stage_name"]: stage for stage in execution_body["stages"]}["submission"]
        assert submission_stage["status"] == "complete"

        assert drain_compute_queue() == 1

        execution_after_worker = client.get(f"/performance/executions/{calculation_id}")
        assert execution_after_worker.status_code == 200
        execution_body_after_worker = execution_after_worker.json()
        assert execution_body_after_worker["status"] == "complete"
        assert execution_body_after_worker["compute_job"]["job_status"] == "complete"
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold
