from app.services.runtime_status_policy import (
    build_compute_queue_policy,
    build_lineage_queue_policy,
    build_recovery_drill_policy,
    build_runtime_retention_policy,
)


def test_runtime_status_policy_builders_map_configured_thresholds():
    settings = type(
        "Settings",
        (),
        {
            "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 10.0,
            "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 20.0,
            "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 30.0,
            "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 4,
            "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 5,
            "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 6,
            "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 40.0,
            "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 50.0,
            "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 7,
            "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 8,
            "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 900,
            "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.25,
            "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 60.0,
            "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 70.0,
            "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 9,
            "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 80.0,
            "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 90.0,
            "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 10,
        },
    )()

    compute_policy = build_compute_queue_policy(settings=settings)
    lineage_policy = build_lineage_queue_policy(settings=settings)
    recovery_policy = build_recovery_drill_policy(settings=settings)
    retention_policy = build_runtime_retention_policy(settings=settings)

    assert compute_policy.pending_age_seconds == 10.0
    assert compute_policy.leased_age_seconds == 20.0
    assert compute_policy.running_age_seconds == 30.0
    assert compute_policy.retry_backlog_count == 4
    assert compute_policy.lease_expiry_count == 5
    assert compute_policy.terminal_failure_count == 6
    assert lineage_policy.pending_age_seconds == 40.0
    assert lineage_policy.leased_age_seconds == 50.0
    assert lineage_policy.retry_backlog_count == 7
    assert lineage_policy.terminal_failure_count == 8
    assert lineage_policy.storage_min_free_bytes == 900
    assert lineage_policy.storage_min_free_ratio == 0.25
    assert recovery_policy.max_age_seconds == 60.0
    assert recovery_policy.active_run_age_seconds == 70.0
    assert recovery_policy.reclaim_count == 9
    assert retention_policy.max_age_seconds == 80.0
    assert retention_policy.active_run_age_seconds == 90.0
    assert retention_policy.reclaim_count == 10


def test_runtime_status_lifecycle_policy_builders_default_missing_optional_thresholds():
    settings = type("Settings", (), {})()

    lineage_policy = build_lineage_queue_policy(settings=settings)
    recovery_policy = build_recovery_drill_policy(settings=settings)
    retention_policy = build_runtime_retention_policy(settings=settings)

    assert lineage_policy.pending_age_seconds == 0.0
    assert lineage_policy.storage_min_free_bytes == 0
    assert recovery_policy.max_age_seconds == 0.0
    assert recovery_policy.reclaim_count == 0
    assert retention_policy.max_age_seconds == 0.0
    assert retention_policy.reclaim_count == 0
