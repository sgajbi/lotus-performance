from __future__ import annotations

from app.services.runtime_status_domain import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RecoveryDrillDegradationPolicy,
    RuntimeRetentionDegradationPolicy,
)


def build_compute_queue_policy(*, settings) -> ComputeQueueDegradationPolicy:
    return ComputeQueueDegradationPolicy(
        pending_age_seconds=settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
        leased_age_seconds=settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
        running_age_seconds=settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
        retry_backlog_count=settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
        lease_expiry_count=settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
        terminal_failure_count=settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )


def build_lineage_queue_policy(*, settings) -> LineageQueueDegradationPolicy:
    return LineageQueueDegradationPolicy(
        pending_age_seconds=getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
        leased_age_seconds=getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
        retry_backlog_count=getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
        terminal_failure_count=getattr(settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
        storage_min_free_bytes=getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0),
        storage_min_free_ratio=getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0),
    )


def build_recovery_drill_policy(*, settings) -> RecoveryDrillDegradationPolicy:
    return RecoveryDrillDegradationPolicy(
        max_age_seconds=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS", 0.0),
        active_run_age_seconds=getattr(
            settings,
            "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
            0.0,
        ),
        reclaim_count=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0),
    )


def build_runtime_retention_policy(*, settings) -> RuntimeRetentionDegradationPolicy:
    return RuntimeRetentionDegradationPolicy(
        max_age_seconds=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0),
        active_run_age_seconds=getattr(
            settings,
            "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
            0.0,
        ),
        reclaim_count=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0),
    )
