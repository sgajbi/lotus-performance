import os
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.async_result_store import async_result_store
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


def test_twr_inspection_request_subject_runs_through_async_runtime_and_artifacts(client):
    inspection_id = str(uuid4())
    payload = {
        "inspection_id": inspection_id,
        "subject_type": "twr_request",
        "inspection_profile": "canonical_validation",
        "request": {
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "performance_start_date": "2026-01-01",
            "metric_basis": "NET",
            "report_end_date": "2026-01-02",
            "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1005.0},
            ],
        },
    }

    submit = client.post("/performance/inspections/twr", json=payload)
    assert submit.status_code == 202
    assert submit.json()["inspection_id"] == inspection_id
    assert submit.json()["result_path"] == f"/performance/inspections/{inspection_id}"

    pending = client.get(f"/performance/inspections/{inspection_id}")
    assert pending.status_code == 202

    assert drain_compute_queue() >= 1

    execution_response = client.get(f"/performance/executions/{inspection_id}")
    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    assert execution_body["analytics_type"] == "TWR_INSPECTION"
    assert execution_body["status"] == "complete"
    stages = {stage["stage_name"]: stage for stage in execution_body["stages"]}
    assert stages["subject_resolution"]["status"] == "complete"
    assert stages["finding_synthesis"]["status"] == "complete"
    assert stages["artifact_materialization"]["status"] == "in_progress"

    result = client.get(f"/performance/inspections/{inspection_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["inspection_id"] == inspection_id
    assert body["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert body["verdict"] == "inspection_failed"
    assert body["check_coverage"]["completed_check_families"] == []
    assert "calculation_consistency" in body["check_coverage"]["pending_check_families"]
    assert body["artifacts"]["inspection_summary.json"].endswith("/inspection_summary.json")

    assert drain_lineage_queue() >= 1

    execution_after_lineage = client.get(f"/performance/executions/{inspection_id}")
    stages_after_lineage = {
        stage["stage_name"]: stage for stage in execution_after_lineage.json()["stages"]
    }
    assert stages_after_lineage["artifact_materialization"]["status"] == "complete"
    assert "inspection_summary.json" in stages_after_lineage["artifact_materialization"]["details"]["artifact_names"]

    artifact = client.get(f"/performance/inspections/{inspection_id}/artifacts/inspection_summary.json")
    assert artifact.status_code == 200
    assert artifact.json()["inspection_id"] == inspection_id
    artifact.close()


def test_twr_inspection_existing_calculation_subject_links_back_to_twr_lineage(client):
    twr_payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "performance_start_date": "2026-01-01",
        "metric_basis": "NET",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [
            {"perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1005.0},
        ],
    }
    twr_response = client.post("/performance/twr", json=twr_payload)
    assert twr_response.status_code == 200
    twr_calculation_id = twr_response.json()["calculation_id"]

    inspection_id = str(uuid4())
    submit = client.post(
        "/performance/inspections/twr",
        json={
            "inspection_id": inspection_id,
            "subject_type": "twr_calculation",
            "subject_calculation_id": twr_calculation_id,
            "inspection_profile": "support_triage",
        },
    )
    assert submit.status_code == 202

    assert drain_compute_queue() >= 1

    result = client.get(f"/performance/inspections/{inspection_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["subject_calculation_id"] == twr_calculation_id
    assert body["related_lineage"]["calculation_id"] == twr_calculation_id
    assert body["related_lineage"]["lineage_path"] == f"/performance/lineage/{twr_calculation_id}"
    assert body["evidence_summary"]["related_execution_found"] is True


def test_twr_inspection_reports_failure_for_missing_twr_subject(client):
    inspection_id = str(uuid4())
    submit = client.post(
        "/performance/inspections/twr",
        json={
            "inspection_id": inspection_id,
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(uuid4()),
            "inspection_profile": "support_triage",
        },
    )
    assert submit.status_code == 202

    assert drain_compute_queue() >= 1

    result = client.get(f"/performance/inspections/{inspection_id}")
    assert result.status_code == 409
    assert "TWR calculation execution not found" in result.json()["detail"]

    execution_response = client.get(f"/performance/executions/{inspection_id}")
    assert execution_response.status_code == 200
    stages = {stage["stage_name"]: stage for stage in execution_response.json()["stages"]}
    assert stages["subject_resolution"]["status"] == "failed"
