import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app


def test_runtime_retention_history_api_reports_unavailable_when_manifest_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "RUNTIME_RETENTION_ARTIFACT_PATH", tmp_path / "missing")

    with TestClient(app) as client:
        response = client.get("/integration/runtime-retention-cleanups")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "runtime_retention_artifact_directory_missing"


def test_runtime_retention_history_api_rejects_invalid_time_filter():
    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-retention-cleanups",
            params={"generated_after": "not-a-timestamp"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_utc_timestamp_filter",
        "field": "generated_after",
        "message": "generated_after must be an ISO-8601 UTC timestamp.",
    }


def test_runtime_retention_history_api_rejects_inverted_time_window():
    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-retention-cleanups",
            params={
                "generated_after": "2026-03-16T00:00:00Z",
                "generated_before": "2026-03-15T00:00:00Z",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_utc_timestamp_filter_window",
        "fields": ["generated_after", "generated_before"],
        "message": "generated_after must be less than or equal to generated_before.",
    }


def test_runtime_retention_history_api_rejects_blank_string_filters():
    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-retention-cleanups",
            params={
                "operator_id": " ",
                "trigger_mode": "  ",
                "job_id": " ",
                "cleanup_mode": "  ",
                "status": " ",
            },
        )

    assert response.status_code == 422
    fields = {item["loc"][-1] for item in response.json()["detail"]}
    assert {"operator_id", "trigger_mode", "job_id", "cleanup_mode", "status"} <= fields


def test_runtime_retention_history_api_returns_filtered_manifest(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-15t00-00-00z.json",
        "retained_file_names": [
            "2026-03-15t00-00-00z.json",
            "2026-03-14t00-00-00z.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-15t00-00-00z.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": "ops-user",
                "trigger_mode": "scheduled",
                "job_id": "retention-nightly",
                "cleanup_mode": "apply",
                "status": "applied",
                "retention_days": 45,
                "prunable_execution_count": 2,
                "prunable_compute_job_count": 2,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 2,
                "prunable_lineage_artifact_count": 2,
            },
            {
                "evidence_file_name": "2026-03-14t00-00-00z.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "trigger_mode": "manual",
                "job_id": None,
                "cleanup_mode": "dry_run",
                "status": "planned",
                "retention_days": 30,
                "prunable_execution_count": 3,
                "prunable_compute_job_count": 3,
                "prunable_async_result_count": 3,
                "prunable_lineage_record_count": 3,
                "prunable_lineage_artifact_count": 3,
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get(
            "/integration/runtime-retention-cleanups",
            params={
                "cleanup_mode": " apply ",
                "trigger_mode": " scheduled ",
                "job_id": " retention-nightly ",
                "status": " applied ",
                "limit": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["total_entries"] == 2
    assert body["matched_entries"] == 1
    assert body["returned_entries"] == 1
    assert body["applied_filters"] == {
        "limit": 1,
        "trigger_mode": "scheduled",
        "job_id": "retention-nightly",
        "cleanup_mode": "apply",
        "status": "applied",
    }
    assert body["entries"] == [
        {
            "evidence_file_name": "2026-03-15t00-00-00z.json",
            "generated_at_utc": "2026-03-15T00:00:00Z",
            "operator_id": "ops-user",
            "trigger_mode": "scheduled",
            "job_id": "retention-nightly",
            "cleanup_mode": "apply",
            "status": "applied",
            "retention_days": 45,
            "prunable_execution_count": 2,
            "prunable_compute_job_count": 2,
            "prunable_async_result_count": 2,
            "prunable_lineage_record_count": 2,
            "prunable_lineage_artifact_count": 2,
        }
    ]
