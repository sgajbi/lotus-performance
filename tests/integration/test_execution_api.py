import os
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services.async_result_store import async_result_store
from app.services.benchmark_mode_service import ResolvedBenchmarkRequest
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.returns_series_service import ResolvedStatefulReturnsSeriesRequest
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
    async_result_store.create_schema()
    async_result_store.clear_all_records()
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app) as c:
        yield c

    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    compute_job_store.clear_all_records()
    async_result_store.clear_all_records()
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

    async def _mock_get_benchmark_composition_window(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "benchmark_id": "BMK_GLOBAL_1",
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX1",
                        "composition_weight": "1.0",
                        "composition_effective_from": "2026-02-01",
                        "composition_effective_to": "2026-02-28",
                    }
                ]
            },
        )

    async def _mock_get_index_price_series(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-02-22", "index_price": "100.0", "series_currency": "USD"},
                    {"series_date": "2026-02-23", "index_price": "100.1", "series_currency": "USD"},
                    {"series_date": "2026-02-24", "index_price": "100.22012", "series_currency": "USD"},
                    {"series_date": "2026-02-25", "index_price": "100.180031952", "series_currency": "USD"},
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )

    monkeypatch.setattr(
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_benchmark_composition_window",
        _mock_get_benchmark_composition_window,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_index_price_series",
        _mock_get_index_price_series,
    )

    payload = {
        "portfolio_id": "DEMO_DPM_EUR_001",
        "as_of_date": "2026-02-25",
        "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
        "frequency": "DAILY",
        "metric_basis": "NET",
        "series_selection": {"include_portfolio": True, "include_benchmark": True},
        "benchmark": {"benchmark_id": "BMK_GLOBAL_1"},
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
    assert stages["retrieval"]["details"]["portfolio_chunk_count"] == 1
    assert stages["retrieval"]["details"]["portfolio_page_count"] == 1
    assert stages["retrieval"]["details"]["benchmark_chunk_count"] == 1
    assert stages["retrieval"]["details"]["benchmark_page_count"] == 1
    assert stages["retrieval"]["details"]["risk_free_chunk_count"] == 0
    assert stages["normalization"]["details"]["benchmark_points"] == 3
    assert len(execution_body["upstream_snapshots"]) >= 2
    assert {snapshot["upstream_endpoint"] for snapshot in execution_body["upstream_snapshots"]} >= {
        "portfolio_timeseries",
        "benchmark_composition_window",
        "index_price_series",
    }


def test_execution_api_tracks_twr_stateful_stages(client, monkeypatch):
    async def _mock_get_portfolio_analytics_timeseries(self, **kwargs):  # noqa: ARG001
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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_analytics_timeseries,
    )

    payload = {
        "portfolio_id": "STATEFUL_EXEC_TWR",
        "performance_start_date": "2024-12-31",
        "metric_basis": "NET",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    twr_response = client.post("/performance/twr", json=payload)

    assert twr_response.status_code == 200
    calculation_id = twr_response.json()["calculation_id"]
    execution_response = client.get(f"/performance/executions/{calculation_id}")

    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["analytics_type"] == "TWR"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["retrieval"]["status"] == "complete"
    assert stages["normalization"]["status"] == "complete"
    assert stages["execution"]["status"] == "complete"
    assert stages["retrieval"]["details"]["portfolio_observations"] == 2
    assert stages["retrieval"]["details"]["portfolio_chunk_count"] == 1
    assert stages["retrieval"]["details"]["portfolio_page_count"] == 1
    assert stages["normalization"]["details"]["valuation_points"] == 2
    assert len(execution_body["upstream_snapshots"]) >= 1
    assert execution_body["upstream_snapshots"][0]["upstream_endpoint"] == "portfolio_timeseries"


def test_execution_api_tracks_mwr_stateful_stages(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "100000",
                        "ending_market_value": "110000",
                        "cash_flows": [{"amount": "10000", "timing": "bod"}],
                    },
                    {
                        "valuation_date": "2025-01-03",
                        "beginning_market_value": "110000",
                        "ending_market_value": "111000",
                        "cash_flows": [],
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_timeseries,
    )

    payload = {
        "portfolio_id": "MWR_STATEFUL_EXEC",
        "as_of": "2025-01-03",
        "mwr_method": "DIETZ",
        "input_mode": "stateful",
        "stateful_input": {
            "consumer_system": "lotus-performance",
            "window_start_date": "2025-01-01",
        },
    }

    response = client.post("/performance/mwr", json=payload)

    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    execution_response = client.get(f"/performance/executions/{calculation_id}")

    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["analytics_type"] == "MWR"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["retrieval"]["status"] == "complete"
    assert stages["normalization"]["status"] == "complete"
    assert stages["execution"]["status"] == "complete"
    assert stages["retrieval"]["details"]["portfolio_observations"] == 2
    assert stages["retrieval"]["details"]["portfolio_chunk_count"] == 1
    assert stages["retrieval"]["details"]["portfolio_page_count"] == 1
    assert stages["normalization"]["details"]["cashflows"] == 1
    assert len(execution_body["upstream_snapshots"]) >= 1
    assert execution_body["upstream_snapshots"][0]["upstream_endpoint"] == "portfolio_timeseries"


def test_execution_api_tracks_contribution_stateful_stages(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020.1",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "SEC_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "1000",
                        "ending_market_value_portfolio_currency": "1010",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "SEC_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "1010",
                        "ending_market_value_portfolio_currency": "1020.1",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_portfolio_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.stateful_input_service.StatefulInputService.get_position_timeseries",
        _mock_get_position_timeseries,
    )

    payload = {
        "portfolio_id": "CONTRIB_STATEFUL_EXEC",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/contribution", json=payload)

    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    execution_response = client.get(f"/performance/executions/{calculation_id}")

    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["analytics_type"] == "Contribution"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["retrieval"]["status"] == "complete"
    assert stages["normalization"]["status"] == "complete"
    assert stages["execution"]["status"] == "complete"
    assert stages["retrieval"]["details"]["portfolio_observations"] == 2
    assert stages["retrieval"]["details"]["position_rows"] == 2
    assert stages["retrieval"]["details"]["portfolio_chunk_count"] == 1
    assert stages["retrieval"]["details"]["portfolio_page_count"] == 1
    assert stages["retrieval"]["details"]["position_chunk_count"] == 1
    assert stages["retrieval"]["details"]["position_page_count"] == 1
    assert stages["normalization"]["details"]["portfolio_points"] == 2
    assert stages["normalization"]["details"]["positions"] == 1


def test_execution_api_tracks_attribution_stateful_stages(client, monkeypatch):
    async def _mock_get_portfolio_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "portfolio_open_date": "2025-01-01",
                "observations": [
                    {
                        "valuation_date": "2025-01-01",
                        "beginning_market_value": "1000",
                        "ending_market_value": "1010",
                    },
                    {
                        "valuation_date": "2025-01-02",
                        "beginning_market_value": "1010",
                        "ending_market_value": "1020.1",
                    },
                ],
            },
        )

    async def _mock_get_position_timeseries(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-01",
                        "beginning_market_value_portfolio_currency": "1000",
                        "ending_market_value_portfolio_currency": "1010",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                    {
                        "position_id": "POS_1",
                        "security_id": "SEC_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "1010",
                        "ending_market_value_portfolio_currency": "1020.1",
                        "cash_flows": [],
                        "dimensions": {"sector": "Technology"},
                    },
                ]
            },
        )

    async def _mock_get_benchmark_assignment(self, **kwargs):  # noqa: ARG001
        return 200, {"benchmark_id": "BMK_1"}

    async def _mock_get_benchmark_composition_window(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "benchmark_id": "BMK_1",
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX_1",
                        "composition_weight": "1.0",
                        "composition_effective_from": "2025-01-01",
                    }
                ],
            },
        )

    async def _mock_get_index_price_series(self, index_id, **kwargs):  # noqa: ARG001
        assert index_id == "IDX_1"
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

    async def _mock_get_index_catalog(self, **kwargs):  # noqa: ARG001
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_1",
                        "classification_labels": {"sector": "Technology"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
        _mock_get_portfolio_timeseries,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_position_analytics_timeseries",
        _mock_get_position_timeseries,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_benchmark_assignment",
        _mock_get_benchmark_assignment,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_benchmark_composition_window",
        _mock_get_benchmark_composition_window,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_index_price_series",
        _mock_get_index_price_series,
    )
    monkeypatch.setattr(
        "app.services.core_integration_service.CoreIntegrationService.get_index_catalog",
        _mock_get_index_catalog,
    )

    payload = {
        "portfolio_id": "ATTRIB_STATEFUL_EXEC",
        "mode": "by_instrument",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    response = client.post("/performance/attribution", json=payload)

    assert response.status_code == 200
    calculation_id = response.json()["calculation_id"]
    execution_response = client.get(f"/performance/executions/{calculation_id}")

    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["analytics_type"] == "Attribution"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["retrieval"]["status"] == "complete"
    assert stages["normalization"]["status"] == "complete"
    assert stages["execution"]["status"] == "complete"
    assert stages["retrieval"]["details"]["portfolio_observations"] == 2
    assert stages["retrieval"]["details"]["position_rows"] == 2
    assert stages["retrieval"]["details"]["benchmark_components"] == 1
    assert stages["retrieval"]["details"]["portfolio_chunk_count"] == 1
    assert stages["retrieval"]["details"]["portfolio_page_count"] == 1
    assert stages["retrieval"]["details"]["position_chunk_count"] == 1
    assert stages["retrieval"]["details"]["position_page_count"] == 1
    assert stages["retrieval"]["details"]["benchmark_chunk_count"] == 1
    assert stages["retrieval"]["details"]["benchmark_page_count"] == 1
    assert stages["retrieval"]["details"]["benchmark_component_observations"] == 2
    assert stages["retrieval"]["details"]["index_request_count"] == 1
    assert stages["normalization"]["details"]["portfolio_points"] == 2
    assert stages["normalization"]["details"]["instruments"] == 1
    assert stages["normalization"]["details"]["benchmark_groups"] == 1
    assert {snapshot["upstream_endpoint"] for snapshot in execution_body["upstream_snapshots"]} >= {
        "portfolio_timeseries",
        "position_timeseries",
        "benchmark_assignment",
        "benchmark_composition_window",
        "index_price_series",
        "index_catalog",
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
        "app.services.portfolio_source_service.CoreIntegrationService.get_portfolio_analytics_timeseries",
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
        assert execution_body["compute_job"]["max_attempts"] == settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS

        assert drain_compute_queue() == 1

        execution_response_after_worker = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response_after_worker.status_code == 200
        execution_body_after_worker = execution_response_after_worker.json()
        assert execution_body_after_worker["status"] == "complete"
        assert execution_body_after_worker["compute_job"]["job_status"] == "complete"
        assert execution_body_after_worker["compute_job"]["worker_id"] == settings.COMPUTE_EXECUTOR_WORKER_ID
        assert execution_body_after_worker["async_result"]["result_status"] == "complete"
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold


def test_execution_api_tracks_resolved_async_returns_series_job_state(client, monkeypatch):
    original_window_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 30
    settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT = 3

    async def _mock_resolve_stateful_returns_series_request(request):  # noqa: ARG001
        return ResolvedStatefulReturnsSeriesRequest(
            request=type(request).model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "portfolio_id": request.portfolio_id,
                    "as_of_date": "2026-02-25",
                    "window": {"mode": "EXPLICIT", "from_date": "2026-02-23", "to_date": "2026-02-25"},
                    "frequency": "DAILY",
                    "metric_basis": "NET",
                    "input_mode": "stateless",
                    "stateless_input": {
                        "portfolio_returns": [
                            {"date": "2026-02-23", "return_value": "0.0100"},
                            {"date": "2026-02-24", "return_value": "0.0050"},
                            {"date": "2026-02-25", "return_value": "-0.0025"},
                        ],
                        "benchmark_returns": [
                            {"date": "2026-02-23", "return_value": "0.0010"},
                            {"date": "2026-02-24", "return_value": "0.0012"},
                            {"date": "2026-02-25", "return_value": "0.0014"},
                        ],
                    },
                }
            ),
            identity_payload={
                "portfolio_id": request.portfolio_id,
                "as_of_date": "2026-02-25",
                "resolved_window": {
                    "start_date": "2026-02-23",
                    "end_date": "2026-02-25",
                    "resolved_period_label": None,
                },
                "frequency": "DAILY",
                "metric_basis": "NET",
                "reporting_currency": None,
                "series_selection": {
                    "include_portfolio": True,
                    "include_benchmark": True,
                    "include_risk_free": False,
                },
                "benchmark": {
                    "benchmark_id": "BMK_RESOLVED",
                    "return_source": "calculated",
                },
                "risk_free": None,
                "data_policy": {
                    "missing_data_policy": "FAIL_FAST",
                    "fill_method": "NONE",
                    "calendar_policy": "BUSINESS",
                    "max_gap_days": None,
                },
                "input_mode": "stateless",
                "stateless_input": {
                    "portfolio_returns": [
                        {"date": "2026-02-23", "return_value": "0.0100"},
                        {"date": "2026-02-24", "return_value": "0.0050"},
                        {"date": "2026-02-25", "return_value": "-0.0025"},
                    ],
                    "benchmark_returns": [
                        {"date": "2026-02-23", "return_value": "0.0010"},
                        {"date": "2026-02-24", "return_value": "0.0012"},
                        {"date": "2026-02-25", "return_value": "0.0014"},
                    ],
                    "risk_free_returns": None,
                },
            },
            input_count=5,
            resolved_benchmark_id="BMK_RESOLVED",
            resolved_benchmark_return_source="calculated",
            benchmark_work_units=5,
        )

    monkeypatch.setattr(
        "app.api.endpoints.returns_series.resolve_stateful_returns_series_request",
        _mock_resolve_stateful_returns_series_request,
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

    try:
        response = client.post("/integration/returns/series", json=payload)
        assert response.status_code == 202
        calculation_id = response.json()["calculation_id"]

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        body = execution_response.json()
        assert body["execution_mode"] == "async"
        assert body["requested_window"]["input_count"] == 5
        assert body["requested_window"]["benchmark_id"] == "BMK_RESOLVED"
        assert body["requested_window"]["benchmark_return_source"] == "calculated"
        assert body["requested_window"]["benchmark_work_units"] == 5

        assert drain_compute_queue() == 1
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.RETURNS_SERIES_EXECUTOR_INPUT_COUNT = original_input_threshold


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
        assert execution_body_after_worker["compute_job"]["attempt_count"] == 1
        assert execution_body_after_worker["async_result"]["result_status"] == "complete"
    finally:
        settings.CONTRIBUTION_EXECUTOR_POSITION_COUNT = original_threshold


def test_execution_api_tracks_async_attribution_job_state(client):
    original_threshold = settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT
    settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = 0
    payload = {
        "portfolio_id": "ATTRIB_EXEC_01",
        "mode": "by_group",
        "group_by": ["sector"],
        "linking": "none",
        "frequency": "daily",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-01",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "portfolio_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.015, "weight_bop": 1.0}],
            }
        ],
        "benchmark_groups_data": [
            {
                "key": {"sector": "Tech"},
                "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
            }
        ],
    }

    try:
        response = client.post("/performance/attribution", json=payload)
        assert response.status_code == 202
        calculation_id = response.json()["calculation_id"]

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        execution_body = execution_response.json()
        assert execution_body["analytics_type"] == "Attribution"
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
        assert execution_body_after_worker["async_result"]["result_status"] == "complete"
    finally:
        settings.ATTRIBUTION_EXECUTOR_INPUT_COUNT = original_threshold


def test_execution_api_tracks_async_benchmark_job_state(client, monkeypatch):
    original_window_threshold = settings.BENCHMARK_EXECUTOR_WINDOW_DAYS
    original_input_threshold = settings.BENCHMARK_EXECUTOR_INPUT_COUNT
    settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = 365
    settings.BENCHMARK_EXECUTOR_INPUT_COUNT = 4

    async def _mock_resolve_benchmark_request(request, *, settings):  # noqa: ARG001
        return ResolvedBenchmarkRequest(
            benchmark_request=BenchmarkPerformanceRequest.model_validate(
                {
                    "calculation_id": str(request.calculation_id),
                    "benchmark_id": request.benchmark_id,
                    "benchmark_start_date": "2026-01-02",
                    "report_end_date": "2026-01-03",
                    "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
                    "return_source": "calculated",
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {"component_id": "IDX_A", "date": "2026-01-02", "weight_bop": 0.6, "component_return": 0.01},
                        {"component_id": "IDX_B", "date": "2026-01-02", "weight_bop": 0.4, "component_return": 0.02},
                        {"component_id": "IDX_A", "date": "2026-01-03", "weight_bop": 0.6, "component_return": 0.01},
                        {"component_id": "IDX_B", "date": "2026-01-03", "weight_bop": 0.4, "component_return": 0.02},
                    ],
                }
            ),
            input_mode=request.input_mode,
            source_details={"benchmark_components": 2},
            input_count=4,
        )

    monkeypatch.setattr("app.api.endpoints.benchmark.resolve_benchmark_request", _mock_resolve_benchmark_request)

    payload = {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_ASYNC_EXEC",
        "benchmark_start_date": "2026-01-02",
        "report_end_date": "2026-01-03",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "return_source": "calculated",
        "stateful_input": {"consumer_system": "lotus-performance"},
    }

    try:
        response = client.post("/performance/benchmark", json=payload)
        assert response.status_code == 202
        calculation_id = response.json()["calculation_id"]

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        body = execution_response.json()
        assert body["analytics_type"] == "BENCHMARK"
        assert body["execution_mode"] == "async"
        assert body["requested_window"]["input_count"] == 4
        assert body["compute_job"]["job_status"] == "pending"

        assert drain_compute_queue() == 1

        execution_after_worker = client.get(f"/performance/executions/{calculation_id}")
        assert execution_after_worker.status_code == 200
        body_after_worker = execution_after_worker.json()
        assert body_after_worker["status"] == "complete"
        assert body_after_worker["compute_job"]["job_status"] == "complete"
        assert body_after_worker["async_result"]["result_status"] == "complete"
    finally:
        settings.BENCHMARK_EXECUTOR_WINDOW_DAYS = original_window_threshold
        settings.BENCHMARK_EXECUTOR_INPUT_COUNT = original_input_threshold


def test_execution_api_exposes_retryable_compute_job_metadata(client, monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    original_attempts = settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0
    settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = 2

    async def _boom(_request):
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="temporary upstream issue")

    monkeypatch.setattr("app.workers.compute_executor_worker.calculate_returns_series", _boom)

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

        assert drain_compute_queue() == 1

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        body = execution_response.json()
        job = body["compute_job"]
        assert job["job_status"] == "pending"
        assert job["attempt_count"] == 1
        assert job["error_type"] == "HTTPException"
        assert job["last_error_at_utc"] is not None
        assert job.get("lease_expires_at_utc") is None
        assert "async_result" not in body
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold
        settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = original_attempts


def test_execution_api_exposes_terminal_async_result_metadata(client, monkeypatch):
    original_threshold = settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS
    original_attempts = settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS
    settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = 0
    settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = 1

    async def _boom(_request):
        raise RuntimeError("explode")

    monkeypatch.setattr("app.workers.compute_executor_worker.calculate_returns_series", _boom)

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

        assert drain_compute_queue() == 1

        execution_response = client.get(f"/performance/executions/{calculation_id}")
        assert execution_response.status_code == 200
        body = execution_response.json()
        assert body["status"] == "failed"
        assert body["async_result"]["result_status"] == "failed"
        assert body["async_result"]["error_message"] == "explode"
        assert body["async_result"]["error_type"] == "RuntimeError"
    finally:
        settings.RETURNS_SERIES_EXECUTOR_WINDOW_DAYS = original_threshold
        settings.COMPUTE_EXECUTOR_MAX_ATTEMPTS = original_attempts
