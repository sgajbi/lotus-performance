from datetime import UTC, datetime

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


def test_recovery_drill_run_api_rejects_immediate_manual_replay(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    settings = get_settings()
    monkeypatch.setattr(settings, "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)

    def _fake_run_recovery_drill(**kwargs):
        import json

        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = {
            "drill_name": "durable_metadata_restore_recovery",
            "generated_at_utc": generated_at_utc,
            "evidence_file_name": "2026-03-15t00-00-00.json",
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
        manifest = {
            "latest_file_name": payload["evidence_file_name"],
            "retained_file_names": [payload["evidence_file_name"]],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [
                {
                    "evidence_file_name": payload["evidence_file_name"],
                    "generated_at_utc": payload["generated_at_utc"],
                    "operator_id": payload["operator_id"],
                    "tenant_id": payload["tenant_id"],
                    "correlation_id": payload["correlation_id"],
                    "backup_identifier": payload["backup_identifier"],
                    "status": payload["status"],
                }
            ],
        }
        (output_dir / payload["evidence_file_name"]).write_text(json.dumps(payload), encoding="utf-8")
        (output_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
        (output_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return type("Evidence", (), payload)()

    monkeypatch.setattr("app.api.endpoints.recovery_drill_history.execute_recovery_drill", _fake_run_recovery_drill)

    with TestClient(app) as client:
        first = client.post(
            "/integration/recovery-drills/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"backup_identifier": "backup-123"},
        )
        second = client.post(
            "/integration/recovery-drills/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"backup_identifier": "backup-123"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.headers["Retry-After"] == str(second.json()["detail"]["retry_after_seconds"])
    assert second.json()["detail"]["code"] == "recovery_drill_manual_run_cooldown_active"
    assert second.json()["detail"]["latest_evidence_file_name"] == first.json()["evidence_file_name"]


def test_recovery_drill_run_api_replays_same_correlation_request(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    settings = get_settings()
    monkeypatch.setattr(settings, "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)

    def _fake_run_recovery_drill(**kwargs):
        import json

        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = {
            "drill_name": "durable_metadata_restore_recovery",
            "generated_at_utc": generated_at_utc,
            "evidence_file_name": "2026-03-15t00-00-00-replay.json",
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
        manifest = {
            "latest_file_name": payload["evidence_file_name"],
            "retained_file_names": [payload["evidence_file_name"]],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [
                {
                    "evidence_file_name": payload["evidence_file_name"],
                    "generated_at_utc": payload["generated_at_utc"],
                    "operator_id": payload["operator_id"],
                    "tenant_id": payload["tenant_id"],
                    "correlation_id": payload["correlation_id"],
                    "backup_identifier": payload["backup_identifier"],
                    "status": payload["status"],
                }
            ],
        }
        (output_dir / payload["evidence_file_name"]).write_text(json.dumps(payload), encoding="utf-8")
        (output_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
        (output_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return type("Evidence", (), payload)()

    monkeypatch.setattr("app.api.endpoints.recovery_drill_history.execute_recovery_drill", _fake_run_recovery_drill)

    headers = {
        "X-Actor-Id": "ops-user",
        "X-Correlation-Id": "corr-123",
    }

    with TestClient(app) as client:
        first = client.post(
            "/integration/recovery-drills/run",
            headers=headers,
            json={"backup_identifier": "backup-123"},
        )
        second = client.post(
            "/integration/recovery-drills/run",
            headers=headers,
            json={"backup_identifier": "backup-123"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert second.json()["evidence_file_name"] == first.json()["evidence_file_name"]


def test_recovery_drill_run_api_allows_immediate_different_backup_identifier(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    settings = get_settings()
    monkeypatch.setattr(settings, "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS", 300.0)

    def _fake_run_recovery_drill(**kwargs):
        import json

        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        evidence_file_name = f"{kwargs['backup_identifier']}.json"
        payload = {
            "drill_name": "durable_metadata_restore_recovery",
            "generated_at_utc": generated_at_utc,
            "evidence_file_name": evidence_file_name,
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
        historical_paths = sorted(
            path for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
        )
        entries = []
        retained_file_names = []
        for path in historical_paths:
            existing = json.loads(path.read_text(encoding="utf-8"))
            retained_file_names.append(existing["evidence_file_name"])
            entries.append(
                {
                    "evidence_file_name": existing["evidence_file_name"],
                    "generated_at_utc": existing["generated_at_utc"],
                    "operator_id": existing["operator_id"],
                    "tenant_id": existing.get("tenant_id"),
                    "correlation_id": existing.get("correlation_id"),
                    "backup_identifier": existing["backup_identifier"],
                    "status": existing["status"],
                }
            )
        retained_file_names.append(evidence_file_name)
        entries.append(
            {
                "evidence_file_name": evidence_file_name,
                "generated_at_utc": generated_at_utc,
                "operator_id": kwargs["operator_id"],
                "tenant_id": kwargs["tenant_id"],
                "correlation_id": kwargs["correlation_id"],
                "backup_identifier": kwargs["backup_identifier"],
                "status": "passed",
            }
        )
        manifest = {
            "latest_file_name": evidence_file_name,
            "retained_file_names": retained_file_names,
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": entries,
        }
        (output_dir / evidence_file_name).write_text(json.dumps(payload), encoding="utf-8")
        (output_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
        (output_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return type("Evidence", (), payload)()

    monkeypatch.setattr("app.api.endpoints.recovery_drill_history.execute_recovery_drill", _fake_run_recovery_drill)

    with TestClient(app) as client:
        first = client.post(
            "/integration/recovery-drills/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"backup_identifier": "backup-123"},
        )
        second = client.post(
            "/integration/recovery-drills/run",
            headers={"X-Actor-Id": "ops-user"},
            json={"backup_identifier": "backup-999"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["backup_identifier"] == "backup-999"
