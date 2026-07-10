import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from scripts.durable_recovery_drill import (
    REQUIRED_TABLES,
    RESTORE_VALIDATION_REQUIRED_TABLES,
    RecoveryDrillEvidence,
    _persist_evidence_history,
    _write_text_atomic,
    run_recovery_drill,
    run_restore_validation_drill,
)


def test_run_recovery_drill_emits_passing_evidence_and_writes_artifact_history(tmp_path):
    output_path = tmp_path / "manual" / "durable-recovery-drill.json"
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    evidence = run_recovery_drill(
        output_path=output_path,
        output_dir=output_dir,
        operator_id=" test-operator ",
        tenant_id=" ",
        correlation_id=" ",
        backup_identifier=" backup-001 ",
        retention_limit=2,
        retention_max_age_days=30,
    )

    assert evidence.status == "passed"
    assert evidence.operator_id == "test-operator"
    assert evidence.tenant_id is None
    assert evidence.correlation_id is None
    assert evidence.backup_identifier == "backup-001"
    assert evidence.processed_payload_count == 1
    assert evidence.compute_job_processed_count == 1
    assert evidence.compute_async_result_status == "complete"
    assert evidence.compute_execution_status == "complete"
    assert evidence.materialized_artifact_exists is True
    assert evidence.owned_tables_present == list(REQUIRED_TABLES)
    assert output_path.exists() is True
    assert (output_dir / "latest.json").exists() is True
    assert (output_dir / evidence.evidence_file_name).exists() is True
    assert (output_dir / "manifest.json").exists() is True

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "passed"
    assert persisted["operator_id"] == "test-operator"
    assert persisted["tenant_id"] is None
    assert persisted["correlation_id"] is None
    assert persisted["backup_identifier"] == "backup-001"
    assert persisted["processed_payload_count"] == 1
    assert persisted["compute_job_processed_count"] == 1
    assert persisted["compute_async_result_status"] == "complete"
    assert persisted["compute_execution_status"] == "complete"
    assert persisted["owned_tables_present"] == list(REQUIRED_TABLES)

    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    historical = json.loads((output_dir / evidence.evidence_file_name).read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert latest["evidence_file_name"] == evidence.evidence_file_name
    assert historical["evidence_file_name"] == evidence.evidence_file_name
    assert manifest["latest_file_name"] == evidence.evidence_file_name
    assert manifest["retention_limit"] == 2
    assert manifest["retention_max_age_days"] == 30
    assert manifest["retained_file_names"] == [evidence.evidence_file_name]


def test_run_recovery_drill_rejects_blank_backup_identifier_before_writing_artifacts(tmp_path):
    output_path = tmp_path / "manual" / "durable-recovery-drill.json"
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    with pytest.raises(ValueError, match="backup_identifier must not be blank"):
        run_recovery_drill(
            output_path=output_path,
            output_dir=output_dir,
            operator_id="test-operator",
            backup_identifier=" ",
            retention_limit=2,
            retention_max_age_days=30,
        )

    assert not output_path.exists()
    assert not output_dir.exists()


def test_run_recovery_drill_prunes_history_to_retention_limit(tmp_path):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    first = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-001",
        retention_limit=2,
        retention_max_age_days=30,
    )
    second = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-002",
        retention_limit=2,
        retention_max_age_days=30,
    )
    third = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-003",
        retention_limit=2,
        retention_max_age_days=30,
    )

    retained = sorted(
        path.name for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
    )
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert first.evidence_file_name not in retained
    assert retained == sorted([second.evidence_file_name, third.evidence_file_name])
    assert manifest["retention_limit"] == 2
    assert manifest["retention_max_age_days"] == 30
    assert manifest["retained_file_names"] == [third.evidence_file_name, second.evidence_file_name]
    assert [entry["evidence_file_name"] for entry in manifest["entries"]] == [
        third.evidence_file_name,
        second.evidence_file_name,
    ]
    assert latest["evidence_file_name"] == third.evidence_file_name


def test_run_recovery_drill_prunes_history_older_than_max_age(tmp_path):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    output_dir.mkdir(parents=True)
    stale_payload = {
        "drill_name": "durable_metadata_restore_recovery",
        "generated_at_utc": (datetime.now(UTC) - timedelta(days=120)).isoformat(),
        "evidence_file_name": "stale.json",
        "operator_id": "old-operator",
        "tenant_id": "tenant-old",
        "correlation_id": "corr-old",
        "backup_identifier": "old-backup",
        "database_path": "stale.db",
        "restored_schema_mode": "legacy_lineage_schema_upgraded_in_place",
        "owned_tables_present": list(REQUIRED_TABLES),
        "compute_job_processed_count": 1,
        "compute_async_result_status": "complete",
        "compute_execution_status": "complete",
        "processed_payload_count": 1,
        "materialized_artifact_path": "details.csv",
        "materialized_artifact_exists": True,
        "status": "passed",
    }
    (output_dir / "stale.json").write_text(json.dumps(stale_payload), encoding="utf-8")

    current = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-004",
        retention_limit=5,
        retention_max_age_days=30,
    )

    retained = sorted(
        path.name for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
    )
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert "stale.json" not in retained
    assert retained == [current.evidence_file_name]
    assert manifest["retained_file_names"] == [current.evidence_file_name]


def test_recovery_drill_history_skips_invalid_retained_artifacts(tmp_path, caplog):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    output_dir.mkdir(parents=True)
    malformed = output_dir / "2026-03-14t00-00-00z.json"
    malformed.write_text("{not-json", encoding="utf-8")
    non_object = output_dir / "2026-03-13t00-00-00z.json"
    non_object.write_text("[]", encoding="utf-8")
    generated_at_utc = datetime.now(UTC).isoformat()
    evidence = RecoveryDrillEvidence(
        drill_name="durable_metadata_restore_recovery",
        generated_at_utc=generated_at_utc,
        evidence_file_name="current.json",
        operator_id="test-operator",
        tenant_id=None,
        correlation_id=None,
        backup_identifier="backup-001",
        database_path="recovery-drill.db",
        restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
        owned_tables_present=list(REQUIRED_TABLES),
        compute_job_processed_count=1,
        compute_async_result_status="complete",
        compute_execution_status="complete",
        processed_payload_count=1,
        materialized_artifact_path="details.csv",
        materialized_artifact_exists=True,
        status="passed",
    )

    with caplog.at_level(logging.WARNING, logger="scripts.durable_recovery_drill"):
        _persist_evidence_history(
            output_dir=output_dir,
            evidence=evidence,
            retention_limit=5,
            retention_max_age_days=30,
        )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["latest_file_name"] == evidence.evidence_file_name
    assert manifest["retained_file_names"] == [evidence.evidence_file_name]
    assert not malformed.exists()
    assert not non_object.exists()
    assert "Recovery drill evidence ignored during age pruning" in caplog.text


def test_recovery_drill_manifest_rebuild_skips_invalid_entry_shapes(tmp_path, caplog):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    output_dir.mkdir(parents=True)
    invalid_shape = output_dir / "invalid-shape.json"
    invalid_shape.write_text(
        json.dumps(
            {
                "evidence_file_name": "invalid-shape.json",
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "operator_id": 123,
                "tenant_id": None,
                "correlation_id": None,
                "backup_identifier": "backup-legacy",
                "status": "passed",
            }
        ),
        encoding="utf-8",
    )
    evidence = RecoveryDrillEvidence(
        drill_name="durable_metadata_restore_recovery",
        generated_at_utc=datetime.now(UTC).isoformat(),
        evidence_file_name="current.json",
        operator_id="test-operator",
        tenant_id=None,
        correlation_id=None,
        backup_identifier="backup-001",
        database_path="recovery-drill.db",
        restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
        owned_tables_present=list(REQUIRED_TABLES),
        compute_job_processed_count=1,
        compute_async_result_status="complete",
        compute_execution_status="complete",
        processed_payload_count=1,
        materialized_artifact_path="details.csv",
        materialized_artifact_exists=True,
        status="passed",
    )

    with caplog.at_level(logging.WARNING, logger="scripts.durable_recovery_drill"):
        _persist_evidence_history(
            output_dir=output_dir,
            evidence=evidence,
            retention_limit=5,
            retention_max_age_days=30,
        )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["retained_file_names"] == [evidence.evidence_file_name]
    assert invalid_shape.exists()
    assert "Recovery drill evidence ignored during manifest rebuild" in caplog.text


def test_recovery_drill_manifest_rebuild_normalizes_optional_entry_identities(tmp_path):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    output_dir.mkdir(parents=True)
    legacy = output_dir / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "evidence_file_name": "legacy.json",
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "operator_id": " legacy-operator ",
                "tenant_id": " tenant-legacy ",
                "correlation_id": " ",
                "backup_identifier": " backup-legacy ",
                "status": "passed",
            }
        ),
        encoding="utf-8",
    )
    evidence = RecoveryDrillEvidence(
        drill_name="durable_metadata_restore_recovery",
        generated_at_utc=datetime.now(UTC).isoformat(),
        evidence_file_name="current.json",
        operator_id="test-operator",
        tenant_id=None,
        correlation_id=None,
        backup_identifier="backup-001",
        database_path="recovery-drill.db",
        restored_schema_mode="legacy_lineage_schema_upgraded_in_place",
        owned_tables_present=list(REQUIRED_TABLES),
        compute_job_processed_count=1,
        compute_async_result_status="complete",
        compute_execution_status="complete",
        processed_payload_count=1,
        materialized_artifact_path="details.csv",
        materialized_artifact_exists=True,
        status="passed",
    )

    _persist_evidence_history(
        output_dir=output_dir,
        evidence=evidence,
        retention_limit=5,
        retention_max_age_days=30,
    )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    legacy_entry = next(entry for entry in manifest["entries"] if entry["evidence_file_name"] == "legacy.json")
    assert legacy_entry["operator_id"] == "legacy-operator"
    assert legacy_entry["tenant_id"] == "tenant-legacy"
    assert legacy_entry["correlation_id"] is None
    assert legacy_entry["backup_identifier"] == "backup-legacy"


def test_write_text_atomic_does_not_leave_partial_target(tmp_path, mocker):
    target_path = tmp_path / "manifest.json"

    def _failing_replace(_dst):
        raise OSError("replace failed")

    mocker.patch("scripts.durable_recovery_drill.Path.replace", side_effect=_failing_replace)

    with pytest.raises(OSError, match="replace failed"):
        _write_text_atomic(target_path, '{"status":"passed"}')

    assert not target_path.exists()
    assert list(tmp_path.glob(".recovery-drill-*.tmp")) == []


def test_run_recovery_drill_persists_enterprise_context(tmp_path):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    evidence = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        backup_identifier="backup-ctx",
        retention_limit=2,
        retention_max_age_days=30,
    )

    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert evidence.tenant_id == "tenant-a"
    assert evidence.correlation_id == "corr-1"
    assert latest["tenant_id"] == "tenant-a"
    assert latest["correlation_id"] == "corr-1"
    assert manifest["entries"][0]["tenant_id"] == "tenant-a"
    assert manifest["entries"][0]["correlation_id"] == "corr-1"


def test_run_restore_validation_drill_records_real_backup_restore_evidence(tmp_path):
    database_path = tmp_path / "restored.db"
    _create_restored_durable_database(database_path)
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    evidence = run_restore_validation_drill(
        restored_database_url=f"sqlite:///{database_path}",
        backup_identifier="backup-restore-001",
        backup_source="s3://lotus-backups/performance/backup-restore-001",
        backup_created_at_utc="2026-03-29T01:00:00Z",
        restore_started_at_utc="2026-03-29T01:20:00Z",
        restore_completed_at_utc="2026-03-29T01:30:00Z",
        output_dir=output_dir,
        operator_id="ops-restore",
        tenant_id="tenant-a",
        correlation_id="corr-restore",
    )

    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert evidence.status == "passed"
    assert evidence.validation_mode == "restore_validation"
    assert evidence.backup_source == "s3://lotus-backups/performance/backup-restore-001"
    assert evidence.restore_timestamp_utc == "2026-03-29T01:30:00+00:00"
    assert evidence.backup_age_seconds == 1800.0
    assert evidence.restore_duration_seconds == 600.0
    assert evidence.owned_tables_present == list(RESTORE_VALIDATION_REQUIRED_TABLES)
    assert evidence.restored_table_row_counts is not None
    assert evidence.restored_table_row_counts["analytics_execution"] == 1
    assert evidence.restored_table_row_counts["lineage_records"] == 1
    assert evidence.schema_bootstrap_status == "passed"
    assert evidence.readiness_status == "ready"
    assert evidence.representative_execution_check == "passed_analytics_execution_read_with_rows"
    assert evidence.representative_lineage_check == "passed_lineage_records_read_with_rows"
    assert latest["validation_mode"] == "restore_validation"
    assert latest["backup_source"] == "s3://lotus-backups/performance/backup-restore-001"
    assert latest["restored_table_row_counts"]["analytics_execution"] == 1


def test_run_restore_validation_drill_fails_when_required_tables_are_missing(tmp_path):
    database_path = tmp_path / "partial-restored.db"
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE analytics_execution (calculation_id TEXT PRIMARY KEY)")
    finally:
        engine.dispose()

    evidence = run_restore_validation_drill(
        restored_database_url=f"sqlite:///{database_path}",
        backup_identifier="backup-restore-002",
        backup_source="manual-snapshot",
        restore_completed_at_utc="2026-03-29T01:30:00Z",
        operator_id="ops-restore",
    )

    assert evidence.status == "failed"
    assert evidence.validation_mode == "restore_validation"
    assert evidence.schema_bootstrap_status == "failed"
    assert evidence.readiness_status == "not_ready"
    assert evidence.owned_tables_present == ["analytics_execution"]
    assert evidence.representative_execution_check == "passed_analytics_execution_read_no_rows"
    assert evidence.representative_lineage_check == "failed_lineage_records_read"


def _create_restored_durable_database(database_path):
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            for table_name in RESTORE_VALIDATION_REQUIRED_TABLES:
                if table_name == "lineage_payloads":
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE lineage_payloads (
                            calculation_id TEXT PRIMARY KEY,
                            worker_id TEXT,
                            leased_at_utc TEXT,
                            lease_expires_at_utc TEXT
                        )
                        """
                    )
                elif table_name == "composite_member_return_facts":
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE composite_member_return_facts (
                            calculation_id TEXT PRIMARY KEY,
                            return_view TEXT,
                            source_fingerprint TEXT,
                            restatement_version TEXT
                        )
                        """
                    )
                else:
                    connection.exec_driver_sql(f'CREATE TABLE "{table_name}" (calculation_id TEXT PRIMARY KEY)')
            connection.exec_driver_sql("INSERT INTO analytics_execution (calculation_id) VALUES ('calc-restored-001')")
            connection.exec_driver_sql("INSERT INTO lineage_records (calculation_id) VALUES ('calc-restored-001')")
    finally:
        engine.dispose()
