from __future__ import annotations

import json
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.operator_request_context import OperatorRequestContext
from app.services.recovery_drill_run_service import run_governed_recovery_drill
from scripts.durable_recovery_drill import RecoveryDrillEvidence


def test_run_governed_recovery_drill_records_operator_context_and_lease_metadata(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    settings = get_settings()
    monkeypatch.setattr(settings, "RECOVERY_DRILL_ARTIFACT_PATH", artifact_dir)
    monkeypatch.setattr(settings, "RECOVERY_DRILL_ACTION_LEASE_STALE_SECONDS", 300.0)

    calls: list[dict[str, object]] = []

    def _fake_drill_executor(**kwargs):
        calls.append(kwargs)
        return RecoveryDrillEvidence(
            drill_name="durable_metadata_restore_recovery",
            generated_at_utc="2026-03-15T00:00:00Z",
            evidence_file_name="2026-03-15t00-00-00.json",
            operator_id=str(kwargs["operator_id"]),
            tenant_id=str(kwargs["tenant_id"]),
            correlation_id=str(kwargs["correlation_id"]),
            backup_identifier=str(kwargs["backup_identifier"]),
            database_path="tmp/recovery.db",
            restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
            owned_tables_present=["analytics_execution"],
            compute_job_processed_count=1,
            compute_async_result_status="complete",
            compute_execution_status="complete",
            processed_payload_count=1,
            materialized_artifact_path="tmp/details.csv",
            materialized_artifact_exists=True,
            status="passed",
        )

    result = run_governed_recovery_drill(
        operator_context=OperatorRequestContext(
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
        ),
        backup_identifier="backup-123",
        settings=settings,
        drill_executor=_fake_drill_executor,
        acquired_at_utc=datetime(2026, 3, 15, tzinfo=UTC),
    )

    assert not result.idempotent_replay
    assert result.response.operator_id == "ops-user"
    assert result.response.tenant_id == "tenant-a"
    assert result.response.correlation_id == "corr-1"
    assert result.response.backup_identifier == "backup-123"
    assert calls == [
        {
            "output_dir": artifact_dir,
            "operator_id": "ops-user",
            "tenant_id": "tenant-a",
            "correlation_id": "corr-1",
            "backup_identifier": "backup-123",
        }
    ]
    assert not list((artifact_dir / ".action-locks").glob("*.lock"))


def test_run_governed_recovery_drill_replays_from_explicit_settings_artifact_directory(tmp_path):
    artifact_dir = tmp_path / "configured" / "durable-recovery-drill"
    settings = get_settings().model_copy(
        update={
            "RECOVERY_DRILL_ARTIFACT_PATH": artifact_dir,
            "RECOVERY_DRILL_ACTION_LEASE_STALE_SECONDS": 300.0,
        }
    )
    operator_context = OperatorRequestContext(
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
    )
    calls: list[dict[str, object]] = []

    def _fake_drill_executor(**kwargs):
        calls.append(kwargs)
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "drill_name": "durable_metadata_restore_recovery",
            "generated_at_utc": "2026-03-15T00:00:00Z",
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
        return RecoveryDrillEvidence(**payload)

    first = run_governed_recovery_drill(
        operator_context=operator_context,
        backup_identifier="backup-123",
        settings=settings,
        drill_executor=_fake_drill_executor,
        acquired_at_utc=datetime(2026, 3, 15, tzinfo=UTC),
    )
    second = run_governed_recovery_drill(
        operator_context=operator_context,
        backup_identifier="backup-123",
        settings=settings,
        drill_executor=_fake_drill_executor,
        acquired_at_utc=datetime(2026, 3, 15, tzinfo=UTC),
    )

    assert not first.idempotent_replay
    assert second.idempotent_replay
    assert second.response.evidence_file_name == "2026-03-15t00-00-00.json"
    assert len(calls) == 1
