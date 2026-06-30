from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app


def _assert_invalid_request_envelope(body: dict, detail: str) -> None:
    assert body["detail"] == detail
    assert body["error_code"] == "INVALID_REQUEST"
    assert body["message"] == detail
    assert body["source"] == "lotus-performance"
    assert body["retryable"] is False
    assert body["correlation_id"]
    assert body["request_id"]


def _assert_validation_error_field(body: dict, field: str) -> None:
    assert body["detail"] == "Request validation failed."
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["message"] == "Request validation failed."
    assert body["source"] == "lotus-performance"
    assert body["retryable"] is False
    assert body["correlation_id"]
    assert body["request_id"]
    assert body["validation_errors"][0]["loc"] == ["body", field]


def test_runtime_retention_run_api_rejects_missing_operator_identity():
    with TestClient(app) as client:
        response = client.post("/integration/runtime-retention-cleanups/run", json={"apply": False})

    assert response.status_code == 400
    _assert_invalid_request_envelope(response.json(), "missing_operator_identity")


@pytest.mark.parametrize("job_id", ["", "   "])
def test_runtime_retention_run_api_rejects_blank_job_id(job_id):
    with TestClient(app) as client:
        response = client.post(
            "/integration/runtime-retention-cleanups/run",
            json={"apply": False, "job_id": job_id},
        )

    assert response.status_code == 422
    _assert_validation_error_field(response.json(), "job_id")


def test_runtime_retention_run_api_persists_actor_identity_and_job_id(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    monkeypatch.setattr(get_settings(), "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)

    with TestClient(app) as client:
        response = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={
                "X-Actor-Id": "ops-user",
                "X-Tenant-Id": "tenant-a",
                "X-Correlation-Id": "corr-42",
            },
            json={"apply": False, "retention_days": 45, "job_id": " ops-ticket-42 "},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operator_id"] == "ops-user"
    assert body["tenant_id"] == "tenant-a"
    assert body["correlation_id"] == "corr-42"
    assert body["trigger_mode"] == "manual"
    assert body["job_id"] == "ops-ticket-42"
    assert body["cleanup_mode"] == "dry_run"
    assert body["status"] == "planned"
    assert body["retention_days"] == 45
    assert body["evidence_file_name"].endswith(".json")
    assert (artifact_dir / body["evidence_file_name"]).exists()
    assert (artifact_dir / "latest.json").exists()
    assert (artifact_dir / "manifest.json").exists()


def test_runtime_retention_run_api_requires_runtime_manage_capability_when_enterprise_auth_is_enabled(
    tmp_path,
    monkeypatch,
):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    monkeypatch.setattr(get_settings(), "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")

    headers = {
        "X-Actor-Id": "ops-user",
        "X-Tenant-Id": "tenant-a",
        "X-Role": "operator",
        "X-Correlation-Id": "corr-1",
        "X-Service-Identity": "lotus-platform",
        "X-Capabilities": "operations.runtime.read",
    }

    with TestClient(app) as client:
        denied = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers=headers,
            json={"apply": False},
        )
        headers["X-Capabilities"] = "operations.runtime.read,operations.runtime.manage"
        allowed = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers=headers,
            json={"apply": False},
        )

    assert denied.status_code == 403
    assert denied.json()["reason"] == "missing_capability:operations.runtime.manage"
    assert allowed.status_code == 200


def test_runtime_retention_run_api_rejects_immediate_manual_replay(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)

    with TestClient(app) as client:
        first = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"apply": False},
        )
        second = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"apply": False},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.headers["Retry-After"] == str(second.json()["detail"]["retry_after_seconds"])
    assert second.json()["detail"]["code"] == "runtime_retention_manual_run_cooldown_active"
    assert second.json()["detail"]["latest_evidence_file_name"] == first.json()["evidence_file_name"]


def test_runtime_retention_run_api_replays_same_correlation_request(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)

    headers = {
        "X-Actor-Id": "ops-user",
        "X-Correlation-Id": "corr-123",
    }

    with TestClient(app) as client:
        first = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers=headers,
            json={"apply": False, "job_id": "ticket-7"},
        )
        second = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers=headers,
            json={"apply": False, "job_id": "ticket-7"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert second.json()["evidence_file_name"] == first.json()["evidence_file_name"]


def test_runtime_retention_run_api_rejects_apply_without_recent_preview(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS", 3600.0)

    with TestClient(app) as client:
        response = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"apply": True, "job_id": "ticket-7"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "runtime_retention_apply_preview_required"


def test_runtime_retention_run_api_allows_apply_after_recent_matching_preview(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_APPLY_PREVIEW_MAX_AGE_SECONDS", 3600.0)

    headers = {
        "X-Actor-Id": "ops-user",
        "X-Correlation-Id": "corr-apply",
    }

    with TestClient(app) as client:
        preview = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers=headers,
            json={"apply": False, "job_id": "ticket-7"},
        )
        apply = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers=headers,
            json={"apply": True, "job_id": "ticket-7"},
        )

    assert preview.status_code == 200
    assert apply.status_code == 200
    assert apply.json()["cleanup_mode"] == "apply"


def test_runtime_retention_run_api_does_not_replay_other_operator_correlation(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)

    with TestClient(app) as client:
        first = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "ops-user", "X-Tenant-Id": "tenant-a", "X-Correlation-Id": "corr-123"},
            json={"apply": False, "job_id": "ticket-7"},
        )
        second = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "other-user", "X-Tenant-Id": "tenant-a", "X-Correlation-Id": "corr-123"},
            json={"apply": False, "job_id": "ticket-7"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "X-Idempotent-Replay" not in second.headers
    assert second.json()["evidence_file_name"] != first.json()["evidence_file_name"]


def test_runtime_retention_run_api_rejects_same_action_when_lease_is_active(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    lock_dir = artifact_dir / ".action-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "runtime-retention-ops-user-tenant-a-dry-run-30-ticket-7.lock"
    fresh_acquired_at = datetime.now(UTC).isoformat()
    lock_path.write_text(
        (
            '{"action_name":"runtime_retention_cleanup","operator_id":"ops-user","tenant_id":"tenant-a",'
            f'"governed_target":"dry_run:30:ticket-7","acquired_at_utc":"{fresh_acquired_at}"'
            "}"
        ),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "ops-user", "X-Tenant-Id": "tenant-a"},
            json={"apply": False, "job_id": "ticket-7"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "runtime_retention_cleanup_already_running"


def test_runtime_retention_run_api_reclaims_stale_action_lease(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RUNTIME_RETENTION_ACTION_LEASE_STALE_SECONDS", 300.0)
    lock_dir = artifact_dir / ".action-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "runtime-retention-ops-user-tenant-a-dry-run-30-ticket-7.lock"
    lock_path.write_text(
        '{"action_name":"runtime_retention_cleanup","operator_id":"ops-user","tenant_id":"tenant-a","governed_target":"dry_run:30:ticket-7","acquired_at_utc":"2026-03-14T00:00:00Z"}',
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.post(
            "/integration/runtime-retention-cleanups/run",
            headers={"X-Actor-Id": "ops-user", "X-Tenant-Id": "tenant-a"},
            json={"apply": False, "job_id": "ticket-7"},
        )

    assert response.status_code == 200
