from pathlib import Path

from app.services import runtime_status_operator_action
from app.services.runtime_status_domain import OperatorActionStatus, RecentOperatorActionReclaim


def test_runtime_status_operator_action_status_handles_exceptions_and_unavailable_snapshot(mocker):
    mocker.patch(
        "app.services.runtime_status_operator_action.build_operator_action_lease_snapshot",
        side_effect=RuntimeError("boom"),
    )
    unavailable = runtime_status_operator_action.build_operator_action_status(
        artifact_directory=Path("artifacts/runtime-retention-cleanup"),
        action_name="runtime_retention_cleanup",
    )
    assert unavailable.status == "unavailable"
    assert unavailable.reason == "RuntimeError"

    mocker.patch(
        "app.services.runtime_status_operator_action.build_operator_action_lease_snapshot",
        return_value=type(
            "LeaseSnapshot",
            (),
            {
                "status": "unavailable",
                "reason": "operator_action_lease_invalid",
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
    assert unavailable_snapshot.reason == "operator_action_lease_invalid"


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
