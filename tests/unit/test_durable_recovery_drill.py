import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.durable_recovery_drill import REQUIRED_TABLES, _write_text_atomic, run_recovery_drill


def test_run_recovery_drill_emits_passing_evidence_and_writes_artifact_history(tmp_path):
    output_path = tmp_path / "manual" / "durable-recovery-drill.json"
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    evidence = run_recovery_drill(
        output_path=output_path,
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-001",
        retention_limit=2,
        retention_max_age_days=30,
    )

    assert evidence.status == "passed"
    assert evidence.operator_id == "test-operator"
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
    assert manifest["retained_file_names"] == sorted([second.evidence_file_name, third.evidence_file_name])
    assert latest["evidence_file_name"] == third.evidence_file_name


def test_run_recovery_drill_prunes_history_older_than_max_age(tmp_path):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    output_dir.mkdir(parents=True)
    stale_payload = {
        "drill_name": "durable_metadata_restore_recovery",
        "generated_at_utc": (datetime.now(UTC) - timedelta(days=120)).isoformat(),
        "evidence_file_name": "stale.json",
        "operator_id": "old-operator",
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


def test_write_text_atomic_does_not_leave_partial_target(tmp_path, mocker):
    target_path = tmp_path / "manifest.json"

    def _failing_replace(_dst):
        raise OSError("replace failed")

    mocker.patch("scripts.durable_recovery_drill.Path.replace", side_effect=_failing_replace)

    with pytest.raises(OSError, match="replace failed"):
        _write_text_atomic(target_path, '{"status":"passed"}')

    assert not target_path.exists()
    assert list(tmp_path.glob(".recovery-drill-*.tmp")) == []
