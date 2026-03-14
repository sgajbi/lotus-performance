from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.compute_job_store import ComputeQueueStats, compute_job_store
from app.services.durability_health_service import (
    DurabilityHealthStatus,
    check_durable_metadata_store_ready,
)
from app.services.lineage_metadata_store import LineageQueueStats, lineage_metadata_store


@dataclass(frozen=True)
class RuntimeQueueStatus:
    status: str
    reason: str | None
    stats: ComputeQueueStats | LineageQueueStats | None


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    generated_at: datetime
    runtime_status: str
    draining: bool
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeQueueStatus
    lineage_queue: RuntimeQueueStatus


def build_runtime_status_snapshot(*, is_draining: bool) -> RuntimeStatusSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()
    settings = get_settings()

    runtime_status = "draining" if is_draining else durability_status.status
    compute_queue = _build_compute_queue_status(durability_status, settings=settings)
    lineage_queue = _build_lineage_queue_status(durability_status, settings=settings)

    if runtime_status == "ready" and (compute_queue.status != "available" or lineage_queue.status != "available"):
        runtime_status = "degraded"

    return RuntimeStatusSnapshot(
        generated_at=generated_at,
        runtime_status=runtime_status,
        draining=is_draining,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
    )


def _build_compute_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            stats=None,
        )
    try:
        stats = compute_job_store.get_queue_stats()
        degrade_reason = _compute_queue_degrade_reason(stats, settings=settings)
        if degrade_reason is not None:
            return RuntimeQueueStatus(status="degraded", reason=degrade_reason, stats=stats)
        return RuntimeQueueStatus(status="available", reason=None, stats=stats)
    except Exception as exc:
        return RuntimeQueueStatus(status="unavailable", reason=type(exc).__name__, stats=None)


def _build_lineage_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            stats=None,
        )
    try:
        stats = lineage_metadata_store.get_pending_payload_stats()
        degrade_reason = _lineage_queue_degrade_reason(stats, settings=settings)
        if degrade_reason is not None:
            return RuntimeQueueStatus(status="degraded", reason=degrade_reason, stats=stats)
        return RuntimeQueueStatus(
            status="available",
            reason=None,
            stats=stats,
        )
    except Exception as exc:
        return RuntimeQueueStatus(status="unavailable", reason=type(exc).__name__, stats=None)


def _compute_queue_degrade_reason(stats: ComputeQueueStats, *, settings) -> str | None:
    if (
        settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT > 0
        and stats.retry_backlog_count >= settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT
    ):
        return "compute_retry_backlog_exceeded"
    if (
        settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT > 0
        and stats.terminal_failure_count >= settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT
    ):
        return "compute_terminal_failure_exceeded"
    if (
        settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT > 0
        and stats.lease_expired_count >= settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT
    ):
        return "compute_lease_expiry_pressure_exceeded"
    if (
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_pending_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS
    ):
        return "compute_pending_age_exceeded"
    if (
        settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_leased_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS
    ):
        return "compute_leased_age_exceeded"
    if (
        settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_running_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS
    ):
        return "compute_running_age_exceeded"
    return None


def _lineage_queue_degrade_reason(stats: LineageQueueStats, *, settings) -> str | None:
    if (
        settings.RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT > 0
        and stats.retry_backlog_count >= settings.RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT
    ):
        return "lineage_retry_backlog_exceeded"
    if (
        settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT > 0
        and stats.terminal_failure_count >= settings.RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT
    ):
        return "lineage_terminal_failure_exceeded"
    if (
        settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_pending_age_seconds >= settings.RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS
    ):
        return "lineage_pending_age_exceeded"
    return None
