from pathlib import Path

from app.services import runtime_status_operator_action
from app.services.operator_action_lease_service import (
    OPERATOR_ACTION_LEASE_INVALID_REASON,
    ReclaimedOperatorActionLeaseEvent,
)
from app.services.runtime_status_domain import OperatorActionStatus, RecentOperatorActionReclaim


def test_runtime_status_operator_action_status_handles_exceptions_and_unavailable_snapshot(mocker, caplog):
    mocker.patch(
        "app.services.runtime_status_operator_action.build_operator_action_lease_snapshot",
        side_effect=RuntimeError("boom"),
    )
    with caplog.at_level("WARNING", logger="app.services.runtime_status_operator_action"):
        unavailable = runtime_status_operator_action.build_operator_action_status(
            artifact_directory=Path("artifacts/runtime-retention-cleanup"),
            action_name="runtime_retention_cleanup",
        )
    assert unavailable.status == "unavailable"
    assert unavailable.reason == "runtime_retention_operator_action_read_failed"
    assert "Runtime status read degraded." in caplog.text

    mocker.patch(
        "app.services.runtime_status_operator_action.build_operator_action_lease_snapshot",
        return_value=type(
            "LeaseSnapshot",
            (),
            {
                "status": "unavailable",
                "reason": OPERATOR_ACTION_LEASE_INVALID_REASON,
                "active_leases": (),
                "latest_reclaimed_lease": None,
                "recent_reclaimed_leases": (),
            },
        )(),
    )
    unavailable_snapshot = runtime_status_operator_action.build_operator_action_status(
        artifact_directory=Path("artifacts/runtime-retention-cleanup"),
        action_name="runtime_retention_cleanup",
    )
    assert unavailable_snapshot.status == "unavailable"
    assert unavailable_snapshot.reason == OPERATOR_ACTION_LEASE_INVALID_REASON


def test_unavailable_operator_action_status_clears_operator_evidence():
    status = runtime_status_operator_action._unavailable_operator_action_status(reason="lease_store_unavailable")

    assert status.status == "unavailable"
    assert status.reason == "lease_store_unavailable"
    assert status.active_run_count == 0
    assert status.oldest_active_run_operator_id is None
    assert status.latest_reclaimed_run_operator_id is None
    assert status.reclaimed_run_count == 0
    assert status.recent_reclaimed_runs == ()


def test_latest_reclaimed_run_status_fields_clear_absent_reclaim():
    fields = runtime_status_operator_action.latest_reclaimed_run_status_fields(None)

    assert fields["latest_reclaimed_run_operator_id"] is None
    assert fields["latest_reclaimed_run_tenant_id"] is None
    assert fields["latest_reclaimed_run_governed_target"] is None
    assert fields["latest_reclaimed_run_acquired_at_utc"] is None
    assert fields["latest_reclaimed_run_reclaimed_at_utc"] is None
    assert fields["latest_reclaimed_run_age_seconds"] is None
    assert fields["reclaimed_run_count"] == 0


def test_latest_reclaimed_run_status_fields_project_reclaim_evidence():
    fields = runtime_status_operator_action.latest_reclaimed_run_status_fields(
        ReclaimedOperatorActionLeaseEvent(
            action_key="runtime-retention-ops-user",
            action_name="runtime_retention_cleanup",
            operator_id="ops-user",
            tenant_id="tenant-a",
            governed_target="runtime-retention",
            acquired_at_utc="2026-05-31T09:00:00Z",
            reclaimed_at_utc="2026-05-31T09:30:00Z",
            stale_after_seconds=900.0,
            reclaim_count=3,
        )
    )

    assert fields["latest_reclaimed_run_operator_id"] == "ops-user"
    assert fields["latest_reclaimed_run_tenant_id"] == "tenant-a"
    assert fields["latest_reclaimed_run_governed_target"] == "runtime-retention"
    assert fields["latest_reclaimed_run_acquired_at_utc"] == "2026-05-31T09:00:00Z"
    assert fields["latest_reclaimed_run_reclaimed_at_utc"] == "2026-05-31T09:30:00Z"
    assert fields["latest_reclaimed_run_age_seconds"] is not None
    assert fields["reclaimed_run_count"] == 3


def test_runtime_status_operator_action_status_normalizes_naive_timestamps(mocker):
    mocker.patch(
        "app.services.runtime_status_operator_action.build_operator_action_lease_snapshot",
        return_value=type(
            "LeaseSnapshot",
            (),
            {
                "status": "available",
                "reason": None,
                "active_leases": (
                    type(
                        "Lease",
                        (),
                        {
                            "operator_id": "ops-user",
                            "tenant_id": None,
                            "governed_target": "backup-1",
                            "acquired_at_utc": "2026-03-15T00:00:00",
                        },
                    )(),
                ),
                "latest_reclaimed_lease": type(
                    "Reclaim",
                    (),
                    {
                        "operator_id": "ops-user",
                        "tenant_id": None,
                        "governed_target": "backup-1",
                        "acquired_at_utc": "2026-03-15T00:00:00Z",
                        "reclaimed_at_utc": "2026-03-15T01:00:00",
                        "reclaim_count": 1,
                    },
                )(),
                "recent_reclaimed_leases": (),
            },
        )(),
    )

    status = runtime_status_operator_action.build_operator_action_status(
        artifact_directory=Path("artifacts/durable-recovery-drill"),
        action_name="recovery_drill",
    )

    assert status.status == "active"
    assert status.latest_reclaimed_run_age_seconds is not None
    assert status.oldest_active_run_age_seconds is not None


def test_operator_action_status_fields_preserve_active_and_reclaim_evidence():
    reclaim = RecentOperatorActionReclaim(
        operator_id="ops-prior",
        tenant_id="tenant-a",
        governed_target="backup-1",
        acquired_at_utc="2026-05-31T09:00:00Z",
        reclaimed_at_utc="2026-05-31T09:30:00Z",
        reclaimed_age_seconds=60.0,
        reclaim_count=2,
    )
    status = OperatorActionStatus(
        status="active",
        reason=None,
        active_run_count=1,
        oldest_active_run_operator_id="ops-user",
        oldest_active_run_tenant_id="tenant-a",
        oldest_active_run_governed_target="backup-1",
        oldest_active_run_acquired_at_utc="2026-05-31T10:00:00Z",
        oldest_active_run_age_seconds=30.0,
        latest_reclaimed_run_operator_id="ops-prior",
        latest_reclaimed_run_tenant_id="tenant-a",
        latest_reclaimed_run_governed_target="backup-1",
        latest_reclaimed_run_acquired_at_utc="2026-05-31T09:00:00Z",
        latest_reclaimed_run_reclaimed_at_utc="2026-05-31T09:30:00Z",
        latest_reclaimed_run_age_seconds=60.0,
        reclaimed_run_count=2,
        recent_reclaimed_runs=(reclaim,),
    )

    fields = runtime_status_operator_action.operator_action_status_fields(status)

    assert fields["active_run_status"] == "active"
    assert fields["oldest_active_run_operator_id"] == "ops-user"
    assert fields["latest_reclaimed_run_operator_id"] == "ops-prior"
    assert fields["reclaimed_run_count"] == 2
    assert fields["recent_reclaimed_runs"] == (reclaim,)
