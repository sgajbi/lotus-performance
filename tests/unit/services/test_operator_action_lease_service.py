import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException

from app.services.operator_action_lease_service import (
    OPERATOR_ACTION_LEASE_DIRECTORY_UNREADABLE_REASON,
    OPERATOR_ACTION_LEASE_INVALID_REASON,
    OPERATOR_ACTION_RECLAIM_EVENT_INVALID_REASON,
    OPERATOR_ACTION_RECLAIM_HISTORY_INVALID_REASON,
    ActiveOperatorActionLease,
    OperatorActionLeaseMetadata,
    _active_lease_required_string_fields,
    _has_valid_reclaimed_event_fields,
    _has_valid_reclaimed_event_string_fields,
    _matching_active_operator_action_lease,
    _matching_reclaimed_event_action_name,
    _parse_reclaimed_event_payload,
    _read_active_operator_action_lease,
    _read_latest_reclaimed_lease,
    _read_recent_reclaimed_leases,
    _recent_reclaimed_lease_events_from_payload,
    _reclaim_stale_lock,
    _stale_lock_reclaim_candidate,
    _write_latest_reclaimed_lease,
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


def test_operator_action_key_builders_normalize_optional_identity_parts():
    assert (
        build_runtime_retention_action_key(
            operator_id=" ops-user ",
            tenant_id=" ",
            apply=False,
            retention_days=30,
            job_id=" ticket-7 ",
        )
        == "runtime-retention-ops-user-no-tenant-dry-run-30-ticket-7"
    )
    assert (
        build_recovery_drill_action_key(
            operator_id=" ops-user ",
            tenant_id=" tenant-a ",
            backup_identifier=" backup-123 ",
        )
        == "recovery-drill-ops-user-tenant-a-backup-123"
    )


def test_operator_action_key_builders_reject_blank_required_parts():
    with pytest.raises(ValueError, match="operator_id must not be blank"):
        build_runtime_retention_action_key(
            operator_id=" ",
            tenant_id=None,
            apply=False,
            retention_days=30,
            job_id=None,
        )
    with pytest.raises(ValueError, match="backup_identifier must not be blank"):
        build_recovery_drill_action_key(
            operator_id="ops-user",
            tenant_id=None,
            backup_identifier=" ",
        )


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


def test_operator_action_lease_normalizes_written_metadata(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    metadata = OperatorActionLeaseMetadata(
        action_name=" recovery_drill ",
        operator_id=" ops-user ",
        tenant_id=" ",
        governed_target=" backup-123 ",
        acquired_at_utc=" 2026-03-15T00:00:00Z ",
    )

    with operator_action_lease(
        artifact_directory=artifact_dir,
        action_key=" recovery-drill-ops-user-backup-123 ",
        metadata=metadata,
        stale_after_seconds=3600.0,
    ):
        lock_path = artifact_dir / ".action-locks" / "recovery-drill-ops-user-backup-123.lock"
        payload = json.loads(lock_path.read_text(encoding="utf-8"))

    assert payload == {
        "action_name": "recovery_drill",
        "operator_id": "ops-user",
        "tenant_id": None,
        "governed_target": "backup-123",
        "acquired_at_utc": "2026-03-15T00:00:00Z",
    }


def test_operator_action_lease_rejects_blank_metadata_before_writing(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    metadata = OperatorActionLeaseMetadata(
        action_name="recovery_drill",
        operator_id=" ",
        tenant_id=None,
        governed_target="backup-123",
        acquired_at_utc="2026-03-15T00:00:00Z",
    )

    with pytest.raises(ValueError, match="operator_id must not be blank"):
        with operator_action_lease(
            artifact_directory=artifact_dir,
            action_key="recovery-drill-ops-user-backup-123",
            metadata=metadata,
            stale_after_seconds=3600.0,
        ):
            pass

    assert not (artifact_dir / ".action-locks").exists()


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


def test_operator_action_lease_snapshot_reports_available_when_lock_directory_is_missing(tmp_path):
    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=tmp_path / "artifacts",
        action_name="recovery_drill",
    )

    assert snapshot.status == "available"
    assert snapshot.reason is None
    assert snapshot.active_leases == ()
    assert snapshot.latest_reclaimed_lease is None
    assert snapshot.recent_reclaimed_leases == ()


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
    assert snapshot.reason == OPERATOR_ACTION_LEASE_INVALID_REASON
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


def test_operator_action_lease_snapshot_combines_active_latest_and_recent_reclaim_events(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    (locks_dir / "recovery-drill.lock").write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-active",
                "tenant_id": "tenant-a",
                "governed_target": "backup-active",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    reclaim_payload = {
        "action_key": "recovery-drill-ops-user-tenant-a-backup-123",
        "action_name": "recovery_drill",
        "operator_id": "ops-user",
        "tenant_id": "tenant-a",
        "governed_target": "backup-123",
        "acquired_at_utc": "2026-03-15T01:00:00Z",
        "reclaimed_at_utc": "2026-03-15T02:00:00Z",
        "stale_after_seconds": 300.0,
        "reclaim_count": 2,
    }
    (locks_dir / "latest-reclaim.json").write_text(json.dumps(reclaim_payload), encoding="utf-8")
    (locks_dir / "reclaim-history.json").write_text(json.dumps([reclaim_payload]), encoding="utf-8")

    snapshot = build_operator_action_lease_snapshot(
        artifact_directory=artifact_dir,
        action_name="recovery_drill",
    )

    assert snapshot.status == "available"
    assert [lease.operator_id for lease in snapshot.active_leases] == ["ops-active"]
    assert snapshot.latest_reclaimed_lease is not None
    assert snapshot.latest_reclaimed_lease.governed_target == "backup-123"
    assert len(snapshot.recent_reclaimed_leases) == 1
    assert snapshot.recent_reclaimed_leases[0].reclaimed_at_utc == "2026-03-15T02:00:00Z"


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
    assert snapshot.reason == OPERATOR_ACTION_RECLAIM_EVENT_INVALID_REASON


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
    assert snapshot.reason == OPERATOR_ACTION_RECLAIM_HISTORY_INVALID_REASON


@pytest.mark.parametrize(
    ("payload",),
    [
        ({"operator_id": "ops-user"},),
        (
            {
                "action_name": 1,
                "operator_id": "ops-user",
                "governed_target": "x",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": 1,
                "governed_target": "x",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": 1,
                "governed_target": "x",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "   ",
                "governed_target": "x",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "governed_target": 1,
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            },
        ),
        ({"action_name": "recovery_drill", "operator_id": "ops-user", "governed_target": "x", "acquired_at_utc": 1},),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "governed_target": "x",
                "acquired_at_utc": "bad",
            },
        ),
    ],
)
def test_read_active_operator_action_lease_rejects_invalid_payload_shapes(tmp_path, payload):
    lock_path = tmp_path / "bad.lock"
    lock_path.write_text(json.dumps(payload), encoding="utf-8")

    assert _read_active_operator_action_lease(lock_path=lock_path).__class__.__name__ == "_InvalidLease"


def test_read_active_operator_action_lease_accepts_absent_optional_tenant(tmp_path):
    lock_path = tmp_path / "recovery.lock"
    lock_path.write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "governed_target": "backup-123",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    lease = _read_active_operator_action_lease(lock_path=lock_path)

    assert isinstance(lease, ActiveOperatorActionLease)
    assert lease.tenant_id is None
    assert lease.action_key == "recovery"


def test_active_lease_required_string_fields_projects_required_values():
    assert _active_lease_required_string_fields(
        {
            "action_name": " recovery_drill ",
            "operator_id": " ops-user ",
            "governed_target": " backup-123 ",
            "acquired_at_utc": " 2026-03-15T00:00:00Z ",
            "tenant_id": 123,
        }
    ) == (
        " recovery_drill ",
        " ops-user ",
        " backup-123 ",
        " 2026-03-15T00:00:00Z ",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "operator_id": "ops-user",
            "governed_target": "backup-123",
            "acquired_at_utc": "2026-03-15T00:00:00Z",
        },
        {
            "action_name": "recovery_drill",
            "operator_id": " ",
            "governed_target": "backup-123",
            "acquired_at_utc": "2026-03-15T00:00:00Z",
        },
        {
            "action_name": "recovery_drill",
            "operator_id": "ops-user",
            "governed_target": 123,
            "acquired_at_utc": "2026-03-15T00:00:00Z",
        },
        {
            "action_name": "recovery_drill",
            "operator_id": "ops-user",
            "governed_target": "backup-123",
            "acquired_at_utc": None,
        },
    ],
)
def test_active_lease_required_string_fields_rejects_missing_blank_or_non_string_values(payload):
    assert _active_lease_required_string_fields(payload).__class__.__name__ == "_InvalidLease"


def test_build_operator_action_lease_snapshot_reports_unreadable_directory(monkeypatch, tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True)
    monkeypatch.setattr(
        type(locks_dir),
        "glob",
        lambda self, pattern: (_ for _ in ()).throw(OSError("boom")),
    )

    snapshot = build_operator_action_lease_snapshot(artifact_directory=artifact_dir, action_name="recovery_drill")

    assert snapshot.status == "unavailable"
    assert snapshot.reason == OPERATOR_ACTION_LEASE_DIRECTORY_UNREADABLE_REASON


def test_read_reclaim_files_reject_invalid_json_and_shapes(tmp_path, caplog):
    locks_dir = tmp_path / ".action-locks"
    locks_dir.mkdir(parents=True)
    (locks_dir / "latest-reclaim.json").write_text("{bad", encoding="utf-8")
    (locks_dir / "reclaim-history.json").write_text("{bad", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_lease_service"):
        assert (
            _read_latest_reclaimed_lease(locks_dir=locks_dir, action_name="recovery_drill").__class__.__name__
            == "_InvalidLease"
        )
        assert (
            _read_recent_reclaimed_leases(locks_dir=locks_dir, action_name="recovery_drill").__class__.__name__
            == "_InvalidLease"
        )

    assert "Operator action lease evidence invalid JSON" in caplog.text
    assert "latest-reclaim.json" in caplog.text
    assert "reclaim-history.json" in caplog.text


def test_parse_reclaimed_event_payload_rejects_invalid_fields_and_filters_other_action():
    assert (
        _parse_reclaimed_event_payload(payload=[], action_name="recovery_drill").__class__.__name__ == "_InvalidLease"
    )
    assert (
        _parse_reclaimed_event_payload(
            payload={"action_name": "runtime_retention_cleanup"},
            action_name="recovery_drill",
        )
        is None
    )
    invalid = {
        "action_name": "recovery_drill",
        "operator_id": "ops-user",
        "tenant_id": 1,
        "governed_target": "backup-1",
        "acquired_at_utc": "2026-03-15T00:00:00Z",
        "reclaimed_at_utc": "2026-03-15T01:00:00Z",
        "stale_after_seconds": 30.0,
        "reclaim_count": 1,
        "action_key": "key",
    }
    assert (
        _parse_reclaimed_event_payload(payload=invalid, action_name="recovery_drill").__class__.__name__
        == "_InvalidLease"
    )
    blank_operator = {
        "action_key": "key",
        "action_name": "recovery_drill",
        "operator_id": " ",
        "tenant_id": None,
        "governed_target": "backup-1",
        "acquired_at_utc": "2026-03-15T00:00:00Z",
        "reclaimed_at_utc": "2026-03-15T01:00:00Z",
        "stale_after_seconds": 30.0,
        "reclaim_count": 1,
    }
    assert (
        _parse_reclaimed_event_payload(payload=blank_operator, action_name="recovery_drill").__class__.__name__
        == "_InvalidLease"
    )


def test_matching_reclaimed_event_action_name_filters_payload_action():
    payload = {"action_name": "recovery_drill"}

    assert _matching_reclaimed_event_action_name(payload=payload, action_name="recovery_drill") == "recovery_drill"
    assert _matching_reclaimed_event_action_name(payload=payload, action_name=None) == "recovery_drill"
    assert _matching_reclaimed_event_action_name(payload=payload, action_name="runtime_retention_cleanup") is None
    assert (
        _matching_reclaimed_event_action_name(
            payload={"action_name": " "}, action_name="recovery_drill"
        ).__class__.__name__
        == "_InvalidLease"
    )
    assert (
        _matching_reclaimed_event_action_name(
            payload={"action_name": 123}, action_name="recovery_drill"
        ).__class__.__name__
        == "_InvalidLease"
    )


def test_has_valid_reclaimed_event_fields_checks_complete_post_filter_shape():
    payload = {
        "action_key": "key",
        "operator_id": "ops-user",
        "tenant_id": None,
        "governed_target": "backup-1",
        "acquired_at_utc": "2026-03-15T00:00:00Z",
        "reclaimed_at_utc": "2026-03-15T01:00:00Z",
        "stale_after_seconds": 30.0,
        "reclaim_count": 1,
    }

    assert _has_valid_reclaimed_event_fields(payload)
    assert not _has_valid_reclaimed_event_fields({**payload, "reclaim_count": "1"})


def test_has_valid_reclaimed_event_string_fields_allows_absent_optional_tenant():
    payload = {
        "action_key": "key",
        "operator_id": "ops-user",
        "tenant_id": None,
        "governed_target": "backup-1",
        "acquired_at_utc": "2026-03-15T00:00:00Z",
        "reclaimed_at_utc": "2026-03-15T01:00:00Z",
    }

    assert _has_valid_reclaimed_event_string_fields(payload)
    assert not _has_valid_reclaimed_event_string_fields({**payload, "action_key": " "})
    assert not _has_valid_reclaimed_event_string_fields({**payload, "tenant_id": 1})


def test_write_latest_reclaimed_lease_increments_prior_count_and_history(tmp_path):
    locks_dir = tmp_path / ".action-locks"
    locks_dir.mkdir(parents=True)
    existing = {
        "action_key": "key-1",
        "action_name": "recovery_drill",
        "operator_id": "ops-user",
        "tenant_id": None,
        "governed_target": "backup-1",
        "acquired_at_utc": "2026-03-15T00:00:00Z",
        "reclaimed_at_utc": "2026-03-15T00:10:00Z",
        "stale_after_seconds": 30.0,
        "reclaim_count": 2,
    }
    (locks_dir / "latest-reclaim.json").write_text(json.dumps(existing), encoding="utf-8")
    _write_latest_reclaimed_lease(
        locks_dir=locks_dir,
        event=type(
            "Event",
            (),
            {
                "action_key": "key-1",
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:20:00Z",
                "reclaimed_at_utc": "2026-03-15T00:30:00Z",
                "stale_after_seconds": 30.0,
                "reclaim_count": 0,
            },
        )(),
    )

    latest = json.loads((locks_dir / "latest-reclaim.json").read_text(encoding="utf-8"))
    history = json.loads((locks_dir / "reclaim-history.json").read_text(encoding="utf-8"))
    assert latest["reclaim_count"] == 3
    assert history[0]["reclaim_count"] == 3


def test_reclaim_stale_lock_invalid_paths(tmp_path):
    lock_path = tmp_path / "bad.lock"
    lock_path.write_text('{"action_name":"recovery_drill"}', encoding="utf-8")
    assert (
        _reclaim_stale_lock(
            lock_path=lock_path,
            stale_after_seconds=30.0,
            action_key="key",
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is False
    )

    future_lock_path = tmp_path / "future.lock"
    future_lock_path.write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T01:05:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert (
        _reclaim_stale_lock(
            lock_path=future_lock_path,
            stale_after_seconds=30.0,
            action_key="key",
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is False
    )
    assert (
        _reclaim_stale_lock(
            lock_path=lock_path,
            stale_after_seconds=0.0,
            action_key="key",
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is False
    )


def test_stale_lock_reclaim_candidate_resolves_only_reclaimable_locks(tmp_path):
    lock_path = tmp_path / "stale.lock"
    lock_path.write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    reclaim_candidate = _stale_lock_reclaim_candidate(
        lock_path=lock_path,
        stale_after_seconds=30.0,
        now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
    )

    assert reclaim_candidate is not None
    assert reclaim_candidate.active_lease.operator_id == "ops-user"
    assert reclaim_candidate.current_time == datetime(2026, 3, 15, 1, 0, tzinfo=UTC)
    assert (
        _stale_lock_reclaim_candidate(
            lock_path=lock_path,
            stale_after_seconds=3600.0,
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is None
    )
    assert (
        _stale_lock_reclaim_candidate(
            lock_path=lock_path,
            stale_after_seconds=0.0,
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is None
    )


def test_stale_lock_reclaim_candidate_rejects_invalid_lock_payload(tmp_path):
    lock_path = tmp_path / "bad.lock"
    lock_path.write_text("{bad", encoding="utf-8")

    assert (
        _stale_lock_reclaim_candidate(
            lock_path=lock_path,
            stale_after_seconds=30.0,
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is None
    )


def test_operator_action_lease_rejects_running_action_when_lock_payload_is_unreadable(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    action_key = build_recovery_drill_action_key(
        operator_id="ops-user",
        tenant_id=None,
        backup_identifier="backup-1",
    )
    lock_dir = artifact_dir / ".action-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / f"{action_key}.lock").write_text("{bad", encoding="utf-8")
    metadata = OperatorActionLeaseMetadata(
        action_name="recovery_drill",
        operator_id="ops-user",
        tenant_id=None,
        governed_target="backup-1",
        acquired_at_utc="2026-03-15T00:00:00Z",
    )

    with pytest.raises(HTTPException) as exc_info:
        with operator_action_lease(
            artifact_directory=artifact_dir,
            action_key=action_key,
            metadata=metadata,
            stale_after_seconds=3600.0,
        ):
            pass

    assert exc_info.value.detail["action_key"] == action_key
    assert "active_operator_id" not in exc_info.value.detail or exc_info.value.detail["active_operator_id"] is None


def test_build_operator_action_lease_snapshot_ignores_other_action_names(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    locks_dir = artifact_dir / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
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
    assert snapshot.active_leases == ()


def test_matching_active_operator_action_lease_filters_candidates():
    lease = ActiveOperatorActionLease(
        action_key="recovery-drill-ops-user-backup-1",
        action_name="recovery_drill",
        operator_id="ops-user",
        tenant_id=None,
        governed_target="backup-1",
        acquired_at_utc="2026-03-15T00:00:00Z",
    )

    assert _matching_active_operator_action_lease(lease_candidate=lease, action_name="recovery_drill") == lease
    assert _matching_active_operator_action_lease(lease_candidate=lease, action_name=None) == lease
    assert (
        _matching_active_operator_action_lease(lease_candidate=lease, action_name="runtime_retention_cleanup") is None
    )
    assert _matching_active_operator_action_lease(lease_candidate=None, action_name="recovery_drill") is None
    assert (
        _matching_active_operator_action_lease(
            lease_candidate=cast(Any, object()),
            action_name="recovery_drill",
        ).__class__.__name__
        == "_LeaseSnapshotFailure"
    )


def test_read_recent_reclaimed_leases_rejects_non_list_payload(tmp_path):
    locks_dir = tmp_path / ".action-locks"
    locks_dir.mkdir(parents=True)
    (locks_dir / "reclaim-history.json").write_text("{}", encoding="utf-8")

    assert (
        _read_recent_reclaimed_leases(locks_dir=locks_dir, action_name="recovery_drill").__class__.__name__
        == "_InvalidLease"
    )


def test_recent_reclaimed_lease_events_from_payload_filters_by_action_name():
    payload = [
        {
            "action_key": "recovery-drill-ops-user-backup-1",
            "action_name": "recovery_drill",
            "operator_id": "ops-user",
            "tenant_id": None,
            "governed_target": "backup-1",
            "acquired_at_utc": "2026-03-15T00:00:00Z",
            "reclaimed_at_utc": "2026-03-15T01:00:00Z",
            "stale_after_seconds": 300.0,
            "reclaim_count": 1,
        },
        {
            "action_key": "runtime-retention-ops-user-apply-30",
            "action_name": "runtime_retention_cleanup",
            "operator_id": "ops-user",
            "tenant_id": None,
            "governed_target": "apply:30:no-job",
            "acquired_at_utc": "2026-03-15T00:00:00Z",
            "reclaimed_at_utc": "2026-03-15T01:00:00Z",
            "stale_after_seconds": 300.0,
            "reclaim_count": 1,
        },
    ]

    events = _recent_reclaimed_lease_events_from_payload(payload=payload, action_name="recovery_drill")

    assert isinstance(events, tuple)
    assert len(events) == 1
    assert events[0].action_name == "recovery_drill"
    assert events[0].governed_target == "backup-1"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [{"action_name": "recovery_drill"}],
    ],
)
def test_recent_reclaimed_lease_events_from_payload_rejects_invalid_history_payload(payload):
    assert (
        _recent_reclaimed_lease_events_from_payload(payload=payload, action_name="recovery_drill").__class__.__name__
        == "_InvalidLease"
    )


@pytest.mark.parametrize(
    ("payload",),
    [
        ({"action_name": None},),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": 1,
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": 30.0,
                "reclaim_count": 1,
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": True,
                "reclaim_count": 1,
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": 30.0,
                "reclaim_count": True,
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": 1,
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": 30.0,
                "reclaim_count": 1,
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": 1,
                "stale_after_seconds": 30.0,
                "reclaim_count": 1,
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": "30",
                "reclaim_count": 1,
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": 30.0,
                "reclaim_count": "1",
                "action_key": "key",
            },
        ),
        (
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "bad",
                "reclaimed_at_utc": "2026-03-15T01:00:00Z",
                "stale_after_seconds": 30.0,
                "reclaim_count": 1,
                "action_key": "key",
            },
        ),
    ],
)
def test_parse_reclaimed_event_payload_rejects_remaining_invalid_shapes(payload):
    assert (
        _parse_reclaimed_event_payload(payload=payload, action_name="recovery_drill").__class__.__name__
        == "_InvalidLease"
    )


def test_reclaim_stale_lock_handles_invalid_json_and_failed_reclaim_write(monkeypatch, tmp_path, caplog):
    lock_path = tmp_path / "bad.lock"
    lock_path.write_text("{bad", encoding="utf-8")
    assert (
        _reclaim_stale_lock(
            lock_path=lock_path,
            stale_after_seconds=30.0,
            action_key="key",
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is False
    )

    valid_lock = tmp_path / "valid.lock"
    valid_lock.write_text(
        json.dumps(
            {
                "action_name": "recovery_drill",
                "operator_id": "ops-user",
                "tenant_id": None,
                "governed_target": "backup-1",
                "acquired_at_utc": "2026-03-15T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.services.operator_action_lease_service._write_latest_reclaimed_lease",
        lambda **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )
    caplog.set_level(logging.WARNING, logger="app.services.operator_action_lease_service")
    assert (
        _reclaim_stale_lock(
            lock_path=valid_lock,
            stale_after_seconds=30.0,
            action_key="key",
            now_utc=datetime(2026, 3, 15, 1, 0, tzinfo=UTC),
        )
        is True
    )
    assert "operator_action_reclaim_evidence_write_failed" in caplog.text
