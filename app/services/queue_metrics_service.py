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
    recovery_drill_action_snapshot, _ = _load_metric_source(
        lambda: build_operator_action_lease_snapshot(
            artifact_directory=getattr(
                settings,
                "RECOVERY_DRILL_ARTIFACT_PATH",
                Path("artifacts/durable-recovery-drill"),
            ),
            action_name="recovery_drill",
        ),
        source_name="recovery drill action lease snapshot",
    )
    runtime_retention_snapshot, runtime_retention_available = _load_metric_source(
        lambda: build_runtime_retention_history_snapshot(limit=1),
        source_name="runtime retention history snapshot",
    )
    runtime_retention_action_snapshot, _ = _load_metric_source(
        lambda: build_operator_action_lease_snapshot(
            artifact_directory=getattr(
                settings,
                "RUNTIME_RETENTION_ARTIFACT_PATH",
                Path("artifacts/runtime-retention-cleanup"),
            ),
            action_name="runtime_retention_cleanup",
        ),
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
        yield GaugeMetricFamily(
            "lotus_performance_durable_queue_store_availability",
            "Availability of durable queue metric sources by store.",
            labels=["store"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_jobs",
            "Durable compute job counts by status.",
            labels=["status"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_failure_pressure_jobs",
            "Durable compute job counts for retry backlog and failure-pressure categories.",
            labels=["category"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending compute job.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_oldest_leased_age_seconds",
            "Age in seconds of the oldest leased compute job.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_oldest_running_age_seconds",
            "Age in seconds of the oldest running compute job.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_degradation_breach",
            "Whether the compute queue currently breaches a configured runtime degradation threshold.",
            labels=["reason"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_queue_pending_payloads",
            "Number of pending lineage payloads awaiting materialization.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_queue_failure_pressure_payloads",
            "Lineage payload counts for retry backlog and terminal failure categories.",
            labels=["category"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending lineage payload.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_queue_degradation_breach",
            "Whether the lineage queue currently breaches a configured runtime degradation threshold.",
            labels=["reason"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_storage_capacity_availability",
            "Availability of lineage storage capacity metrics.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_storage_capacity_bytes",
            "Lineage storage capacity by segment.",
            labels=["segment"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_storage_free_ratio",
            "Fraction of free lineage storage capacity currently remaining.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_storage_pressure_threshold",
            "Configured proactive lineage storage pressure thresholds.",
            labels=["threshold"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_storage_pressure_breach",
            "Whether lineage storage currently breaches a proactive saturation threshold.",
            labels=["reason"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_availability",
            "Availability of retained durable recovery-drill history.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_action_availability",
            "Availability of governed in-flight recovery-drill action lease visibility.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_active_actions",
            "Number of active governed recovery-drill runs currently holding an in-flight lease.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_oldest_active_action_age_seconds",
            "Age in seconds of the oldest active governed recovery-drill run.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds",
            "Age in seconds since the latest stale governed recovery-drill lease reclaim.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_reclaimed_actions",
            "Count of stale governed recovery-drill leases reclaimed and retained in the current control-plane counter.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_latest_age_seconds",
            "Age in seconds of the latest retained durable recovery drill.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_policy_threshold",
            "Configured recovery-drill degradation thresholds.",
            labels=["threshold"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_recovery_drill_degradation_breach",
            "Whether retained durable recovery-drill history currently breaches a recovery assurance policy.",
            labels=["reason"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_availability",
            "Availability of retained runtime-retention cleanup history.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_action_availability",
            "Availability of governed in-flight runtime-retention cleanup lease visibility.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_active_actions",
            "Number of active governed runtime-retention cleanups currently holding an in-flight lease.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_oldest_active_action_age_seconds",
            "Age in seconds of the oldest active governed runtime-retention cleanup.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds",
            "Age in seconds since the latest stale governed runtime-retention lease reclaim.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_reclaimed_actions",
            "Count of stale governed runtime-retention leases reclaimed and retained in the current control-plane counter.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_latest_age_seconds",
            "Age in seconds of the latest retained runtime-retention cleanup.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_policy_threshold",
            "Configured runtime-retention degradation thresholds.",
            labels=["threshold"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_degradation_breach",
            "Whether retained runtime-retention cleanup history currently breaches a lifecycle-governance policy.",
            labels=["reason"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_preview_availability",
            "Availability of the live runtime-retention preview under the current policy.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_runtime_retention_prunable_items",
            "Current runtime-retention items that would be pruned by a dry-run cleanup.",
            labels=["category"],
        )

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

        yield policy_threshold_metric(
            metric_name="lotus_performance_recovery_drill_policy_threshold",
            description="Configured recovery-drill degradation thresholds.",
            max_age_seconds=recovery_drill_policy.max_age_seconds,
            active_run_age_seconds=recovery_drill_policy.active_run_age_seconds,
            reclaim_count=recovery_drill_policy.reclaim_count,
        )

        yield from operator_action_lease_metrics(
            snapshot=sources.recovery_drill_action_snapshot,
            spec=RECOVERY_DRILL_ACTION_METRICS,
        )

        yield policy_threshold_metric(
            metric_name="lotus_performance_runtime_retention_policy_threshold",
            description="Configured runtime-retention degradation thresholds.",
            max_age_seconds=runtime_retention_policy.max_age_seconds,
            active_run_age_seconds=runtime_retention_policy.active_run_age_seconds,
            reclaim_count=runtime_retention_policy.reclaim_count,
        )

        yield from operator_action_lease_metrics(
            snapshot=sources.runtime_retention_action_snapshot,
            spec=RUNTIME_RETENTION_ACTION_METRICS,
        )

        if (
            sources.recovery_drill_snapshot is not None
            and sources.recovery_drill_snapshot.status == "available"
            and sources.recovery_drill_snapshot.entries
        ):
            latest = sources.recovery_drill_snapshot.entries[0]
            latest_age_seconds = age_seconds_since(latest.generated_at_utc)

            yield recovery_drill_latest_age_metric(latest_age_seconds=latest_age_seconds)

            yield recovery_drill_degradation_breach_metric(
                latest=latest,
                latest_age_seconds=latest_age_seconds,
                action_snapshot=sources.recovery_drill_action_snapshot,
                policy=recovery_drill_policy,
            )

        if (
            sources.runtime_retention_snapshot is not None
            and sources.runtime_retention_snapshot.status == "available"
            and sources.runtime_retention_snapshot.entries
        ):
            latest = sources.runtime_retention_snapshot.entries[0]
            latest_age_seconds = age_seconds_since(latest.generated_at_utc)

            yield runtime_retention_latest_age_metric(latest_age_seconds=latest_age_seconds)

            yield runtime_retention_degradation_breach_metric(
                latest=latest,
                latest_age_seconds=latest_age_seconds,
                action_snapshot=sources.runtime_retention_action_snapshot,
                policy=runtime_retention_policy,
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
