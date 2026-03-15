import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.services.operator_action_lease_service import (
    OperatorActionLeaseMetadata,
    build_operator_action_lease_snapshot,
    build_recovery_drill_action_key,
    build_runtime_retention_action_key,
    operator_action_lease,
)


def test_operator_action_lease_rejects_concurrent_same_key(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    action_key = build_runtime_retention_action_key(
        operator_id="ops-user",
        tenant_id="tenant-a",
        apply=False,
        retention_days=30,
        job_id="ticket-7",
    )
    metadata = OperatorActionLeaseMetadata(
        action_name="runtime_retention_cleanup",
        operator_id="ops-user",
        tenant_id="tenant-a",
        governed_target="dry_run:30:ticket-7",
        acquired_at_utc=datetime.now(UTC).isoformat(),
    )

    with operator_action_lease(
        artifact_directory=artifact_dir,
        action_key=action_key,
        metadata=metadata,
        stale_after_seconds=3600.0,
    ):
        with pytest.raises(HTTPException) as exc_info:
            with operator_action_lease(
                artifact_directory=artifact_dir,
                action_key=action_key,
                metadata=metadata,
                stale_after_seconds=3600.0,
            ):
                pass

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "runtime_retention_cleanup_already_running"
    assert exc_info.value.detail["active_operator_id"] == "ops-user"


def test_operator_action_lease_cleans_up_lock_file(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    action_key = build_recovery_drill_action_key(
        operator_id="ops-user",
        tenant_id="tenant-a",
        backup_identifier="backup-123",
    )
    metadata = OperatorActionLeaseMetadata(
        action_name="recovery_drill",
        operator_id="ops-user",
        tenant_id="tenant-a",
        governed_target="backup-123",
        acquired_at_utc=datetime.now(UTC).isoformat(),
    )

    with operator_action_lease(
        artifact_directory=artifact_dir,
        action_key=action_key,
        metadata=metadata,
        stale_after_seconds=3600.0,
    ):
        lock_path = artifact_dir / ".action-locks" / f"{action_key}.lock"
        assert lock_path.exists()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["operator_id"] == "ops-user"

    assert not (artifact_dir / ".action-locks" / f"{action_key}.lock").exists()


def test_operator_action_lease_reclaims_stale_lock(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    action_key = build_recovery_drill_action_key(
        operator_id="ops-user",
        tenant_id="tenant-a",
        backup_identifier="backup-123",
    )
    lock_dir = artifact_dir / ".action-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{action_key}.lock"
    lock_path.write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": "tenant-a",
                "governed_target": "backup-123",
                "acquired_at_utc": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    metadata = OperatorActionLeaseMetadata(
        action_name="recovery_drill",
        operator_id="ops-user",
        tenant_id="tenant-a",
        governed_target="backup-123",
        acquired_at_utc=datetime.now(UTC).isoformat(),
    )

    with operator_action_lease(
        artifact_directory=artifact_dir,
        action_key=action_key,
        metadata=metadata,
        stale_after_seconds=300.0,
    ):
        assert lock_path.exists()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["acquired_at_utc"] == metadata.acquired_at_utc
    latest_reclaim_path = artifact_dir / ".action-locks" / "latest-reclaim.json"
    latest_reclaim = json.loads(latest_reclaim_path.read_text(encoding="utf-8"))
    assert latest_reclaim["action_key"] == action_key
    assert latest_reclaim["action_name"] == "recovery_drill"
    assert latest_reclaim["governed_target"] == "backup-123"
    assert latest_reclaim["stale_after_seconds"] == 300.0
    assert latest_reclaim["reclaim_count"] == 1


def test_operator_action_lease_snapshot_lists_oldest_active_leases(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "recovery-drill-first.lock").write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-a",
                "tenant_id": "tenant-a",
                "governed_target": "backup-a",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (locks_dir / "recovery-drill-second.lock").write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-b",
                "tenant_id": "tenant-b",
                "governed_target": "backup-b",
                "acquired_at_utc": "2026-03-15T01:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (locks_dir / "runtime-retention.lock").write_text(
        json.dumps(
            {
                "action_name": "runtime_retention_cleanup",
                "operator_id": "ops-c",
                "tenant_id": "tenant-c",
                "governed_target": "apply:30:job-1",
                "acquired_at_utc": "2026-03-15T02:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "available"
    assert snapshot.reason is None
    assert len(snapshot.active_leases) == 2
    assert snapshot.active_leases[0].operator_id == "ops-a"
    assert snapshot.active_leases[0].governed_target == "backup-a"
    assert snapshot.active_leases[1].operator_id == "ops-b"


def test_operator_action_lease_snapshot_reports_invalid_payload(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "bad.lock").write_text('{"action_name":"recovery_drill"}', encoding="utf-8")

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "operator_action_lease_invalid"
    assert snapshot.active_leases == ()


def test_operator_action_lease_snapshot_exposes_latest_reclaimed_event(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "latest-reclaim.json").write_text(
        json.dumps(
            {
                "action_key": "recovery-drill-ops-user-tenant-a-backup-123",
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": "tenant-a",
                "governed_target": "backup-123",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": "2026-03-15T02:00:00Z",
                "stale_after_seconds": 300.0,
                "reclaim_count": 2,
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "available"
    assert snapshot.latest_reclaimed_lease is not None
    assert snapshot.latest_reclaimed_lease.operator_id == "ops-user"
    assert snapshot.latest_reclaimed_lease.governed_target == "backup-123"
    assert snapshot.latest_reclaimed_lease.reclaim_count == 2
    assert snapshot.recent_reclaimed_leases == ()


def test_operator_action_lease_snapshot_exposes_recent_reclaim_history(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "reclaim-history.json").write_text(
        json.dumps(
            [
                {
                    "action_key": "recovery-drill-ops-user-tenant-a-backup-123",
                    "action_name": "recovery_drill",
                    "operator_id": "ops-user",
                    "tenant_id": "tenant-a",
                    "governed_target": "backup-123",
                    "acquired_at_utc": "2026-03-15T00:00:00Z",
                    "reclaimed_at_utc": "2026-03-15T02:00:00Z",
                    "stale_after_seconds": 300.0,
                    "reclaim_count": 2,
                },
                {
                    "action_key": "runtime-retention-ops-batch-tenant-b-apply-30-job-1",
                    "action_name": "runtime_retention_cleanup",
                    "operator_id": "ops-batch",
                    "tenant_id": "tenant-b",
                    "governed_target": "apply:30:job-1",
                    "acquired_at_utc": "2026-03-15T01:00:00Z",
                    "reclaimed_at_utc": "2026-03-15T03:00:00Z",
                    "stale_after_seconds": 300.0,
                    "reclaim_count": 1,
                },
            ]
        ),
        encoding="utf-8",
    )

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "available"
    assert len(snapshot.recent_reclaimed_leases) == 1
    assert snapshot.recent_reclaimed_leases[0].operator_id == "ops-user"
    assert snapshot.recent_reclaimed_leases[0].reclaim_count == 2


def test_operator_action_lease_snapshot_reports_invalid_reclaim_payload(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "latest-reclaim.json").write_text('{"action_name":"recovery_drill"}', encoding="utf-8")

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "operator_action_reclaim_event_invalid"


def test_operator_action_lease_snapshot_reports_invalid_reclaim_history_payload(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "reclaim-history.json").write_text('[{"action_name":"recovery_drill"}]', encoding="utf-8")

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "operator_action_reclaim_history_invalid"
