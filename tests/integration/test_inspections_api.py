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
    assert body["verdict"] == "supportable_with_warnings"
    assert body["check_coverage"]["completed_check_families"] == ["calculation_consistency"]
    assert body["findings"] == []
    assert body["subject_calculation_id"] == twr_calculation_id
    assert body["related_lineage"]["calculation_id"] == twr_calculation_id
    assert body["related_lineage"]["lineage_path"] == f"/performance/lineage/{twr_calculation_id}"
    assert body["evidence_summary"]["related_execution_found"] is True


def test_twr_inspection_flags_relative_arithmetic_mismatch_for_existing_calculation(client):
    twr_payload = {
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "performance_start_date": "2026-01-01",
        "metric_basis": "NET",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "include_benchmark": True,
        "valuation_points": [
            {"perf_date": "2026-01-01", "begin_mv": 1000.0, "end_mv": 1010.0},
            {"perf_date": "2026-01-02", "begin_mv": 1010.0, "end_mv": 1020.1},
        ],
        "benchmark": {
            "benchmark_id": "BMK_GLOBAL_60_40",
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2026-01-01", "benchmark_return": 0.005},
                    {"perf_date": "2026-01-02", "benchmark_return": 0.004},
                ],
            },
        },
    }
    twr_response = client.post("/performance/twr", json=twr_payload)
    assert twr_response.status_code == 200
    twr_body = twr_response.json()
    tampered_calculation_id = uuid4()
    execution_registry.create_execution(
        calculation_id=tampered_calculation_id,
        analytics_type="TWR",
        portfolio_id=twr_body["portfolio_id"],
        execution_mode="sync",
        requested_window={"requested_periods": ["YTD"]},
        input_fingerprint="tampered",
        calculation_hash="tampered",
    )
    tampered_body = dict(twr_body)
    tampered_results = dict(twr_body["results_by_period"])
    tampered_ytd = dict(tampered_results["YTD"])
    tampered_relative = dict(tampered_ytd["relative_performance"])
    tampered_summary = dict(tampered_relative["summary"])
    tampered_period_return = dict(tampered_summary["period_return"])
    tampered_period_return["base"] = tampered_period_return["base"] + 0.25
    tampered_summary["period_return"] = tampered_period_return
    tampered_relative["summary"] = tampered_summary
    tampered_ytd["relative_performance"] = tampered_relative
    tampered_results["YTD"] = tampered_ytd
    tampered_body["results_by_period"] = tampered_results
    tampered_body["calculation_id"] = str(tampered_calculation_id)
    async_result_store.record_success(
        calculation_id=tampered_calculation_id,
        analytics_type="TWR",
        response_payload=tampered_body,
    )

    inspection_id = str(uuid4())
    submit = client.post(
        "/performance/inspections/twr",
        json={
            "inspection_id": inspection_id,
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(tampered_calculation_id),
            "inspection_profile": "support_triage",
        },
    )
    assert submit.status_code == 202

    assert drain_compute_queue() >= 1

    result = client.get(f"/performance/inspections/{inspection_id}")
    assert result.status_code == 200
    body = result.json()
    assert body["verdict"] == "not_supportable"
    assert body["check_coverage"]["completed_check_families"] == ["calculation_consistency"]
    assert {finding["code"] for finding in body["findings"]} >= {"RELATIVE_PERFORMANCE_SUMMARY_MISMATCH"}


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
