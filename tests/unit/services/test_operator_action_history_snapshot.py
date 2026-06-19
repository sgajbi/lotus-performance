from pathlib import Path

from app.services.operator_action_history_snapshot import (
    build_available_history_snapshot,
    build_unavailable_history_snapshot,
)
from app.services.recovery_drill_history_service import (
    RecoveryDrillHistoryEntry,
    RecoveryDrillHistorySnapshot,
)
from app.services.runtime_retention_history_service import RuntimeRetentionHistorySnapshot


def test_available_history_snapshot_projects_manifest_paging_and_filters() -> None:
    entry = RecoveryDrillHistoryEntry(
        evidence_file_name="2026-03-14t00-00-00.json",
        generated_at_utc="2026-03-14T00:00:00Z",
        operator_id="ops-user",
        backup_identifier="backup-123",
        status="passed",
    )

    snapshot = build_available_history_snapshot(
        RecoveryDrillHistorySnapshot,
        directory=Path("artifacts/durable-recovery-drill"),
        manifest_payload={
            "latest_file_name": "2026-03-14t00-00-00.json",
            "retained_file_names": ["2026-03-14t00-00-00.json"],
            "retention_limit": 30,
            "retention_max_age_days": 90,
            "entries": [],
        },
        entries=[entry],
        total_entries=3,
        matched_entries=2,
        returned_entries=1,
        next_offset=2,
        applied_filters={"operator_id": "ops-user", "limit": 1},
    )

    assert snapshot == RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(Path("artifacts/durable-recovery-drill")),
        latest_file_name="2026-03-14t00-00-00.json",
        retained_file_names=["2026-03-14t00-00-00.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[entry],
        total_entries=3,
        matched_entries=2,
        returned_entries=1,
        next_offset=2,
        applied_filters={"operator_id": "ops-user", "limit": 1},
        reason=None,
    )


def test_unavailable_history_snapshot_projects_empty_operator_history_state() -> None:
    snapshot = build_unavailable_history_snapshot(
        RuntimeRetentionHistorySnapshot,
        directory=Path("artifacts/runtime-retention-cleanup"),
        applied_filters={"status": "applied"},
        reason="runtime_retention_manifest_unreadable",
    )

    assert snapshot == RuntimeRetentionHistorySnapshot(
        status="unavailable",
        artifact_directory=str(Path("artifacts/runtime-retention-cleanup")),
        latest_file_name=None,
        retained_file_names=[],
        retention_limit=None,
        retention_max_age_days=None,
        entries=[],
        total_entries=0,
        matched_entries=0,
        returned_entries=0,
        next_offset=None,
        applied_filters={"status": "applied"},
        reason="runtime_retention_manifest_unreadable",
    )
