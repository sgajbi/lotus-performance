import json
from pathlib import Path

import pytest

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
        "retained_file_names": ["2026-03-14t00-00-00.json", "2026-03-13t00-00-00.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "tenant_id": "tenant-a",
                "correlation_id": "corr-1",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-batch",
                "tenant_id": "tenant-b",
                "correlation_id": "corr-2",
                "backup_identifier": "backup-999",
                "status": "failed",
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "available"
    assert snapshot.reason is None
    assert snapshot.latest_file_name == "2026-03-14t00-00-00.json"
    assert snapshot.retained_file_names == ["2026-03-14t00-00-00.json", "2026-03-13t00-00-00.json"]
    assert snapshot.retention_limit == 30
    assert snapshot.retention_max_age_days == 90
    assert snapshot.total_entries == 2
    assert snapshot.returned_entries == 2
    assert snapshot.applied_filters == {}
    assert len(snapshot.entries) == 2
    assert snapshot.entries[0].operator_id == "ops-user"
    assert snapshot.entries[0].tenant_id == "tenant-a"
    assert snapshot.entries[0].correlation_id == "corr-1"


def test_recovery_drill_history_snapshot_reports_invalid_manifest(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "recovery_drill_manifest_invalid"
    assert snapshot.entries == []


def test_recovery_drill_history_snapshot_reports_invalid_manifest_shape(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": ["2026-03-14t00-00-00.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [{"generated_at_utc": "2026-03-14T00:00:00Z"}],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "recovery_drill_manifest_invalid"
    assert snapshot.entries == []


def test_recovery_drill_history_snapshot_reports_missing_manifest(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "recovery_drill_manifest_missing"
    assert snapshot.entries == []


def test_recovery_drill_history_snapshot_reports_unreadable_manifest(tmp_path, mocker):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest_path = artifact_dir / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    mocker.patch("pathlib.Path.read_text", side_effect=OSError("permission denied"))

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "recovery_drill_manifest_unreadable"


@pytest.mark.parametrize(
    "manifest",
    [
        {
            "latest_file_name": 123,
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [],
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": "not-a-list",
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [],
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": "thirty",
            "retention_max_age_days": 90,
            "entries": [],
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": "ninety",
            "entries": [],
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": "not-a-list",
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": ["not-a-dict"],
        },
        {
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
                    "status": 999,
                }
            ],
        },
        {
            "latest_file_name": "latest.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [],
        },
        {
            "latest_file_name": "../outside.json",
            "retained_file_names": ["../outside.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [],
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["nested/evidence.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [],
        },
        {
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [
                {
                    "evidence_file_name": "../outside.json",
                    "generated_at_utc": "2026-03-14T00:00:00Z",
                    "operator_id": "ops-user",
                    "backup_identifier": "backup-123",
                    "status": "passed",
                }
            ],
        },
    ],
)
def test_recovery_drill_history_snapshot_rejects_additional_invalid_manifest_shapes(tmp_path, manifest):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "recovery_drill_manifest_invalid"


def test_recovery_drill_history_snapshot_applies_filters_and_limit(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": [
            "2026-03-14t00-00-00.json",
            "2026-03-13t00-00-00.json",
            "2026-03-12t00-00-00.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "failed",
            },
            {
                "evidence_file_name": "2026-03-12t00-00-00.json",
                "generated_at_utc": "2026-03-12T00:00:00Z",
                "operator_id": "ops-batch",
                "backup_identifier": "backup-999",
                "status": "passed",
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(
        artifact_directory=artifact_dir,
        limit=1,
        operator_id="ops-user",
        backup_identifier="backup-123",
        status_filter="passed",
    )

    assert snapshot.status == "available"
    assert snapshot.total_entries == 3
    assert snapshot.matched_entries == 1
    assert snapshot.returned_entries == 1
    assert snapshot.applied_filters == {
        "limit": 1,
        "operator_id": "ops-user",
        "backup_identifier": "backup-123",
        "status": "passed",
    }
    assert [entry.evidence_file_name for entry in snapshot.entries] == ["2026-03-14t00-00-00.json"]


def test_recovery_drill_history_snapshot_applies_offset_and_time_window(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "durable-recovery-drill"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-14t00-00-00.json",
        "retained_file_names": [
            "2026-03-14t00-00-00.json",
            "2026-03-13t00-00-00.json",
            "2026-03-12t00-00-00.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-14t00-00-00.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
            {
                "evidence_file_name": "2026-03-12t00-00-00.json",
                "generated_at_utc": "2026-03-12T00:00:00Z",
                "operator_id": "ops-user",
                "backup_identifier": "backup-123",
                "status": "passed",
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_recovery_drill_history_snapshot(
        artifact_directory=artifact_dir,
        limit=1,
        offset=1,
        generated_after="2026-03-12T00:00:00Z",
        generated_before="2026-03-14T00:00:00Z",
        status_filter="passed",
    )

    assert snapshot.total_entries == 3
    assert snapshot.matched_entries == 3
    assert snapshot.returned_entries == 1
    assert snapshot.next_offset == 2
    assert snapshot.applied_filters == {
        "limit": 1,
        "offset": 1,
        "status": "passed",
        "generated_after": "2026-03-12T00:00:00Z",
        "generated_before": "2026-03-14T00:00:00Z",
    }
    assert [entry.evidence_file_name for entry in snapshot.entries] == ["2026-03-13t00-00-00.json"]


def test_recovery_drill_history_snapshot_reads_runtime_config_each_call(tmp_path, mocker):
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
    mocker.patch(
        "app.services.recovery_drill_history_service.get_settings",
        return_value=type("Settings", (), {"RECOVERY_DRILL_ARTIFACT_PATH": Path(artifact_dir)})(),
    )

    snapshot = build_recovery_drill_history_snapshot()

    assert snapshot.status == "available"
    assert snapshot.artifact_directory == str(artifact_dir)
    assert snapshot.latest_file_name == "2026-03-14t00-00-00.json"
