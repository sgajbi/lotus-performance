import json

from scripts.durable_recovery_drill import REQUIRED_TABLES, run_recovery_drill


def test_run_recovery_drill_emits_passing_evidence_and_writes_artifact(tmp_path):
    output_path = tmp_path / "artifacts" / "durable-recovery-drill.json"

    evidence = run_recovery_drill(output_path=output_path)

    assert evidence.status == "passed"
    assert evidence.processed_payload_count == 1
    assert evidence.materialized_artifact_exists is True
    assert evidence.owned_tables_present == list(REQUIRED_TABLES)
    assert output_path.exists() is True

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "passed"
    assert persisted["processed_payload_count"] == 1
    assert persisted["owned_tables_present"] == list(REQUIRED_TABLES)
