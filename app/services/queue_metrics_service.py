from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from prometheus_client.core import GaugeMetricFamily

from app.core.config import get_settings
from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import get_lineage_storage_capacity
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.operator_action_lease_service import build_operator_action_lease_snapshot
from app.services.queue_metric_builders import (
    RECOVERY_DRILL_ACTION_METRICS,
    RUNTIME_RETENTION_ACTION_METRICS,
    OperatorActionMetricSpec,
    availability_metric,
    compute_queue_degradation_breach_metric,
    compute_queue_failure_pressure_metric,
    compute_queue_job_count_metric,
    compute_queue_oldest_age_metrics,
    durable_queue_store_availability_metric,
    lineage_queue_degradation_breach_metric,
    lineage_queue_payload_metrics,
    lineage_storage_capacity_metrics,
    lineage_storage_pressure_breach_metric,
    lineage_storage_pressure_threshold_metric,
    operator_action_lease_metrics,
    policy_threshold_metric,
    recovery_drill_degradation_breach_metric,
    recovery_drill_latest_age_metric,
    runtime_retention_degradation_breach_metric,
    runtime_retention_latest_age_metric,
    runtime_retention_prunable_items_metric,
    snapshot_available,
)
from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot
from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot
from app.services.runtime_retention_service import run_runtime_retention_cleanup
from app.services.runtime_status_policy import (
    build_compute_queue_policy,
    build_lineage_queue_policy,
    build_recovery_drill_policy,
    build_runtime_retention_policy,
)
from app.services.runtime_status_time import age_seconds_since

TMetricSource = TypeVar("TMetricSource")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DurableQueueMetricSources:
    compute_stats: Any | None
    compute_available: bool
    lineage_stats: Any | None
    lineage_available: bool
    lineage_storage_capacity: Any | None
    lineage_storage_capacity_available: bool
    recovery_drill_snapshot: Any | None
    recovery_drill_available: bool
    recovery_drill_action_snapshot: Any | None
    runtime_retention_snapshot: Any | None
    runtime_retention_available: bool
    runtime_retention_action_snapshot: Any | None
    runtime_retention_preview: Any | None
    runtime_retention_preview_available: bool


@dataclass(frozen=True)
class _DurableQueueMetricDescriptor:
    name: str
    description: str
    labels: tuple[str, ...] = ()

    def build(self) -> GaugeMetricFamily:
        if self.labels:
            return GaugeMetricFamily(self.name, self.description, labels=list(self.labels))
        return GaugeMetricFamily(self.name, self.description)


@dataclass(frozen=True)
class _LifecycleHistoryMetricSpec:
    policy_metric_name: str
    policy_metric_description: str
    action_metric_spec: OperatorActionMetricSpec
    latest_age_metric: Callable[..., GaugeMetricFamily]
    degradation_breach_metric: Callable[..., GaugeMetricFamily]


_DURABLE_QUEUE_METRIC_DESCRIPTORS = (
    _DurableQueueMetricDescriptor(
        "lotus_performance_durable_queue_store_availability",
        "Availability of durable queue metric sources by store.",
        ("store",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_compute_queue_jobs",
        "Durable compute job counts by status.",
        ("status",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_compute_queue_failure_pressure_jobs",
        "Durable compute job counts for retry backlog and failure-pressure categories.",
        ("category",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_compute_queue_oldest_pending_age_seconds",
        "Age in seconds of the oldest pending compute job.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_compute_queue_oldest_leased_age_seconds",
        "Age in seconds of the oldest leased compute job.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_compute_queue_oldest_running_age_seconds",
        "Age in seconds of the oldest running compute job.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_compute_queue_degradation_breach",
        "Whether the compute queue currently breaches a configured runtime degradation threshold.",
        ("reason",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_queue_pending_payloads",
        "Number of pending lineage payloads awaiting materialization.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_queue_failure_pressure_payloads",
        "Lineage payload counts for retry backlog and terminal failure categories.",
        ("category",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_queue_oldest_pending_age_seconds",
        "Age in seconds of the oldest pending lineage payload.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_queue_degradation_breach",
        "Whether the lineage queue currently breaches a configured runtime degradation threshold.",
        ("reason",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_storage_capacity_availability",
        "Availability of lineage storage capacity metrics.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_storage_capacity_bytes",
        "Lineage storage capacity by segment.",
        ("segment",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_storage_free_ratio",
        "Fraction of free lineage storage capacity currently remaining.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_storage_pressure_threshold",
        "Configured proactive lineage storage pressure thresholds.",
        ("threshold",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_lineage_storage_pressure_breach",
        "Whether lineage storage currently breaches a proactive saturation threshold.",
        ("reason",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_availability",
        "Availability of retained durable recovery-drill history.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_action_availability",
        "Availability of governed in-flight recovery-drill action lease visibility.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_active_actions",
        "Number of active governed recovery-drill runs currently holding an in-flight lease.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_oldest_active_action_age_seconds",
        "Age in seconds of the oldest active governed recovery-drill run.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds",
        "Age in seconds since the latest stale governed recovery-drill lease reclaim.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_reclaimed_actions",
        "Count of stale governed recovery-drill leases reclaimed and retained in the current control-plane counter.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_latest_age_seconds",
        "Age in seconds of the latest retained durable recovery drill.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_policy_threshold",
        "Configured recovery-drill degradation thresholds.",
        ("threshold",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_recovery_drill_degradation_breach",
        "Whether retained durable recovery-drill history currently breaches a recovery assurance policy.",
        ("reason",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_availability",
        "Availability of retained runtime-retention cleanup history.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_action_availability",
        "Availability of governed in-flight runtime-retention cleanup lease visibility.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_active_actions",
        "Number of active governed runtime-retention cleanups currently holding an in-flight lease.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_oldest_active_action_age_seconds",
        "Age in seconds of the oldest active governed runtime-retention cleanup.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds",
        "Age in seconds since the latest stale governed runtime-retention lease reclaim.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_reclaimed_actions",
        "Count of stale governed runtime-retention leases reclaimed and retained in the current control-plane counter.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_latest_age_seconds",
        "Age in seconds of the latest retained runtime-retention cleanup.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_policy_threshold",
        "Configured runtime-retention degradation thresholds.",
        ("threshold",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_degradation_breach",
        "Whether retained runtime-retention cleanup history currently breaches a lifecycle-governance policy.",
        ("reason",),
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_preview_availability",
        "Availability of the live runtime-retention preview under the current policy.",
    ),
    _DurableQueueMetricDescriptor(
        "lotus_performance_runtime_retention_prunable_items",
        "Current runtime-retention items that would be pruned by a dry-run cleanup.",
        ("category",),
    ),
)

_RECOVERY_DRILL_LIFECYCLE_METRICS = _LifecycleHistoryMetricSpec(
    policy_metric_name="lotus_performance_recovery_drill_policy_threshold",
    policy_metric_description="Configured recovery-drill degradation thresholds.",
    action_metric_spec=RECOVERY_DRILL_ACTION_METRICS,
    latest_age_metric=recovery_drill_latest_age_metric,
    degradation_breach_metric=recovery_drill_degradation_breach_metric,
)

_RUNTIME_RETENTION_LIFECYCLE_METRICS = _LifecycleHistoryMetricSpec(
    policy_metric_name="lotus_performance_runtime_retention_policy_threshold",
    policy_metric_description="Configured runtime-retention degradation thresholds.",
    action_metric_spec=RUNTIME_RETENTION_ACTION_METRICS,
    latest_age_metric=runtime_retention_latest_age_metric,
    degradation_breach_metric=runtime_retention_degradation_breach_metric,
)


def _load_metric_source(
    loader: Callable[[], TMetricSource],
    *,
    source_name: str = "unlabeled source",
) -> tuple[TMetricSource | None, bool]:
    try:
        return loader(), True
    except Exception:
        logger.warning("Queue metric source load failed for %s.", source_name, exc_info=True)
        return None, False


def _load_durable_queue_metric_sources(settings) -> _DurableQueueMetricSources:
    compute_stats, compute_available = _load_metric_source(
        compute_job_store.get_queue_stats,
        source_name="compute queue stats",
    )
    lineage_stats, lineage_available = _load_metric_source(
        lineage_metadata_store.get_pending_payload_stats,
        source_name="lineage queue payload stats",
    )
    lineage_storage_capacity, lineage_storage_capacity_available = _load_metric_source(
        get_lineage_storage_capacity,
        source_name="lineage storage capacity",
    )
    recovery_drill_snapshot, recovery_drill_available = _load_metric_source(
        lambda: build_recovery_drill_history_snapshot(limit=1),
        source_name="recovery drill history snapshot",
    )
    recovery_drill_action_snapshot = _load_operator_action_lease_metric_source(
        settings,
        artifact_path_attribute="RECOVERY_DRILL_ARTIFACT_PATH",
        default_artifact_path=Path("artifacts/durable-recovery-drill"),
        action_name="recovery_drill",
        source_name="recovery drill action lease snapshot",
    )
    runtime_retention_snapshot, runtime_retention_available = _load_metric_source(
        lambda: build_runtime_retention_history_snapshot(limit=1),
        source_name="runtime retention history snapshot",
    )
    runtime_retention_action_snapshot = _load_operator_action_lease_metric_source(
        settings,
        artifact_path_attribute="RUNTIME_RETENTION_ARTIFACT_PATH",
        default_artifact_path=Path("artifacts/runtime-retention-cleanup"),
        action_name="runtime_retention_cleanup",
        source_name="runtime retention action lease snapshot",
    )
    runtime_retention_preview, runtime_retention_preview_available = _load_metric_source(
        lambda: run_runtime_retention_cleanup(dry_run=True),
        source_name="runtime retention cleanup preview",
    )
    return _DurableQueueMetricSources(
        compute_stats=compute_stats,
        compute_available=compute_available,
        lineage_stats=lineage_stats,
        lineage_available=lineage_available,
        lineage_storage_capacity=lineage_storage_capacity,
        lineage_storage_capacity_available=lineage_storage_capacity_available,
        recovery_drill_snapshot=recovery_drill_snapshot,
        recovery_drill_available=recovery_drill_available,
        recovery_drill_action_snapshot=recovery_drill_action_snapshot,
        runtime_retention_snapshot=runtime_retention_snapshot,
        runtime_retention_available=runtime_retention_available,
        runtime_retention_action_snapshot=runtime_retention_action_snapshot,
        runtime_retention_preview=runtime_retention_preview,
        runtime_retention_preview_available=runtime_retention_preview_available,
    )


def _load_operator_action_lease_metric_source(
    settings,
    *,
    artifact_path_attribute: str,
    default_artifact_path: Path,
    action_name: str,
    source_name: str,
) -> Any | None:
    snapshot, _ = _load_metric_source(
        lambda: build_operator_action_lease_snapshot(
            artifact_directory=getattr(settings, artifact_path_attribute, default_artifact_path),
            action_name=action_name,
        ),
        source_name=source_name,
    )
    return snapshot


def _availability_and_preview_metrics(sources: _DurableQueueMetricSources) -> tuple[GaugeMetricFamily, ...]:
    metrics = [
        durable_queue_store_availability_metric(
            compute_available=sources.compute_available,
            lineage_available=sources.lineage_available,
        ),
        availability_metric(
            metric_name="lotus_performance_lineage_storage_capacity_availability",
            description="Availability of lineage storage capacity metrics.",
            is_available=sources.lineage_storage_capacity_available,
        ),
        availability_metric(
            metric_name="lotus_performance_recovery_drill_availability",
            description="Availability of retained durable recovery-drill history.",
            is_available=sources.recovery_drill_available and snapshot_available(sources.recovery_drill_snapshot),
        ),
        availability_metric(
            metric_name="lotus_performance_recovery_drill_action_availability",
            description="Availability of governed in-flight recovery-drill action lease visibility.",
            is_available=snapshot_available(sources.recovery_drill_action_snapshot),
        ),
        availability_metric(
            metric_name="lotus_performance_runtime_retention_availability",
            description="Availability of retained runtime-retention cleanup history.",
            is_available=sources.runtime_retention_available and snapshot_available(sources.runtime_retention_snapshot),
        ),
        availability_metric(
            metric_name="lotus_performance_runtime_retention_action_availability",
            description="Availability of governed in-flight runtime-retention cleanup lease visibility.",
            is_available=snapshot_available(sources.runtime_retention_action_snapshot),
        ),
        availability_metric(
            metric_name="lotus_performance_runtime_retention_preview_availability",
            description="Availability of the live runtime-retention preview under the current policy.",
            is_available=sources.runtime_retention_preview_available,
        ),
    ]
    if sources.runtime_retention_preview is not None:
        metrics.append(runtime_retention_prunable_items_metric(preview=sources.runtime_retention_preview))
    return tuple(metrics)


class DurableQueueCollector:
    def describe(self):
        for descriptor in _DURABLE_QUEUE_METRIC_DESCRIPTORS:
            yield descriptor.build()

    def collect(self):
        settings = get_settings()
        compute_queue_policy = build_compute_queue_policy(settings=settings)
        lineage_queue_policy = build_lineage_queue_policy(settings=settings)
        recovery_drill_policy = build_recovery_drill_policy(settings=settings)
        runtime_retention_policy = build_runtime_retention_policy(settings=settings)
        sources = _load_durable_queue_metric_sources(settings)

        yield from _availability_and_preview_metrics(sources)
        yield from _core_queue_and_storage_metrics(
            sources=sources,
            compute_queue_policy=compute_queue_policy,
            lineage_queue_policy=lineage_queue_policy,
        )
        yield from _lifecycle_history_metrics(
            sources=sources,
            recovery_drill_policy=recovery_drill_policy,
            runtime_retention_policy=runtime_retention_policy,
        )


def _core_queue_and_storage_metrics(
    *,
    sources: _DurableQueueMetricSources,
    compute_queue_policy: Any,
    lineage_queue_policy: Any,
) -> tuple[GaugeMetricFamily, ...]:
    metrics: list[GaugeMetricFamily] = []
    if sources.compute_stats is not None:
        metrics.append(compute_queue_job_count_metric(stats=sources.compute_stats))
        metrics.append(compute_queue_failure_pressure_metric(stats=sources.compute_stats))
        metrics.extend(compute_queue_oldest_age_metrics(stats=sources.compute_stats))
        metrics.append(
            compute_queue_degradation_breach_metric(
                stats=sources.compute_stats,
                policy=compute_queue_policy,
            )
        )

    if sources.lineage_stats is not None:
        metrics.extend(lineage_queue_payload_metrics(stats=sources.lineage_stats))
        metrics.append(
            lineage_queue_degradation_breach_metric(
                stats=sources.lineage_stats,
                policy=lineage_queue_policy,
            )
        )

    if sources.lineage_storage_capacity is not None:
        metrics.extend(lineage_storage_capacity_metrics(capacity=sources.lineage_storage_capacity))
        metrics.append(
            lineage_storage_pressure_breach_metric(
                capacity=sources.lineage_storage_capacity,
                policy=lineage_queue_policy,
            )
        )

    metrics.append(lineage_storage_pressure_threshold_metric(policy=lineage_queue_policy))
    return tuple(metrics)


def _lifecycle_history_metrics(
    *,
    sources: _DurableQueueMetricSources,
    recovery_drill_policy: Any,
    runtime_retention_policy: Any,
) -> tuple[GaugeMetricFamily, ...]:
    return (
        *_lifecycle_history_metric_group(
            snapshot=sources.recovery_drill_snapshot,
            action_snapshot=sources.recovery_drill_action_snapshot,
            policy=recovery_drill_policy,
            spec=_RECOVERY_DRILL_LIFECYCLE_METRICS,
        ),
        *_lifecycle_history_metric_group(
            snapshot=sources.runtime_retention_snapshot,
            action_snapshot=sources.runtime_retention_action_snapshot,
            policy=runtime_retention_policy,
            spec=_RUNTIME_RETENTION_LIFECYCLE_METRICS,
        ),
    )


def _lifecycle_history_metric_group(
    *,
    snapshot: Any | None,
    action_snapshot: Any | None,
    policy: Any,
    spec: _LifecycleHistoryMetricSpec,
) -> tuple[GaugeMetricFamily, ...]:
    metrics = [
        policy_threshold_metric(
            metric_name=spec.policy_metric_name,
            description=spec.policy_metric_description,
            max_age_seconds=policy.max_age_seconds,
            active_run_age_seconds=policy.active_run_age_seconds,
            reclaim_count=policy.reclaim_count,
        ),
        *operator_action_lease_metrics(
            snapshot=action_snapshot,
            spec=spec.action_metric_spec,
        ),
    ]

    if _snapshot_has_entries(snapshot):
        if snapshot is None:
            return tuple(metrics)
        latest = snapshot.entries[0]
        latest_age_seconds = age_seconds_since(latest.generated_at_utc)
        metrics.append(spec.latest_age_metric(latest_age_seconds=latest_age_seconds))
        metrics.append(
            spec.degradation_breach_metric(
                latest=latest,
                latest_age_seconds=latest_age_seconds,
                action_snapshot=action_snapshot,
                policy=policy,
            )
        )
    return tuple(metrics)


def _snapshot_has_entries(snapshot: Any | None) -> bool:
    return snapshot is not None and snapshot.status == "available" and bool(snapshot.entries)
