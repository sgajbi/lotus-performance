from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from prometheus_client.core import GaugeMetricFamily

from app.services.runtime_degradation_policy import threshold_breach_flag
from app.services.runtime_status_domain import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RecoveryDrillDegradationPolicy,
    RuntimeRetentionDegradationPolicy,
)
from app.services.runtime_status_time import age_seconds_since


@dataclass(frozen=True)
class OperatorActionMetricSpec:
    active_metric_name: str
    active_description: str
    oldest_active_age_metric_name: str
    oldest_active_age_description: str
    reclaimed_age_metric_name: str
    reclaimed_age_description: str
    reclaimed_count_metric_name: str
    reclaimed_count_description: str


RECOVERY_DRILL_ACTION_METRICS = OperatorActionMetricSpec(
    active_metric_name="lotus_performance_recovery_drill_active_actions",
    active_description="Number of active governed recovery-drill runs currently holding an in-flight lease.",
    oldest_active_age_metric_name="lotus_performance_recovery_drill_oldest_active_action_age_seconds",
    oldest_active_age_description="Age in seconds of the oldest active governed recovery-drill run.",
    reclaimed_age_metric_name="lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds",
    reclaimed_age_description="Age in seconds since the latest stale governed recovery-drill lease reclaim.",
    reclaimed_count_metric_name="lotus_performance_recovery_drill_reclaimed_actions",
    reclaimed_count_description=(
        "Count of stale governed recovery-drill leases reclaimed and retained in the current control-plane counter."
    ),
)

RUNTIME_RETENTION_ACTION_METRICS = OperatorActionMetricSpec(
    active_metric_name="lotus_performance_runtime_retention_active_actions",
    active_description="Number of active governed runtime-retention cleanups currently holding an in-flight lease.",
    oldest_active_age_metric_name="lotus_performance_runtime_retention_oldest_active_action_age_seconds",
    oldest_active_age_description="Age in seconds of the oldest active governed runtime-retention cleanup.",
    reclaimed_age_metric_name="lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds",
    reclaimed_age_description="Age in seconds since the latest stale governed runtime-retention lease reclaim.",
    reclaimed_count_metric_name="lotus_performance_runtime_retention_reclaimed_actions",
    reclaimed_count_description=(
        "Count of stale governed runtime-retention leases reclaimed and retained in the current control-plane counter."
    ),
)


def operator_action_lease_metrics(
    *,
    snapshot: Any,
    spec: OperatorActionMetricSpec,
) -> tuple[GaugeMetricFamily, ...]:
    if snapshot is None or snapshot.status != "available":
        return ()

    metrics: list[GaugeMetricFamily] = []
    active_actions = GaugeMetricFamily(spec.active_metric_name, spec.active_description)
    active_actions.add_metric([], len(snapshot.active_leases))
    metrics.append(active_actions)

    if snapshot.active_leases:
        oldest_active_action_age = GaugeMetricFamily(
            spec.oldest_active_age_metric_name,
            spec.oldest_active_age_description,
        )
        oldest_active_action_age.add_metric([], age_seconds_since(snapshot.active_leases[0].acquired_at_utc))
        metrics.append(oldest_active_action_age)

    if snapshot.latest_reclaimed_lease is not None:
        latest_reclaimed_action_age = GaugeMetricFamily(
            spec.reclaimed_age_metric_name,
            spec.reclaimed_age_description,
        )
        latest_reclaimed_action_age.add_metric(
            [],
            age_seconds_since(snapshot.latest_reclaimed_lease.reclaimed_at_utc),
        )
        metrics.append(latest_reclaimed_action_age)

        reclaimed_actions = GaugeMetricFamily(spec.reclaimed_count_metric_name, spec.reclaimed_count_description)
        reclaimed_actions.add_metric([], snapshot.latest_reclaimed_lease.reclaim_count)
        metrics.append(reclaimed_actions)

    return tuple(metrics)


def policy_threshold_metric(
    *,
    metric_name: str,
    description: str,
    max_age_seconds: float,
    active_run_age_seconds: float,
    reclaim_count: int,
) -> GaugeMetricFamily:
    metric = GaugeMetricFamily(metric_name, description, labels=["threshold"])
    metric.add_metric(["max_age_seconds"], max_age_seconds)
    metric.add_metric(["active_run_age_seconds"], active_run_age_seconds)
    metric.add_metric(["reclaim_count"], reclaim_count)
    return metric


def compute_queue_degradation_breach_metric(
    *,
    stats: Any,
    policy: ComputeQueueDegradationPolicy,
) -> GaugeMetricFamily:
    return reason_labeled_metric(
        metric_name="lotus_performance_compute_queue_degradation_breach",
        description="Whether the compute queue currently breaches a configured runtime degradation threshold.",
        samples=(
            (
                "compute_retry_backlog_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.retry_backlog_count,
                    observed_value=stats.retry_backlog_count,
                ),
            ),
            (
                "compute_terminal_failure_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.terminal_failure_count,
                    observed_value=stats.terminal_failure_count,
                ),
            ),
            (
                "compute_lease_expiry_pressure_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.lease_expiry_count,
                    observed_value=stats.lease_expired_count,
                ),
            ),
            (
                "compute_pending_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.pending_age_seconds,
                    observed_value=stats.oldest_pending_age_seconds,
                ),
            ),
            (
                "compute_leased_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.leased_age_seconds,
                    observed_value=stats.oldest_leased_age_seconds,
                ),
            ),
            (
                "compute_running_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.running_age_seconds,
                    observed_value=stats.oldest_running_age_seconds,
                ),
            ),
        ),
    )


def lineage_queue_degradation_breach_metric(
    *,
    stats: Any,
    policy: LineageQueueDegradationPolicy,
) -> GaugeMetricFamily:
    return reason_labeled_metric(
        metric_name="lotus_performance_lineage_queue_degradation_breach",
        description="Whether the lineage queue currently breaches a configured runtime degradation threshold.",
        samples=(
            (
                "lineage_retry_backlog_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.retry_backlog_count,
                    observed_value=stats.retry_backlog_count,
                ),
            ),
            (
                "lineage_terminal_failure_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.terminal_failure_count,
                    observed_value=stats.terminal_failure_count,
                ),
            ),
            (
                "lineage_pending_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.pending_age_seconds,
                    observed_value=stats.oldest_pending_age_seconds,
                ),
            ),
            (
                "lineage_leased_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.leased_age_seconds,
                    observed_value=getattr(stats, "oldest_leased_age_seconds", 0.0),
                ),
            ),
        ),
    )


def lineage_storage_pressure_breach_metric(
    *,
    capacity: Any,
    policy: LineageQueueDegradationPolicy,
) -> GaugeMetricFamily:
    return reason_labeled_metric(
        metric_name="lotus_performance_lineage_storage_pressure_breach",
        description="Whether lineage storage currently breaches a proactive saturation threshold.",
        samples=(
            (
                "lineage_storage_free_bytes_below_threshold",
                threshold_breach_flag(
                    observed_value=capacity.free_bytes,
                    threshold_value=policy.storage_min_free_bytes,
                    comparison="at_or_below",
                ),
            ),
            (
                "lineage_storage_free_ratio_below_threshold",
                threshold_breach_flag(
                    observed_value=capacity.free_ratio,
                    threshold_value=policy.storage_min_free_ratio,
                    comparison="at_or_below",
                ),
            ),
        ),
    )


def recovery_drill_degradation_breach_metric(
    *,
    latest: Any,
    latest_age_seconds: float,
    action_snapshot: Any,
    policy: RecoveryDrillDegradationPolicy,
) -> GaugeMetricFamily:
    return reason_labeled_metric(
        metric_name="lotus_performance_recovery_drill_degradation_breach",
        description="Whether retained durable recovery-drill history currently breaches a recovery assurance policy.",
        samples=(
            ("recovery_drill_latest_not_passed", 1 if latest.status != "passed" else 0),
            (
                "recovery_drill_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.max_age_seconds,
                    observed_value=latest_age_seconds,
                ),
            ),
            (
                "recovery_drill_active_run_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.active_run_age_seconds,
                    observed_value=active_lease_age_seconds_or_zero(action_snapshot),
                ),
            ),
            (
                "recovery_drill_reclaim_pressure_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.reclaim_count,
                    observed_value=latest_reclaim_count_or_zero(action_snapshot),
                ),
            ),
        ),
    )


def runtime_retention_degradation_breach_metric(
    *,
    latest: Any,
    latest_age_seconds: float,
    action_snapshot: Any,
    policy: RuntimeRetentionDegradationPolicy,
) -> GaugeMetricFamily:
    return reason_labeled_metric(
        metric_name="lotus_performance_runtime_retention_degradation_breach",
        description="Whether retained runtime-retention cleanup history currently breaches a lifecycle-governance policy.",
        samples=(
            ("runtime_retention_latest_not_applied", 1 if latest.cleanup_mode != "apply" else 0),
            (
                "runtime_retention_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.max_age_seconds,
                    observed_value=latest_age_seconds,
                ),
            ),
            (
                "runtime_retention_active_run_age_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.active_run_age_seconds,
                    observed_value=active_lease_age_seconds_or_zero(action_snapshot),
                ),
            ),
            (
                "runtime_retention_reclaim_pressure_exceeded",
                threshold_breach_flag(
                    threshold_value=policy.reclaim_count,
                    observed_value=latest_reclaim_count_or_zero(action_snapshot),
                ),
            ),
        ),
    )


def recovery_drill_latest_age_metric(*, latest_age_seconds: float) -> GaugeMetricFamily:
    return single_sample_metric(
        metric_name="lotus_performance_recovery_drill_latest_age_seconds",
        description="Age in seconds of the latest retained durable recovery drill.",
        value=latest_age_seconds,
    )


def runtime_retention_latest_age_metric(*, latest_age_seconds: float) -> GaugeMetricFamily:
    return single_sample_metric(
        metric_name="lotus_performance_runtime_retention_latest_age_seconds",
        description="Age in seconds of the latest retained runtime-retention cleanup.",
        value=latest_age_seconds,
    )


def labeled_metric(
    *,
    metric_name: str,
    description: str,
    label_name: str,
    samples: Iterable[tuple[str, float]],
) -> GaugeMetricFamily:
    metric = GaugeMetricFamily(metric_name, description, labels=[label_name])
    for label_value, value in samples:
        metric.add_metric([label_value], value)
    return metric


def reason_labeled_metric(
    *,
    metric_name: str,
    description: str,
    samples: Iterable[tuple[str, float]],
) -> GaugeMetricFamily:
    return labeled_metric(
        metric_name=metric_name,
        description=description,
        label_name="reason",
        samples=samples,
    )


def active_lease_age_seconds_or_zero(snapshot: Any) -> float:
    if not snapshot_available(snapshot) or not snapshot.active_leases:
        return 0.0
    return age_seconds_since(snapshot.active_leases[0].acquired_at_utc)


def latest_reclaim_count_or_zero(snapshot: Any) -> int:
    if not snapshot_available(snapshot) or snapshot.latest_reclaimed_lease is None:
        return 0
    return snapshot.latest_reclaimed_lease.reclaim_count


def single_sample_metric(*, metric_name: str, description: str, value: Any) -> GaugeMetricFamily:
    metric = GaugeMetricFamily(metric_name, description)
    metric.add_metric([], value)
    return metric


def availability_metric(*, metric_name: str, description: str, is_available: bool) -> GaugeMetricFamily:
    return single_sample_metric(
        metric_name=metric_name,
        description=description,
        value=1 if is_available else 0,
    )


def snapshot_available(snapshot: Any) -> bool:
    return snapshot is not None and snapshot.status == "available"
