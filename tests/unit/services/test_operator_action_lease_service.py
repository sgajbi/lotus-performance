import json

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
    )

    with operator_action_lease(artifact_directory=artifact_dir, action_key=action_key, metadata=metadata):
        with pytest.raises(HTTPException) as exc_info:
            with operator_action_lease(artifact_directory=artifact_dir, action_key=action_key, metadata=metadata):
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
    )

    with operator_action_lease(artifact_directory=artifact_dir, action_key=action_key, metadata=metadata):
        lock_path = artifact_dir / ".action-locks" / f"{action_key}.lock"
        assert lock_path.exists()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["operator_id"] == "ops-user"

    assert not (artifact_dir / ".action-locks" / f"{action_key}.lock").exists()
