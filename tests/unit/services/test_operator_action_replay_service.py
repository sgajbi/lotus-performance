from app.services.operator_action_replay_service import (
    resolve_recovery_drill_manual_replay,
    resolve_runtime_retention_manual_replay,
)
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)


def test_runtime_retention_manual_replay_returns_matching_evidence(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    payload = {
        "cleanup_name": "runtime_retention_cleanup",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "evidence_file_name": "2026-03-15t00-00-00z.json",
        "operator_id": "ops-user",
        "tenant_id": "tenant-a",
        "correlation_id": "corr-1",
        "trigger_mode": "manual",
        "job_id": "ticket-7",
        "cleanup_mode": "dry_run",
        "status": "planned",
        "retention_days": 30,
        "cutoff_utc": "2026-02-13T00:00:00Z",
        "prunable_execution_count": 1,
        "prunable_compute_job_count": 1,
        "prunable_async_result_count": 1,
        "prunable_lineage_record_count": 1,
        "prunable_lineage_artifact_count": 1,
    }
    (artifact_dir / payload["evidence_file_name"]).write_text(__import__("json").dumps(payload), encoding="utf-8")
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name=payload["evidence_file_name"],
        retained_file_names=[payload["evidence_file_name"]],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name=payload["evidence_file_name"],
                generated_at_utc=payload["generated_at_utc"],
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="ticket-7",
                cleanup_mode="dry_run",
                status="planned",
                retention_days=30,
                prunable_execution_count=1,
                prunable_compute_job_count=1,
                prunable_async_result_count=1,
                prunable_lineage_record_count=1,
                prunable_lineage_artifact_count=1,
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 10, "trigger_mode": "manual"},
    )

    replay = resolve_runtime_retention_manual_replay(
        snapshot,
        artifact_directory=artifact_dir,
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        apply=False,
        retention_days=None,
        job_id="ticket-7",
    )

    assert replay is not None
    assert replay.evidence_file_name == payload["evidence_file_name"]


def test_runtime_retention_manual_replay_rejects_different_operator_or_tenant(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    payload = {
        "cleanup_name": "runtime_retention_cleanup",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "evidence_file_name": "2026-03-15t00-00-00z.json",
        "operator_id": "ops-user",
        "tenant_id": "tenant-a",
        "correlation_id": "corr-1",
        "trigger_mode": "manual",
        "job_id": "ticket-7",
        "cleanup_mode": "dry_run",
        "status": "planned",
        "retention_days": 30,
        "cutoff_utc": "2026-02-13T00:00:00Z",
        "prunable_execution_count": 1,
        "prunable_compute_job_count": 1,
        "prunable_async_result_count": 1,
        "prunable_lineage_record_count": 1,
        "prunable_lineage_artifact_count": 1,
    }
    (artifact_dir / payload["evidence_file_name"]).write_text(__import__("json").dumps(payload), encoding="utf-8")
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name=payload["evidence_file_name"],
        retained_file_names=[payload["evidence_file_name"]],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name=payload["evidence_file_name"],
                generated_at_utc=payload["generated_at_utc"],
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="ticket-7",
                cleanup_mode="dry_run",
                status="planned",
                retention_days=30,
                prunable_execution_count=1,
                prunable_compute_job_count=1,
                prunable_async_result_count=1,
                prunable_lineage_record_count=1,
                prunable_lineage_artifact_count=1,
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 10, "trigger_mode": "manual"},
    )

    assert (
        resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="other-ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            apply=False,
            retention_days=None,
            job_id="ticket-7",
        )
        is None
    )
    assert (
        resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-b",
            correlation_id="corr-1",
            apply=False,
            retention_days=None,
            job_id="ticket-7",
        )
        is None
    )


def test_recovery_drill_manual_replay_returns_matching_evidence(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    payload = {
        "drill_name": "durable_metadata_restore_recovery",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "evidence_file_name": "2026-03-15t00-00-00.json",
        "operator_id": "ops-user",
        "tenant_id": "tenant-a",
        "correlation_id": "corr-1",
        "backup_identifier": "backup-123",
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
    (artifact_dir / payload["evidence_file_name"]).write_text(__import__("json").dumps(payload), encoding="utf-8")
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name=payload["evidence_file_name"],
        retained_file_names=[payload["evidence_file_name"]],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name=payload["evidence_file_name"],
                generated_at_utc=payload["generated_at_utc"],
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                backup_identifier="backup-123",
                status="passed",
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 10},
    )

    replay = resolve_recovery_drill_manual_replay(
        snapshot,
        artifact_directory=artifact_dir,
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        backup_identifier="backup-123",
    )

    assert replay is not None
    assert replay.evidence_file_name == payload["evidence_file_name"]


def test_recovery_drill_manual_replay_rejects_different_operator_or_tenant(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    payload = {
        "drill_name": "durable_metadata_restore_recovery",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "evidence_file_name": "2026-03-15t00-00-00.json",
        "operator_id": "ops-user",
        "tenant_id": "tenant-a",
        "correlation_id": "corr-1",
        "backup_identifier": "backup-123",
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
    (artifact_dir / payload["evidence_file_name"]).write_text(__import__("json").dumps(payload), encoding="utf-8")
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name=payload["evidence_file_name"],
        retained_file_names=[payload["evidence_file_name"]],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name=payload["evidence_file_name"],
                generated_at_utc=payload["generated_at_utc"],
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                backup_identifier="backup-123",
                status="passed",
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 10},
    )

    assert (
        resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="other-ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )
        is None
    )
    assert (
        resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-b",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )
        is None
    )
