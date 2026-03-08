import os
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from main import app
from tests.conftest import drain_lineage_queue

settings = get_settings()


@pytest.fixture()
def client():
    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
    os.makedirs(settings.LINEAGE_STORAGE_PATH, exist_ok=True)
    execution_registry.create_schema()
    execution_registry.clear_all_records()
    lineage_metadata_store.create_schema()
    lineage_metadata_store.clear_all_records()

    with TestClient(app) as c:
        yield c

    if os.path.exists(settings.LINEAGE_STORAGE_PATH):
        shutil.rmtree(settings.LINEAGE_STORAGE_PATH)
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
