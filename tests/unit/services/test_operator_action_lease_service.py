import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.services.operator_action_lease_service import (
    OperatorActionLeaseMetadata,
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
