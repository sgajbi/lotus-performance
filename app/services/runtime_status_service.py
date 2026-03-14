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
    degradation_reasons: tuple[str, ...]
    degradation_details: tuple["RuntimeDegradationDetail", ...]
    stats: ComputeQueueStats | LineageQueueStats | None


@dataclass(frozen=True)
class RuntimeDegradationDetail:
    reason: str
    observed_value: float
    threshold_value: float


@dataclass(frozen=True)
class ComputeQueueDegradationPolicy:
    pending_age_seconds: float
    leased_age_seconds: float
    running_age_seconds: float
    retry_backlog_count: int
    lease_expiry_count: int
    terminal_failure_count: int


@dataclass(frozen=True)
class LineageQueueDegradationPolicy:
    pending_age_seconds: float
    leased_age_seconds: float
    retry_backlog_count: int
    terminal_failure_count: int


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    generated_at: datetime
    runtime_status: str
    runtime_degradation_reasons: tuple[str, ...]
    runtime_degradation_details: tuple[RuntimeDegradationDetail, ...]
    draining: bool
    durable_metadata_store: DurabilityHealthStatus
    compute_queue: RuntimeQueueStatus
    lineage_queue: RuntimeQueueStatus
    compute_queue_policy: ComputeQueueDegradationPolicy
    lineage_queue_policy: LineageQueueDegradationPolicy


def build_runtime_status_snapshot(*, is_draining: bool) -> RuntimeStatusSnapshot:
    generated_at = datetime.now(UTC)
    durability_status = check_durable_metadata_store_ready()
    settings = get_settings()
    compute_queue_policy = _build_compute_queue_policy(settings=settings)
    lineage_queue_policy = _build_lineage_queue_policy(settings=settings)

    runtime_status = "draining" if is_draining else durability_status.status
    compute_queue = _build_compute_queue_status(durability_status, settings=settings)
    lineage_queue = _build_lineage_queue_status(durability_status, settings=settings)
    runtime_degradation_reasons = _collect_runtime_degradation_reasons(
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
    )
    runtime_degradation_details = _collect_runtime_degradation_details(
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
    )

    if runtime_status == "ready" and (compute_queue.status != "available" or lineage_queue.status != "available"):
        runtime_status = "degraded"

    return RuntimeStatusSnapshot(
        generated_at=generated_at,
        runtime_status=runtime_status,
        runtime_degradation_reasons=runtime_degradation_reasons,
        runtime_degradation_details=runtime_degradation_details,
        draining=is_draining,
        durable_metadata_store=durability_status,
        compute_queue=compute_queue,
        lineage_queue=lineage_queue,
        compute_queue_policy=compute_queue_policy,
        lineage_queue_policy=lineage_queue_policy,
    )


def _build_compute_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
        )
    try:
        stats = compute_job_store.get_queue_stats()
        degradation_details = _compute_queue_degradation_details(stats, settings=settings)
        degradation_reasons = tuple(detail.reason for detail in degradation_details)
        if degradation_reasons:
            return RuntimeQueueStatus(
                status="degraded",
                reason=degradation_reasons[0],
                degradation_reasons=degradation_reasons,
                degradation_details=degradation_details,
                stats=stats,
            )
        return RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=stats,
        )
    except Exception as exc:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=type(exc).__name__,
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
        )


def _build_lineage_queue_status(durability_status: DurabilityHealthStatus, *, settings) -> RuntimeQueueStatus:
    if not durability_status.is_ready:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=durability_status.reason or "durable_metadata_store_unreachable",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
        )
    try:
        stats = lineage_metadata_store.get_pending_payload_stats()
        degradation_details = _lineage_queue_degradation_details(stats, settings=settings)
        degradation_reasons = tuple(detail.reason for detail in degradation_details)
        if degradation_reasons:
            return RuntimeQueueStatus(
                status="degraded",
                reason=degradation_reasons[0],
                degradation_reasons=degradation_reasons,
                degradation_details=degradation_details,
                stats=stats,
            )
        return RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=stats,
        )
    except Exception as exc:
        return RuntimeQueueStatus(
            status="unavailable",
            reason=type(exc).__name__,
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
        )


def _compute_queue_degradation_details(
    stats: ComputeQueueStats, *, settings
) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    if (
        settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT > 0
        and stats.retry_backlog_count >= settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_retry_backlog_exceeded",
                observed_value=float(stats.retry_backlog_count),
                threshold_value=float(settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT > 0
        and stats.terminal_failure_count >= settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_terminal_failure_exceeded",
                observed_value=float(stats.terminal_failure_count),
                threshold_value=float(settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT > 0
        and stats.lease_expired_count >= settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_lease_expiry_pressure_exceeded",
                observed_value=float(stats.lease_expired_count),
                threshold_value=float(settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT),
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_pending_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_pending_age_exceeded",
                observed_value=stats.oldest_pending_age_seconds,
                threshold_value=settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_leased_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_leased_age_exceeded",
                observed_value=stats.oldest_leased_age_seconds,
                threshold_value=settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
            )
        )
    if (
        settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS > 0
        and stats.oldest_running_age_seconds >= settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="compute_running_age_exceeded",
                observed_value=stats.oldest_running_age_seconds,
                threshold_value=settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
            )
        )
    return tuple(details)


def _lineage_queue_degradation_details(
    stats: LineageQueueStats, *, settings
) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    lineage_leased_age_degrade_seconds = getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0)
    lineage_retry_backlog_degrade_count = getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0)
    lineage_terminal_failure_degrade_count = getattr(settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0)
    lineage_pending_age_degrade_seconds = getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0)
    if (
        lineage_leased_age_degrade_seconds > 0
        and stats.oldest_leased_age_seconds >= lineage_leased_age_degrade_seconds
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_leased_age_exceeded",
                observed_value=stats.oldest_leased_age_seconds,
                threshold_value=lineage_leased_age_degrade_seconds,
            )
        )
    if (
        lineage_retry_backlog_degrade_count > 0
        and stats.retry_backlog_count >= lineage_retry_backlog_degrade_count
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_retry_backlog_exceeded",
                observed_value=float(stats.retry_backlog_count),
                threshold_value=float(lineage_retry_backlog_degrade_count),
            )
        )
    if (
        lineage_terminal_failure_degrade_count > 0
        and stats.terminal_failure_count >= lineage_terminal_failure_degrade_count
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_terminal_failure_exceeded",
                observed_value=float(stats.terminal_failure_count),
                threshold_value=float(lineage_terminal_failure_degrade_count),
            )
        )
    if (
        lineage_pending_age_degrade_seconds > 0
        and stats.oldest_pending_age_seconds >= lineage_pending_age_degrade_seconds
    ):
        details.append(
            RuntimeDegradationDetail(
                reason="lineage_pending_age_exceeded",
                observed_value=stats.oldest_pending_age_seconds,
                threshold_value=lineage_pending_age_degrade_seconds,
            )
        )
    return tuple(details)


def _collect_runtime_degradation_reasons(
    *,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
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

    return tuple(reasons)


def _collect_runtime_degradation_details(
    *,
    compute_queue: RuntimeQueueStatus,
    lineage_queue: RuntimeQueueStatus,
) -> tuple[RuntimeDegradationDetail, ...]:
    return compute_queue.degradation_details + lineage_queue.degradation_details


def _build_compute_queue_policy(*, settings) -> ComputeQueueDegradationPolicy:
    return ComputeQueueDegradationPolicy(
        pending_age_seconds=settings.RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS,
        leased_age_seconds=settings.RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS,
        running_age_seconds=settings.RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS,
        retry_backlog_count=settings.RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT,
        lease_expiry_count=settings.RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT,
        terminal_failure_count=settings.RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT,
    )


def _build_lineage_queue_policy(*, settings) -> LineageQueueDegradationPolicy:
    return LineageQueueDegradationPolicy(
        pending_age_seconds=getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
        leased_age_seconds=getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
        retry_backlog_count=getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
        terminal_failure_count=getattr(settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
    )
