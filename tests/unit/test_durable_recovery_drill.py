import json

from scripts.durable_recovery_drill import REQUIRED_TABLES, run_recovery_drill


def test_run_recovery_drill_emits_passing_evidence_and_writes_artifact_history(tmp_path):
    output_path = tmp_path / "manual" / "durable-recovery-drill.json"
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    evidence = run_recovery_drill(
        output_path=output_path,
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-001",
        retention_limit=2,
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
    assert manifest["retained_file_names"] == [evidence.evidence_file_name]


def test_run_recovery_drill_prunes_history_to_retention_limit(tmp_path):
    output_dir = tmp_path / "artifacts" / "durable-recovery-drill"

    first = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-001",
        retention_limit=2,
    )
    second = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-002",
        retention_limit=2,
    )
    third = run_recovery_drill(
        output_dir=output_dir,
        operator_id="test-operator",
        backup_identifier="backup-003",
        retention_limit=2,
    )

    retained = sorted(
        path.name for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
    )
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert first.evidence_file_name not in retained
    assert retained == sorted([second.evidence_file_name, third.evidence_file_name])
    assert manifest["retention_limit"] == 2
    assert manifest["retained_file_names"] == sorted([second.evidence_file_name, third.evidence_file_name])
    assert latest["evidence_file_name"] == third.evidence_file_name
