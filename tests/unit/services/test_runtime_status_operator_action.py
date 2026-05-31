from app.services import runtime_status_operator_action


def test_runtime_status_operator_action_status_handles_exceptions_and_unavailable_snapshot(mocker):
    mocker.patch(
        "app.services.runtime_status_operator_action.build_operator_action_lease_snapshot",
        side_effect=RuntimeError("boom"),
    )
    unavailable = runtime_status_operator_action.build_operator_action_status(
        artifact_directory="artifacts/runtime-retention-cleanup",
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
        artifact_directory="artifacts/runtime-retention-cleanup",
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
        artifact_directory="artifacts/durable-recovery-drill",
        action_name="recovery_drill",
    )

    assert status.status == "active"
    assert status.latest_reclaimed_run_age_seconds is not None
    assert status.oldest_active_run_age_seconds is not None
