from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app


def test_runtime_retention_run_api_rejects_missing_operator_identity():
    with TestClient(app) as client:
        response = client.post("/integration/runtime-retention-cleanups/run", json={"apply": False})

    assert response.status_code == 400
    assert response.json() == {"detail": "missing_operator_identity"}


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
            json={"apply": False, "retention_days": 45, "job_id": "ops-ticket-42"},
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
