from __future__ import annotations

from decimal import Decimal

from app.services.compute_job_store import ComputeQueueStats
from app.services.durability_health_service import LineageStorageCapacitySnapshot
from app.services.lineage_metadata_store import LineageQueueStats
from app.services.runtime_degradation_policy import (
    ThresholdComparison,
    as_decimal_number,
    threshold_breach_values,
)
from app.services.runtime_status_domain import (
    OperatorActionStatus,
    RecoveryDrillStatus,
    RuntimeDegradationDetail,
    RuntimeQueueStatus,
    RuntimeRetentionStatus,
)


def compute_queue_degradation_details(stats: ComputeQueueStats, *, settings) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    append_degradation_detail_if_breached(
        details,
        reason="compute_retry_backlog_exceeded",
        observed_value=stats.retry_backlog_count,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
    )
    append_degradation_detail_if_breached(
        details,
        reason="compute_terminal_failure_exceeded",
        observed_value=stats.terminal_failure_count,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )
    append_degradation_detail_if_breached(
        details,
        reason="compute_lease_expiry_pressure_exceeded",
        observed_value=stats.lease_expired_count,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
    )
    append_degradation_detail_if_breached(
        details,
        reason="compute_pending_age_exceeded",
        observed_value=stats.oldest_pending_age_seconds,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
    )
    append_degradation_detail_if_breached(
        details,
        reason="compute_leased_age_exceeded",
        observed_value=stats.oldest_leased_age_seconds,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
    )
    append_degradation_detail_if_breached(
        details,
        reason="compute_running_age_exceeded",
        observed_value=stats.oldest_running_age_seconds,
        threshold_value=settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
    )
    return tuple(details)


def lineage_queue_degradation_details(
    stats: LineageQueueStats,
    *,
    storage_capacity: LineageStorageCapacitySnapshot,
    settings,
) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    lineage_leased_age_degrade_seconds = getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0)
    lineage_retry_backlog_degrade_count = getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0)
    lineage_terminal_failure_degrade_count = getattr(
        settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0
    )
    lineage_pending_age_degrade_seconds = getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0)
    append_degradation_detail_if_breached(
        details,
        reason="lineage_leased_age_exceeded",
        observed_value=stats.oldest_leased_age_seconds,
        threshold_value=lineage_leased_age_degrade_seconds,
    )
    append_degradation_detail_if_breached(
        details,
        reason="lineage_retry_backlog_exceeded",
        observed_value=stats.retry_backlog_count,
        threshold_value=lineage_retry_backlog_degrade_count,
    )
    append_degradation_detail_if_breached(
        details,
        reason="lineage_terminal_failure_exceeded",
        observed_value=stats.terminal_failure_count,
        threshold_value=lineage_terminal_failure_degrade_count,
    )
    append_degradation_detail_if_breached(
        details,
        reason="lineage_pending_age_exceeded",
        observed_value=stats.oldest_pending_age_seconds,
        threshold_value=lineage_pending_age_degrade_seconds,
    )
    lineage_storage_min_free_bytes = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0)
    lineage_storage_min_free_ratio = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0)
    append_degradation_detail_if_breached(
        details,
        reason="lineage_storage_free_bytes_below_threshold",
        observed_value=storage_capacity.free_bytes,
        threshold_value=lineage_storage_min_free_bytes,
        comparison="at_or_below",
    )
    append_degradation_detail_if_breached(
        details,
        reason="lineage_storage_free_ratio_below_threshold",
        observed_value=storage_capacity.free_ratio,
        threshold_value=lineage_storage_min_free_ratio,
        comparison="at_or_below",
    )
    return tuple(details)


def append_degradation_detail_if_breached(
    details: list[RuntimeDegradationDetail],
    *,
    reason: str,
    observed_value: object,
    threshold_value: object,
    comparison: ThresholdComparison = "at_or_above",
) -> None:
    breached_values = threshold_breach_values(
        observed_value=observed_value,
        threshold_value=threshold_value,
        comparison=comparison,
    )
    if breached_values is None:
        return
    observed_decimal, threshold_decimal = breached_values
    details.append(
        RuntimeDegradationDetail(
            reason=reason,
            observed_value=observed_decimal,
            threshold_value=threshold_decimal,
        )
    )


def append_operator_action_degradation_details(
    details: list[RuntimeDegradationDetail],
    *,
    active_run_status: OperatorActionStatus,
    active_run_age_threshold: float,
    active_run_reason: str,
    reclaim_threshold: int,
    reclaim_reason: str,
) -> None:
    if active_run_status.status == "active" and active_run_status.oldest_active_run_age_seconds is not None:
        append_degradation_detail_if_breached(
            details,
            reason=active_run_reason,
            observed_value=active_run_status.oldest_active_run_age_seconds,
            threshold_value=active_run_age_threshold,
        )
    append_degradation_detail_if_breached(
        details,
        reason=reclaim_reason,
        observed_value=active_run_status.reclaimed_run_count,
        threshold_value=reclaim_threshold,
    )


def append_latest_history_age_degradation_detail(
    details: list[RuntimeDegradationDetail],
    *,
    reason: str,
    latest_age_seconds: float,
    threshold: float,
) -> None:
    append_degradation_detail_if_breached(
        details,
        reason=reason,
        observed_value=latest_age_seconds,
        threshold_value=threshold,
    )


def append_lifecycle_state_degradation_detail(
    details: list[RuntimeDegradationDetail],
    *,
    is_healthy: bool,
    reason: str,
) -> None:
    if is_healthy:
        return
    details.append(
        RuntimeDegradationDetail(
            reason=reason,
            observed_value=as_decimal_number(0),
            threshold_value=as_decimal_number(0),
        )
    )


def decimal_number(value: object) -> Decimal:
    return as_decimal_number(value)


def missing_history_degradation(
    *,
    threshold: float,
    reason: str,
) -> tuple[tuple[str, ...], tuple[RuntimeDegradationDetail, ...]]:
    if threshold <= 0:
        return (), ()
    return (
        (reason,),
        (
            RuntimeDegradationDetail(
                reason=reason,
                observed_value=as_decimal_number(0),
                threshold_value=as_decimal_number(threshold),
            ),
        ),
    )


def lifecycle_status_from_degradation_details(
    degradation_details: tuple[RuntimeDegradationDetail, ...],
) -> tuple[str, str | None, tuple[str, ...]]:
    reasons = tuple(detail.reason for detail in degradation_details)
    return (
        "degraded" if reasons else "available",
        reasons[0] if reasons else None,
        reasons,
    )


def runtime_status_from_component_statuses(
    *,
    is_draining: bool,
    durable_metadata_status: str,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
    recovery_drill: RecoveryDrillStatus,
    runtime_retention: RuntimeRetentionStatus,
) -> str:
    if is_draining:
        return "draining"
    if durable_metadata_status != "ready":
        return durable_metadata_status
    if (
        compute_queue.status != "available"
        or lineage_queue.status != "available"
        or recovery_drill.status != "available"
        or runtime_retention.status != "available"
    ):
        return "degraded"
    return "ready"


def collect_runtime_degradation_reasons(
    *,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
    recovery_drill: RecoveryDrillStatus,
    runtime_retention: RuntimeRetentionStatus,
) -> tuple[str, ...]:
    reasons: list[str] = []

    for prefix, queue_status in (
        ("compute_queue", compute_queue),
        ("lineage_queue", lineage_queue),
    ):
        if queue_status.status == "degraded":
            reasons.extend(f"{prefix}:{reason}" for reason in queue_status.degradation_reasons)
        elif queue_status.status == "unavailable" and queue_status.reason is not None:
            reasons.append(f"{prefix}:{queue_status.reason}")

    if recovery_drill.status == "degraded":
        reasons.extend(f"recovery_drill:{reason}" for reason in recovery_drill.degradation_reasons)
    elif recovery_drill.status == "unavailable" and recovery_drill.reason is not None:
        reasons.append(f"recovery_drill:{recovery_drill.reason}")

    if runtime_retention.status == "degraded":
        reasons.extend(f"runtime_retention:{reason}" for reason in runtime_retention.degradation_reasons)
    elif runtime_retention.status == "unavailable" and runtime_retention.reason is not None:
        reasons.append(f"runtime_retention:{runtime_retention.reason}")

    return tuple(reasons)


def collect_runtime_degradation_details(
    *,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
    recovery_drill: RecoveryDrillStatus,
    runtime_retention: RuntimeRetentionStatus,
) -> tuple[RuntimeDegradationDetail, ...]:
    return (
        compute_queue.degradation_details
        + lineage_queue.degradation_details
        + recovery_drill.degradation_details
        + runtime_retention.degradation_details
    )
