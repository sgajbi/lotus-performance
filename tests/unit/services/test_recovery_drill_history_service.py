import json

from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot


def test_recovery_drill_history_snapshot_reports_missing_directory(tmp_path):
    snapshot = build_recovery_drill_history_snapshot(artifact_directory=tmp_path / "missing")

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "recovery_drill_artifact_directory_missing"
    assert snapshot.entries == []


def test_recovery_drill_history_snapshot_reads_manifest(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": ["2026-03-14t00-00-00.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            }
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "available"
    assert snapshot.reason is None
    assert snapshot.latest_file_name == "2026-03-14t00-00-00.json"
    assert snapshot.retained_file_names == ["2026-03-14t00-00-00.json"]
    assert snapshot.retention_limit == 30
    assert snapshot.retention_max_age_days == 90
    assert len(snapshot.entries) == 1
    assert snapshot.entries[0].operator_id == "ops-user"
