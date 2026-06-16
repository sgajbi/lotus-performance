import logging

from app.services.operator_action_replay_service import (
    _load_payload,
    _recovery_drill_entry_matches,
    _recovery_drill_payload_has_required_shape,
    _recovery_drill_payload_identity_matches,
    _recovery_drill_payload_matches_entry,
    _runtime_retention_payload_counts_match,
    _runtime_retention_payload_has_required_shape,
    _runtime_retention_payload_identity_matches,
    _runtime_retention_payload_matches_entry,
    _runtime_retention_replay_from_entry,
    _runtime_retention_request_filters_match,
    resolve_recovery_drill_manual_replay,
    resolve_runtime_retention_manual_replay,
)
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)


def _runtime_retention_entry() -> RuntimeRetentionHistoryEntry:
    return RuntimeRetentionHistoryEntry(
        evidence_file_name="2026-03-15t00-00-00z.json",
        generated_at_utc="2026-03-15T00:00:00Z",
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        trigger_mode="manual",
        job_id="ticket-7",
        cleanup_mode="dry_run",
        status="planned",
        retention_days=30,
        prunable_execution_count=1,
        prunable_compute_job_count=2,
        prunable_async_result_count=3,
        prunable_lineage_record_count=4,
        prunable_lineage_artifact_count=5,
    )


def _runtime_retention_payload(**overrides):
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
        "prunable_compute_job_count": 2,
        "prunable_async_result_count": 3,
        "prunable_lineage_record_count": 4,
        "prunable_lineage_artifact_count": 5,
    }
    payload.update(overrides)
    return payload


def _recovery_drill_entry() -> RecoveryDrillHistoryEntry:
    return RecoveryDrillHistoryEntry(
        evidence_file_name="2026-03-15t00-00-00.json",
        generated_at_utc="2026-03-15T00:00:00Z",
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        backup_identifier="backup-123",
        status="passed",
    )


def _recovery_drill_payload(**overrides):
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
    payload.update(overrides)
    return payload


def test_runtime_retention_payload_match_helpers_accept_matching_payload():
    payload = _runtime_retention_payload()
    entry = _runtime_retention_entry()

    assert _runtime_retention_payload_has_required_shape(payload) is True
    assert _runtime_retention_payload_identity_matches(payload, entry) is True
    assert _runtime_retention_payload_counts_match(payload, entry) is True
    assert _runtime_retention_payload_matches_entry(payload, entry) is True


def test_runtime_retention_payload_match_helpers_reject_shape_identity_and_count_drift():
    entry = _runtime_retention_entry()

    assert _runtime_retention_payload_has_required_shape(_runtime_retention_payload(cutoff_utc=" ")) is False
    assert (
        _runtime_retention_payload_identity_matches(
            _runtime_retention_payload(evidence_file_name="different.json"), entry
        )
        is False
    )
    assert _runtime_retention_payload_identity_matches(_runtime_retention_payload(job_id=None), entry) is False
    assert (
        _runtime_retention_payload_counts_match(_runtime_retention_payload(prunable_execution_count=99), entry) is False
    )
    assert (
        _runtime_retention_payload_matches_entry(_runtime_retention_payload(prunable_execution_count=99), entry)
        is False
    )


def test_runtime_retention_request_filters_accept_matching_request():
    assert (
        _runtime_retention_request_filters_match(
            _runtime_retention_entry(),
            apply=False,
            retention_days=30,
            job_id=" ticket-7 ",
        )
        is True
    )


def test_runtime_retention_request_filters_accept_absent_optional_retention_days():
    assert (
        _runtime_retention_request_filters_match(
            _runtime_retention_entry(),
            apply=False,
            retention_days=None,
            job_id="ticket-7",
        )
        is True
    )


def test_runtime_retention_request_filters_reject_drift():
    entry = _runtime_retention_entry()

    assert (
        _runtime_retention_request_filters_match(
            entry,
            apply=True,
            retention_days=30,
            job_id="ticket-7",
        )
        is False
    )
    assert (
        _runtime_retention_request_filters_match(
            entry,
            apply=False,
            retention_days=60,
            job_id="ticket-7",
        )
        is False
    )
    assert (
        _runtime_retention_request_filters_match(
            entry,
            apply=False,
            retention_days=30,
            job_id="ticket-8",
        )
        is False
    )


def test_runtime_retention_replay_from_entry_returns_loaded_matching_payload(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    entry = _runtime_retention_entry()
    payload = _runtime_retention_payload()
    (artifact_dir / entry.evidence_file_name).write_text(__import__("json").dumps(payload), encoding="utf-8")

    replay = _runtime_retention_replay_from_entry(entry, artifact_directory=artifact_dir)

    assert replay is not None
    assert replay.payload == payload
    assert replay.evidence_file_name == entry.evidence_file_name


def test_runtime_retention_replay_from_entry_rejects_payload_drift(tmp_path, caplog):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    entry = _runtime_retention_entry()
    payload = _runtime_retention_payload(prunable_execution_count=99)
    (artifact_dir / entry.evidence_file_name).write_text(__import__("json").dumps(payload), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        replay = _runtime_retention_replay_from_entry(entry, artifact_directory=artifact_dir)

    assert replay is None
    assert "payload does not match runtime retention history entry" in caplog.text


def test_recovery_drill_payload_match_helpers_accept_matching_payload():
    payload = _recovery_drill_payload()
    entry = _recovery_drill_entry()

    assert _recovery_drill_payload_has_required_shape(payload) is True
    assert _recovery_drill_payload_identity_matches(payload, entry) is True
    assert _recovery_drill_payload_matches_entry(payload, entry) is True


def test_recovery_drill_payload_match_helpers_reject_shape_and_identity_drift():
    entry = _recovery_drill_entry()

    assert _recovery_drill_payload_has_required_shape(_recovery_drill_payload(database_path=" ")) is False
    assert (
        _recovery_drill_payload_identity_matches(_recovery_drill_payload(evidence_file_name="different.json"), entry)
        is False
    )
    assert _recovery_drill_payload_identity_matches(_recovery_drill_payload(tenant_id=None), entry) is False
    assert _recovery_drill_payload_identity_matches(_recovery_drill_payload(correlation_id=None), entry) is False
    assert (
        _recovery_drill_payload_identity_matches(_recovery_drill_payload(backup_identifier="backup-456"), entry)
        is False
    )
    assert _recovery_drill_payload_identity_matches(_recovery_drill_payload(status="failed"), entry) is False
    assert (
        _recovery_drill_payload_matches_entry(_recovery_drill_payload(evidence_file_name="different.json"), entry)
        is False
    )


def test_recovery_drill_entry_matches_accepts_matching_identity():
    assert (
        _recovery_drill_entry_matches(
            _recovery_drill_entry(),
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier=" backup-123 ",
        )
        is True
    )


def test_recovery_drill_entry_matches_rejects_identity_drift():
    entry = _recovery_drill_entry()

    assert (
        _recovery_drill_entry_matches(
            entry,
            operator_id="other-ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )
        is False
    )
    assert (
        _recovery_drill_entry_matches(
            entry,
            operator_id="ops-user",
            tenant_id="tenant-b",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )
        is False
    )
    assert (
        _recovery_drill_entry_matches(
            entry,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-2",
            backup_identifier="backup-123",
        )
        is False
    )
    assert (
        _recovery_drill_entry_matches(
            entry,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier="backup-456",
        )
        is False
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
        job_id=" ticket-7 ",
    )

    assert replay is not None
    assert replay.evidence_file_name == payload["evidence_file_name"]


def test_runtime_retention_manual_replay_rejects_blank_required_payload_string(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    payload = {
        "cleanup_name": " ",
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

    assert replay is None


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
    assert (
        resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-2",
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
        backup_identifier=" backup-123 ",
    )

    assert replay is not None
    assert replay.evidence_file_name == payload["evidence_file_name"]


def test_recovery_drill_manual_replay_rejects_blank_required_payload_string(tmp_path):
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
        "database_path": " ",
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

    assert replay is None


def test_recovery_drill_manual_replay_rejects_blank_owned_table_payload_item(tmp_path):
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
        "owned_tables_present": ["analytics_execution", " "],
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

    assert replay is None


def test_recovery_drill_manual_replay_rejects_non_boolean_artifact_exists(tmp_path):
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
        "materialized_artifact_exists": "true",
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

    assert replay is None


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
    assert (
        resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-2",
            backup_identifier="backup-123",
        )
        is None
    )


def test_runtime_retention_manual_replay_handles_missing_correlation_and_unreadable_payload(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="missing.json",
        retained_file_names=["missing.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="missing.json",
                generated_at_utc="2026-03-15T00:00:00Z",
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
        applied_filters={},
    )

    assert (
        resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id=None,
            apply=False,
            retention_days=30,
            job_id="ticket-7",
        )
        is None
    )
    assert (
        resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            apply=False,
            retention_days=30,
            job_id="ticket-7",
        )
        is None
    )


def test_operator_action_replay_payload_loader_logs_unreadable_invalid_and_non_object_payloads(
    tmp_path, monkeypatch, caplog
):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    unreadable_path = artifact_dir / "unreadable.json"
    unreadable_path.write_text("{}", encoding="utf-8")
    invalid_path = artifact_dir / "invalid.json"
    invalid_path.write_text("{", encoding="utf-8")
    list_path = artifact_dir / "list.json"
    list_path.write_text("[1, 2]", encoding="utf-8")

    def _raise_os_error(self, *args, **kwargs):
        if self == unreadable_path:
            raise OSError("payload unreadable")
        return original_read_text(self, *args, **kwargs)

    original_read_text = type(unreadable_path).read_text
    monkeypatch.setattr(type(unreadable_path), "read_text", _raise_os_error)

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_replay_service"):
        assert _load_payload(artifact_directory=artifact_dir, evidence_file_name="unreadable.json") is None
        assert _load_payload(artifact_directory=artifact_dir, evidence_file_name="invalid.json") is None
        assert _load_payload(artifact_directory=artifact_dir, evidence_file_name="list.json") is None

    assert "Operator action replay evidence unreadable: unreadable.json" in caplog.text
    assert "OSError: payload unreadable" in caplog.text
    assert "Operator action replay evidence invalid JSON: invalid.json" in caplog.text
    assert "Operator action replay evidence ignored because payload is not an object: list.json" in caplog.text


def test_runtime_retention_manual_replay_rejects_evidence_outside_artifact_directory(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    outside_payload_path = tmp_path / "outside-runtime-retention.json"
    outside_payload_path.write_text(__import__("json").dumps({"ok": True}), encoding="utf-8")
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="../outside-runtime-retention.json",
        retained_file_names=["../outside-runtime-retention.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="../outside-runtime-retention.json",
                generated_at_utc="2026-03-15T00:00:00Z",
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
        applied_filters={},
    )

    assert (
        resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            apply=False,
            retention_days=30,
            job_id="ticket-7",
        )
        is None
    )


def test_runtime_retention_manual_replay_rejects_mismatched_cleanup_payload(tmp_path, caplog):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    payload = {"ok": True}
    (artifact_dir / "evidence.json").write_text(__import__("json").dumps(payload), encoding="utf-8")
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="evidence.json",
        retained_file_names=["evidence.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="evidence.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="job-1",
                cleanup_mode="apply",
                status="applied",
                retention_days=60,
                prunable_execution_count=0,
                prunable_compute_job_count=0,
                prunable_async_result_count=0,
                prunable_lineage_record_count=0,
                prunable_lineage_artifact_count=0,
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={},
    )

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_replay_service"):
        replay = resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            apply=True,
            retention_days=60,
            job_id="job-1",
        )

    assert replay is None
    assert (
        "Operator action replay evidence ignored because payload does not match runtime retention history entry: evidence.json"
        in caplog.text
    )


def test_runtime_retention_manual_replay_rejects_payload_missing_optional_context(tmp_path, caplog):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    payload = {
        "cleanup_name": "runtime_retention_cleanup",
        "generated_at_utc": "2026-03-15T00:00:00Z",
        "evidence_file_name": "evidence.json",
        "operator_id": "ops-user",
        "trigger_mode": "manual",
        "cleanup_mode": "dry_run",
        "status": "planned",
        "retention_days": 30,
        "cutoff_utc": "2026-02-13T00:00:00Z",
        "prunable_execution_count": 0,
        "prunable_compute_job_count": 0,
        "prunable_async_result_count": 0,
        "prunable_lineage_record_count": 0,
        "prunable_lineage_artifact_count": 0,
    }
    (artifact_dir / "evidence.json").write_text(__import__("json").dumps(payload), encoding="utf-8")
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="evidence.json",
        retained_file_names=["evidence.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="evidence.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="job-1",
                cleanup_mode="dry_run",
                status="planned",
                retention_days=30,
                prunable_execution_count=0,
                prunable_compute_job_count=0,
                prunable_async_result_count=0,
                prunable_lineage_record_count=0,
                prunable_lineage_artifact_count=0,
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={},
    )

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_replay_service"):
        replay = resolve_runtime_retention_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            apply=False,
            retention_days=30,
            job_id="job-1",
        )

    assert replay is None
    assert (
        "Operator action replay evidence ignored because payload does not match runtime retention history entry: evidence.json"
        in caplog.text
    )


def test_recovery_drill_manual_replay_rejects_mismatched_payload(tmp_path, caplog):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "evidence.json").write_text(__import__("json").dumps({"ok": True}), encoding="utf-8")
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="evidence.json",
        retained_file_names=["evidence.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="evidence.json",
                generated_at_utc="2026-03-15T00:00:00Z",
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
        applied_filters={},
    )

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_replay_service"):
        replay = resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )

    assert replay is None
    assert (
        "Operator action replay evidence ignored because payload does not match recovery drill history entry: evidence.json"
        in caplog.text
    )


def test_recovery_drill_manual_replay_handles_missing_correlation_and_unreadable_payload(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="missing.json",
        retained_file_names=["missing.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="missing.json",
                generated_at_utc="2026-03-15T00:00:00Z",
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
        applied_filters={},
    )

    assert (
        resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id=None,
            backup_identifier="backup-123",
        )
        is None
    )
    assert (
        resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )
        is None
    )


def test_recovery_drill_manual_replay_rejects_evidence_outside_artifact_directory(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    outside_payload_path = tmp_path / "outside-recovery-drill.json"
    outside_payload_path.write_text(__import__("json").dumps({"ok": True}), encoding="utf-8")
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(artifact_dir),
        latest_file_name="../outside-recovery-drill.json",
        retained_file_names=["../outside-recovery-drill.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="../outside-recovery-drill.json",
                generated_at_utc="2026-03-15T00:00:00Z",
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
        applied_filters={},
    )

    assert (
        resolve_recovery_drill_manual_replay(
            snapshot,
            artifact_directory=artifact_dir,
            operator_id="ops-user",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            backup_identifier="backup-123",
        )
        is None
    )
