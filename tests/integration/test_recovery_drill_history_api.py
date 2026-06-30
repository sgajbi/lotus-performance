import json

from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app


def _validation_error_fields(body: dict) -> set[str]:
    assert body["detail"] == "Request validation failed."
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["message"] == "Request validation failed."
    assert body["source"] == "lotus-performance"
    assert body["retryable"] is False
    assert body["correlation_id"]
    assert body["request_id"]
    return {item["loc"][-1] for item in body["validation_errors"]}


def test_recovery_drill_history_api_reports_unavailable_when_manifest_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", tmp_path / "missing")

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "v1"
    assert body["status"] == "unavailable"
    assert body["reason"] == "recovery_drill_artifact_directory_missing"


def test_recovery_drill_history_api_rejects_invalid_time_filter():
    with TestClient(app) as client:
        response = client.get(
            "/integration/recovery-drills",
            params={"generated_before": "not-a-timestamp"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_utc_timestamp_filter",
        "field": "generated_before",
        "message": "generated_before must be an ISO-8601 UTC timestamp.",
    }


def test_recovery_drill_history_api_rejects_blank_string_filters():
    with TestClient(app) as client:
        response = client.get(
            "/integration/recovery-drills",
            params={"operator_id": " ", "backup_identifier": "  ", "status": " "},
        )

    assert response.status_code == 422
    fields = _validation_error_fields(response.json())
    assert {"operator_id", "backup_identifier", "status"} <= fields


def test_recovery_drill_history_api_reports_unavailable_when_manifest_is_invalid(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "manifest.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "recovery_drill_manifest_invalid"


def test_recovery_drill_history_api_reports_unavailable_when_manifest_shape_is_invalid(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": ["2026-03-14t00-00-00.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [{"generated_at_utc": "2026-03-14T00:00:00Z"}],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "recovery_drill_manifest_invalid"


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
                "tenant_id": None,
                "correlation_id": None,
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "tenant_id": None,
                "correlation_id": None,
                "backup_identifier": "backup-123",
                "status": "failed",
            },
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
    assert body["applied_filters"] == {"limit": 10}
    assert body["entries"] == [
        {
            "evidence_file_name": "2026-03-14t00-00-00.json",
            "generated_at_utc": "2026-03-14T00:00:00Z",
            "operator_id": "ops-user",
            "tenant_id": None,
            "correlation_id": None,
            "backup_identifier": "backup-123",
            "status": "passed",
        },
        {
            "evidence_file_name": "2026-03-13t00-00-00.json",
            "generated_at_utc": "2026-03-13T00:00:00Z",
            "operator_id": "ops-user",
            "tenant_id": None,
            "correlation_id": None,
            "backup_identifier": "backup-123",
            "status": "failed",
        },
    ]


def test_recovery_drill_history_api_normalizes_retained_entries_newest_first(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-13t00-00-00.json",
        "retained_file_names": [
            "2026-03-13t00-00-00.json",
            "2026-03-15t00-00-00.json",
            "2026-03-14t00-00-00.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "failed",
            },
            {
                "evidence_file_name": "2026-03-15t00-00-00.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "failed",
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills", params={"limit": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["latest_file_name"] == "2026-03-15t00-00-00.json"
    assert body["retained_file_names"] == [
        "2026-03-15t00-00-00.json",
        "2026-03-14t00-00-00.json",
        "2026-03-13t00-00-00.json",
    ]
    assert [entry["evidence_file_name"] for entry in body["entries"]] == [
        "2026-03-15t00-00-00.json",
        "2026-03-14t00-00-00.json",
        "2026-03-13t00-00-00.json",
    ]


def test_recovery_drill_history_api_defaults_to_bounded_page(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    entries = [
        {
            "evidence_file_name": f"2026-03-{day:02d}t00-00-00.json",
            "generated_at_utc": f"2026-03-{day:02d}T00:00:00Z",
            "operator_id": "ops-user",
            "backup_identifier": "backup-123",
            "status": "passed",
        }
        for day in range(20, 9, -1)
    ]
    manifest = {
        "latest_file_name": "2026-03-20t00-00-00.json",
        "retained_file_names": [entry["evidence_file_name"] for entry in entries],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": entries,
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.get("/integration/recovery-drills")

    assert response.status_code == 200
    body = response.json()
    assert body["total_entries"] == 11
    assert body["matched_entries"] == 11
    assert body["returned_entries"] == 10
    assert body["next_offset"] == 10
    assert body["applied_filters"] == {"limit": 10}
    assert [entry["evidence_file_name"] for entry in body["entries"]] == [
        entry["evidence_file_name"] for entry in entries[:10]
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
                "operator_id": " ops-user ",
                "backup_identifier": " backup-123 ",
                "status": " passed ",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_entries"] == 3
    assert body["matched_entries"] == 1
    assert body["returned_entries"] == 1
    assert body["next_offset"] is None
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
            "tenant_id": None,
            "correlation_id": None,
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
            "tenant_id": None,
            "correlation_id": None,
            "backup_identifier": "backup-123",
            "status": "passed",
        }
    ]
