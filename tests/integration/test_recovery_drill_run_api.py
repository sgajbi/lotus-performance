from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app


def test_recovery_drill_run_api_rejects_missing_operator_identity():
    with TestClient(app) as client:
        response = client.post(
            "/integration/recovery-drills/run",
            json={"backup_identifier": "backup-123"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "missing_operator_identity"}


def test_recovery_drill_run_api_persists_enterprise_context(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    monkeypatch.setattr(get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)

    def _fake_run_recovery_drill(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "drill_name": "durable_metadata_restore_recovery",
            "generated_at_utc": "2026-03-14T00:00:00Z",
            "evidence_file_name": "2026-03-14t00-00-00.json",
            "operator_id": kwargs["operator_id"],
            "tenant_id": kwargs["tenant_id"],
            "correlation_id": kwargs["correlation_id"],
            "backup_identifier": kwargs["backup_identifier"],
            "database_path": "tmp/recovery.db",
            "restored_schema_mode": "legacy_lineage_schema_upgraded_in_place",
            "owned_tables_present": ["analytics_execution"],
            "compute_job_processed_count": 1,
            "compute_async_result_status": "complete",
            "compute_execution_status": "complete",
            "processed_payload_count": 1,
            "materialized_artifact_path": "tmp/details.csv",
            "materialized_artifact_exists": True,
            "status": "passed",
        }
        (output_dir / "2026-03-14t00-00-00.json").write_text(__import__("json").dumps(payload), encoding="utf-8")
        return type("Evidence", (), payload)()

    monkeypatch.setattr("app.api.endpoints.recovery_drill_history.execute_recovery_drill", _fake_run_recovery_drill)

    with TestClient(app) as client:
        response = client.post(
            "/integration/recovery-drills/run",
            headers={
                "X-Actor-Id": "ops-user",
                "X-Tenant-Id": "tenant-a",
                "X-Correlation-Id": "corr-1",
            },
            json={"backup_identifier": "backup-123"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operator_id"] == "ops-user"
    assert body["tenant_id"] == "tenant-a"
    assert body["correlation_id"] == "corr-1"
    assert body["backup_identifier"] == "backup-123"


def test_recovery_drill_run_api_requires_runtime_manage_capability_when_enterprise_auth_is_enabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        get_settings(), "RECOVERY_DRILL_ARTIFACT_PATH", tmp_path / "artifacts" / "durable-recovery-drill"
    )
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
            "/integration/recovery-drills/run",
            headers=headers,
            json={"backup_identifier": "backup-123"},
        )

    assert denied.status_code == 403
    assert denied.json()["reason"] == "missing_capability:operations.runtime.manage"
