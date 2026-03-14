import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app


def test_recovery_drill_history_api_reports_unavailable_when_manifest_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", tmp_path / "missing")

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["status"] == "unavailable"
    assert body["reason"] == "recovery_drill_artifact_directory_missing"


def test_recovery_drill_history_api_returns_retained_manifest(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": ["2026-03-14t00-00-00.json", "2026-03-13t00-00-00.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "failed",
            }
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["latest_file_name"] == "2026-03-14t00-00-00.json"
    assert body["retention_limit"] == 30
    assert body["retention_max_age_days"] == 90
    assert body["total_entries"] == 2
    assert body["matched_entries"] == 2
    assert body["returned_entries"] == 2
    assert body["applied_filters"] == {}
    assert body["entries"] == [
        {
            "evidence_file_name": "2026-03-14t00-00-00.json",
            "generated_at_utc": "2026-03-14T00:00:00Z",
            "operator_id": "ops-user",
            "backup_identifier": "backup-123",
            "status": "passed",
        },
        {
            "evidence_file_name": "2026-03-13t00-00-00.json",
            "generated_at_utc": "2026-03-13T00:00:00Z",
            "operator_id": "ops-user",
            "backup_identifier": "backup-123",
            "status": "failed",
        }
    ]


def test_recovery_drill_history_api_applies_filters_and_limit(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": [
            "2026-03-14t00-00-00.json",
            "2026-03-13t00-00-00.json",
            "2026-03-12t00-00-00.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "failed",
            },
            {
                "evidence_file_name": "2026-03-12t00-00-00.json",
                "generated_at_utc": "2026-03-12T00:00:00Z",
                "operator_id": "ops-batch",
                "backup_identifier": "backup-999",
                "status": "passed",
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get(
            "/integration/recovery-drills",
            params={
                "limit": 1,
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_entries"] == 3
    assert body["matched_entries"] == 1
    assert body["returned_entries"] == 1
    assert "next_offset" not in body
    assert body["applied_filters"] == {
        "limit": 1,
        "operator_id": "ops-user",
        "backup_identifier": "backup-123",
        "status": "passed",
    }
    assert body["entries"] == [
        {
            "evidence_file_name": "2026-03-14t00-00-00.json",
            "generated_at_utc": "2026-03-14T00:00:00Z",
            "operator_id": "ops-user",
            "backup_identifier": "backup-123",
            "status": "passed",
        }
    ]


def test_recovery_drill_history_api_applies_offset_and_time_window(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": [
            "2026-03-14t00-00-00.json",
            "2026-03-13t00-00-00.json",
            "2026-03-12t00-00-00.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-12t00-00-00.json",
                "generated_at_utc": "2026-03-12T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get(
            "/integration/recovery-drills",
            params={
                "limit": 1,
                "offset": 1,
                "generated_after": "2026-03-12T00:00:00Z",
                "generated_before": "2026-03-14T00:00:00Z",
                "status": "passed",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_entries"] == 3
    assert body["matched_entries"] == 3
    assert body["returned_entries"] == 1
    assert body["next_offset"] == 2
    assert body["applied_filters"] == {
        "limit": 1,
        "offset": 1,
        "generated_after": "2026-03-12T00:00:00Z",
        "generated_before": "2026-03-14T00:00:00Z",
        "status": "passed",
    }
    assert body["entries"] == [
        {
            "evidence_file_name": "2026-03-13t00-00-00.json",
            "generated_at_utc": "2026-03-13T00:00:00Z",
            "operator_id": "ops-user",
            "backup_identifier": "backup-123",
            "status": "passed",
        }
    ]
