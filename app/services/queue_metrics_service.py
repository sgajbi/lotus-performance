from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from prometheus_client.core import GaugeMetricFamily

from app.core.config import get_settings
from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import get_lineage_storage_capacity
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.operator_action_lease_service import build_operator_action_lease_snapshot
from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot
from app.services.runtime_degradation_policy import threshold_breach_flag
from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot
from app.services.runtime_retention_service import run_runtime_retention_cleanup


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
        try:
            compute_stats = compute_job_store.get_queue_stats()
            compute_available = True
        except Exception:
            compute_stats = None
            compute_available = False
        try:
            lineage_stats = lineage_metadata_store.get_pending_payload_stats()
            lineage_available = True
        except Exception:
            lineage_stats = None
            lineage_available = False
        try:
            lineage_storage_capacity = get_lineage_storage_capacity()
            lineage_storage_capacity_available = True
        except Exception:
            lineage_storage_capacity = None
            lineage_storage_capacity_available = False
        try:
            recovery_drill_snapshot = build_recovery_drill_history_snapshot(limit=1)
            recovery_drill_available = True
        except Exception:
            recovery_drill_snapshot = None
            recovery_drill_available = False
        try:
            recovery_drill_action_snapshot = build_operator_action_lease_snapshot(
                artifact_directory=getattr(
                    settings,
                    "RECOVERY_DRILL_ARTIFACT_PATH",
                    Path("artifacts/durable-recovery-drill"),
                ),
                action_name="recovery_drill",
            )
        except Exception:
            recovery_drill_action_snapshot = None
        try:
            runtime_retention_snapshot = build_runtime_retention_history_snapshot(limit=1)
            runtime_retention_available = True
        except Exception:
            runtime_retention_snapshot = None
            runtime_retention_available = False
        try:
            runtime_retention_action_snapshot = build_operator_action_lease_snapshot(
                artifact_directory=getattr(
                    settings,
                    "RUNTIME_RETENTION_ARTIFACT_PATH",
                    Path("artifacts/runtime-retention-cleanup"),
                ),
                action_name="runtime_retention_cleanup",
            )
        except Exception:
            runtime_retention_action_snapshot = None
        try:
            runtime_retention_preview = run_runtime_retention_cleanup(dry_run=True)
            runtime_retention_preview_available = True
        except Exception:
            runtime_retention_preview = None
            runtime_retention_preview_available = False

        availability = GaugeMetricFamily(
            "lotus_performance_durable_queue_store_availability",
            "Availability of durable queue metric sources by store.",
            labels=["store"],
        )
        availability.add_metric(["compute"], 1 if compute_available else 0)
        availability.add_metric(["lineage"], 1 if lineage_available else 0)
        yield availability

        lineage_storage_availability = GaugeMetricFamily(
            "lotus_performance_lineage_storage_capacity_availability",
            "Availability of lineage storage capacity metrics.",
        )
        lineage_storage_availability.add_metric([], 1 if lineage_storage_capacity_available else 0)
        yield lineage_storage_availability

        recovery_drill_availability = GaugeMetricFamily(
            "lotus_performance_recovery_drill_availability",
            "Availability of retained durable recovery-drill history.",
        )
        recovery_drill_availability.add_metric(
            [],
            1
            if recovery_drill_available
            and recovery_drill_snapshot is not None
            and recovery_drill_snapshot.status == "available"
            else 0,
        )
        yield recovery_drill_availability

        recovery_drill_action_availability = GaugeMetricFamily(
            "lotus_performance_recovery_drill_action_availability",
            "Availability of governed in-flight recovery-drill action lease visibility.",
        )
        recovery_drill_action_availability.add_metric(
            [],
            1
            if recovery_drill_action_snapshot is not None and recovery_drill_action_snapshot.status == "available"
            else 0,
        )
        yield recovery_drill_action_availability

        runtime_retention_availability = GaugeMetricFamily(
            "lotus_performance_runtime_retention_availability",
            "Availability of retained runtime-retention cleanup history.",
        )
        runtime_retention_availability.add_metric(
            [],
            1
            if runtime_retention_available
            and runtime_retention_snapshot is not None
            and runtime_retention_snapshot.status == "available"
            else 0,
        )
        yield runtime_retention_availability

        runtime_retention_action_availability = GaugeMetricFamily(
            "lotus_performance_runtime_retention_action_availability",
            "Availability of governed in-flight runtime-retention cleanup lease visibility.",
        )
        runtime_retention_action_availability.add_metric(
            [],
            1
            if runtime_retention_action_snapshot is not None and runtime_retention_action_snapshot.status == "available"
            else 0,
        )
        yield runtime_retention_action_availability

        runtime_retention_preview_availability = GaugeMetricFamily(
            "lotus_performance_runtime_retention_preview_availability",
            "Availability of the live runtime-retention preview under the current policy.",
        )
        runtime_retention_preview_availability.add_metric([], 1 if runtime_retention_preview_available else 0)
        yield runtime_retention_preview_availability

        if runtime_retention_preview is not None:
            runtime_retention_prunable = GaugeMetricFamily(
                "lotus_performance_runtime_retention_prunable_items",
                "Current runtime-retention items that would be pruned by a dry-run cleanup.",
                labels=["category"],
            )
            runtime_retention_prunable.add_metric(["execution"], runtime_retention_preview.prunable_execution_count)
            runtime_retention_prunable.add_metric(["compute_job"], runtime_retention_preview.prunable_compute_job_count)
            runtime_retention_prunable.add_metric(
                ["async_result"], runtime_retention_preview.prunable_async_result_count
            )
            runtime_retention_prunable.add_metric(
                ["lineage_record"], runtime_retention_preview.prunable_lineage_record_count
            )
            runtime_retention_prunable.add_metric(
                ["lineage_artifact"], runtime_retention_preview.prunable_lineage_artifact_count
            )
            yield runtime_retention_prunable

        if compute_stats is not None:
            compute_jobs = GaugeMetricFamily(
                "lotus_performance_compute_queue_jobs",
                "Durable compute job counts by status.",
                labels=["status"],
            )
            compute_jobs.add_metric(["pending"], compute_stats.pending_count)
            compute_jobs.add_metric(["leased"], compute_stats.leased_count)
            compute_jobs.add_metric(["running"], compute_stats.running_count)
            compute_jobs.add_metric(["failed"], compute_stats.failed_count)
            compute_jobs.add_metric(["complete"], compute_stats.complete_count)
            yield compute_jobs

        if compute_stats is not None:
            compute_failure_pressure = GaugeMetricFamily(
                "lotus_performance_compute_queue_failure_pressure_jobs",
                "Durable compute job counts for retry backlog and failure-pressure categories.",
                labels=["category"],
            )
            compute_failure_pressure.add_metric(["retry_backlog"], compute_stats.retry_backlog_count)
            compute_failure_pressure.add_metric(["lease_expired"], compute_stats.lease_expired_count)
            compute_failure_pressure.add_metric(["reclaimable"], compute_stats.reclaimable_count)
            compute_failure_pressure.add_metric(["terminal_failure"], compute_stats.terminal_failure_count)
            yield compute_failure_pressure

        if compute_stats is not None:
            compute_oldest_pending = GaugeMetricFamily(
                "lotus_performance_compute_queue_oldest_pending_age_seconds",
                "Age in seconds of the oldest pending compute job.",
            )
            compute_oldest_pending.add_metric([], compute_stats.oldest_pending_age_seconds)
            yield compute_oldest_pending

        if compute_stats is not None:
            compute_oldest_leased = GaugeMetricFamily(
                "lotus_performance_compute_queue_oldest_leased_age_seconds",
                "Age in seconds of the oldest leased compute job.",
            )
            compute_oldest_leased.add_metric([], compute_stats.oldest_leased_age_seconds)
            yield compute_oldest_leased

        if compute_stats is not None:
            compute_oldest_running = GaugeMetricFamily(
                "lotus_performance_compute_queue_oldest_running_age_seconds",
                "Age in seconds of the oldest running compute job.",
            )
            compute_oldest_running.add_metric([], compute_stats.oldest_running_age_seconds)
            yield compute_oldest_running

            compute_breach = GaugeMetricFamily(
                "lotus_performance_compute_queue_degradation_breach",
                "Whether the compute queue currently breaches a configured runtime degradation threshold.",
                labels=["reason"],
            )
            compute_breach.add_metric(
                ["compute_retry_backlog_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
                    observed_value=compute_stats.retry_backlog_count,
                ),
            )
            compute_breach.add_metric(
                ["compute_terminal_failure_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
                    observed_value=compute_stats.terminal_failure_count,
                ),
            )
            compute_breach.add_metric(
                ["compute_lease_expiry_pressure_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT", 0),
                    observed_value=compute_stats.lease_expired_count,
                ),
            )
            compute_breach.add_metric(
                ["compute_pending_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
                    observed_value=compute_stats.oldest_pending_age_seconds,
                ),
            )
            compute_breach.add_metric(
                ["compute_leased_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
                    observed_value=compute_stats.oldest_leased_age_seconds,
                ),
            )
            compute_breach.add_metric(
                ["compute_running_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS", 0.0),
                    observed_value=compute_stats.oldest_running_age_seconds,
                ),
            )
            yield compute_breach

        if lineage_stats is not None:
            lineage_pending = GaugeMetricFamily(
                "lotus_performance_lineage_queue_pending_payloads",
                "Number of pending lineage payloads awaiting materialization.",
            )
            lineage_pending.add_metric([], lineage_stats.pending_payload_count)
            yield lineage_pending

        if lineage_stats is not None:
            lineage_failure_pressure = GaugeMetricFamily(
                "lotus_performance_lineage_queue_failure_pressure_payloads",
                "Lineage payload counts for retry backlog and terminal failure categories.",
                labels=["category"],
            )
            lineage_failure_pressure.add_metric(["retry_backlog"], lineage_stats.retry_backlog_count)
            lineage_failure_pressure.add_metric(["reclaimable"], lineage_stats.reclaimable_count)
            lineage_failure_pressure.add_metric(["terminal_failure"], lineage_stats.terminal_failure_count)
            yield lineage_failure_pressure

        if lineage_stats is not None:
            lineage_oldest_pending = GaugeMetricFamily(
                "lotus_performance_lineage_queue_oldest_pending_age_seconds",
                "Age in seconds of the oldest pending lineage payload.",
            )
            lineage_oldest_pending.add_metric([], lineage_stats.oldest_pending_age_seconds)
            yield lineage_oldest_pending

            lineage_breach = GaugeMetricFamily(
                "lotus_performance_lineage_queue_degradation_breach",
                "Whether the lineage queue currently breaches a configured runtime degradation threshold.",
                labels=["reason"],
            )
            lineage_breach.add_metric(
                ["lineage_retry_backlog_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
                    observed_value=lineage_stats.retry_backlog_count,
                ),
            )
            lineage_breach.add_metric(
                ["lineage_terminal_failure_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
                    observed_value=lineage_stats.terminal_failure_count,
                ),
            )
            lineage_breach.add_metric(
                ["lineage_pending_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
                    observed_value=lineage_stats.oldest_pending_age_seconds,
                ),
            )
            lineage_breach.add_metric(
                ["lineage_leased_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
                    observed_value=getattr(lineage_stats, "oldest_leased_age_seconds", 0.0),
                ),
            )
            yield lineage_breach

        if lineage_storage_capacity is not None:
            lineage_storage_bytes = GaugeMetricFamily(
                "lotus_performance_lineage_storage_capacity_bytes",
                "Lineage storage capacity by segment.",
                labels=["segment"],
            )
            lineage_storage_bytes.add_metric(["total"], lineage_storage_capacity.total_bytes)
            lineage_storage_bytes.add_metric(["used"], lineage_storage_capacity.used_bytes)
            lineage_storage_bytes.add_metric(["free"], lineage_storage_capacity.free_bytes)
            yield lineage_storage_bytes

            lineage_storage_free_ratio = GaugeMetricFamily(
                "lotus_performance_lineage_storage_free_ratio",
                "Fraction of free lineage storage capacity currently remaining.",
            )
            lineage_storage_free_ratio.add_metric([], lineage_storage_capacity.free_ratio)
            yield lineage_storage_free_ratio

            lineage_storage_breach = GaugeMetricFamily(
                "lotus_performance_lineage_storage_pressure_breach",
                "Whether lineage storage currently breaches a proactive saturation threshold.",
                labels=["reason"],
            )
            min_free_bytes = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0)
            min_free_ratio = getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0)
            lineage_storage_breach.add_metric(
                ["lineage_storage_free_bytes_below_threshold"],
                threshold_breach_flag(
                    observed_value=lineage_storage_capacity.free_bytes,
                    threshold_value=min_free_bytes,
                    comparison="at_or_below",
                ),
            )
            lineage_storage_breach.add_metric(
                ["lineage_storage_free_ratio_below_threshold"],
                threshold_breach_flag(
                    observed_value=lineage_storage_capacity.free_ratio,
                    threshold_value=min_free_ratio,
                    comparison="at_or_below",
                ),
            )
            yield lineage_storage_breach

        lineage_storage_thresholds = GaugeMetricFamily(
            "lotus_performance_lineage_storage_pressure_threshold",
            "Configured proactive lineage storage pressure thresholds.",
            labels=["threshold"],
        )
        lineage_storage_thresholds.add_metric(
            ["min_free_bytes"],
            getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES", 0),
        )
        lineage_storage_thresholds.add_metric(
            ["min_free_ratio"],
            getattr(settings, "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO", 0.0),
        )
        yield lineage_storage_thresholds

        recovery_drill_thresholds = GaugeMetricFamily(
            "lotus_performance_recovery_drill_policy_threshold",
            "Configured recovery-drill degradation thresholds.",
            labels=["threshold"],
        )
        recovery_drill_thresholds.add_metric(
            ["max_age_seconds"],
            getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS", 0.0),
        )
        recovery_drill_thresholds.add_metric(
            ["active_run_age_seconds"],
            getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS", 0.0),
        )
        recovery_drill_thresholds.add_metric(
            ["reclaim_count"],
            getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0),
        )
        yield recovery_drill_thresholds

        if recovery_drill_action_snapshot is not None and recovery_drill_action_snapshot.status == "available":
            recovery_drill_active_actions = GaugeMetricFamily(
                "lotus_performance_recovery_drill_active_actions",
                "Number of active governed recovery-drill runs currently holding an in-flight lease.",
            )
            recovery_drill_active_actions.add_metric([], len(recovery_drill_action_snapshot.active_leases))
            yield recovery_drill_active_actions
            if recovery_drill_action_snapshot.active_leases:
                recovery_drill_oldest_active_action_age = GaugeMetricFamily(
                    "lotus_performance_recovery_drill_oldest_active_action_age_seconds",
                    "Age in seconds of the oldest active governed recovery-drill run.",
                )
                recovery_drill_oldest_active_action_age.add_metric(
                    [],
                    _age_seconds(recovery_drill_action_snapshot.active_leases[0].acquired_at_utc),
                )
                yield recovery_drill_oldest_active_action_age
            if recovery_drill_action_snapshot.latest_reclaimed_lease is not None:
                recovery_drill_latest_reclaimed_action_age = GaugeMetricFamily(
                    "lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds",
                    "Age in seconds since the latest stale governed recovery-drill lease reclaim.",
                )
                recovery_drill_latest_reclaimed_action_age.add_metric(
                    [],
                    _age_seconds(recovery_drill_action_snapshot.latest_reclaimed_lease.reclaimed_at_utc),
                )
                yield recovery_drill_latest_reclaimed_action_age
                recovery_drill_reclaimed_actions = GaugeMetricFamily(
                    "lotus_performance_recovery_drill_reclaimed_actions",
                    "Count of stale governed recovery-drill leases reclaimed and retained in the current control-plane counter.",
                )
                recovery_drill_reclaimed_actions.add_metric(
                    [],
                    recovery_drill_action_snapshot.latest_reclaimed_lease.reclaim_count,
                )
                yield recovery_drill_reclaimed_actions

        runtime_retention_thresholds = GaugeMetricFamily(
            "lotus_performance_runtime_retention_policy_threshold",
            "Configured runtime-retention degradation thresholds.",
            labels=["threshold"],
        )
        runtime_retention_thresholds.add_metric(
            ["max_age_seconds"],
            getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0),
        )
        runtime_retention_thresholds.add_metric(
            ["active_run_age_seconds"],
            getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS", 0.0),
        )
        runtime_retention_thresholds.add_metric(
            ["reclaim_count"],
            getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0),
        )
        yield runtime_retention_thresholds

        if runtime_retention_action_snapshot is not None and runtime_retention_action_snapshot.status == "available":
            runtime_retention_active_actions = GaugeMetricFamily(
                "lotus_performance_runtime_retention_active_actions",
                "Number of active governed runtime-retention cleanups currently holding an in-flight lease.",
            )
            runtime_retention_active_actions.add_metric([], len(runtime_retention_action_snapshot.active_leases))
            yield runtime_retention_active_actions
            if runtime_retention_action_snapshot.active_leases:
                runtime_retention_oldest_active_action_age = GaugeMetricFamily(
                    "lotus_performance_runtime_retention_oldest_active_action_age_seconds",
                    "Age in seconds of the oldest active governed runtime-retention cleanup.",
                )
                runtime_retention_oldest_active_action_age.add_metric(
                    [],
                    _age_seconds(runtime_retention_action_snapshot.active_leases[0].acquired_at_utc),
                )
                yield runtime_retention_oldest_active_action_age
            if runtime_retention_action_snapshot.latest_reclaimed_lease is not None:
                runtime_retention_latest_reclaimed_action_age = GaugeMetricFamily(
                    "lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds",
                    "Age in seconds since the latest stale governed runtime-retention lease reclaim.",
                )
                runtime_retention_latest_reclaimed_action_age.add_metric(
                    [],
                    _age_seconds(runtime_retention_action_snapshot.latest_reclaimed_lease.reclaimed_at_utc),
                )
                yield runtime_retention_latest_reclaimed_action_age
                runtime_retention_reclaimed_actions = GaugeMetricFamily(
                    "lotus_performance_runtime_retention_reclaimed_actions",
                    "Count of stale governed runtime-retention leases reclaimed and retained in the current control-plane counter.",
                )
                runtime_retention_reclaimed_actions.add_metric(
                    [],
                    runtime_retention_action_snapshot.latest_reclaimed_lease.reclaim_count,
                )
                yield runtime_retention_reclaimed_actions

        if (
            recovery_drill_snapshot is not None
            and recovery_drill_snapshot.status == "available"
            and recovery_drill_snapshot.entries
        ):
            latest = recovery_drill_snapshot.entries[0]
            latest_age_seconds = _age_seconds(latest.generated_at_utc)

            recovery_drill_age = GaugeMetricFamily(
                "lotus_performance_recovery_drill_latest_age_seconds",
                "Age in seconds of the latest retained durable recovery drill.",
            )
            recovery_drill_age.add_metric([], latest_age_seconds)
            yield recovery_drill_age

            recovery_drill_breach = GaugeMetricFamily(
                "lotus_performance_recovery_drill_degradation_breach",
                "Whether retained durable recovery-drill history currently breaches a recovery assurance policy.",
                labels=["reason"],
            )
            recovery_drill_breach.add_metric(
                ["recovery_drill_latest_not_passed"],
                1 if latest.status != "passed" else 0,
            )
            recovery_drill_breach.add_metric(
                ["recovery_drill_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS", 0.0),
                    observed_value=latest_age_seconds,
                ),
            )
            recovery_drill_breach.add_metric(
                ["recovery_drill_active_run_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(
                        settings,
                        "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
                        0.0,
                    ),
                    observed_value=(
                        0.0
                        if recovery_drill_action_snapshot is None
                        or recovery_drill_action_snapshot.status != "available"
                        or not recovery_drill_action_snapshot.active_leases
                        else _age_seconds(recovery_drill_action_snapshot.active_leases[0].acquired_at_utc)
                    ),
                ),
            )
            recovery_drill_breach.add_metric(
                ["recovery_drill_reclaim_pressure_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT", 0),
                    observed_value=(
                        0
                        if recovery_drill_action_snapshot is None
                        or recovery_drill_action_snapshot.status != "available"
                        or recovery_drill_action_snapshot.latest_reclaimed_lease is None
                        else recovery_drill_action_snapshot.latest_reclaimed_lease.reclaim_count
                    ),
                ),
            )
            yield recovery_drill_breach

        if (
            runtime_retention_snapshot is not None
            and runtime_retention_snapshot.status == "available"
            and runtime_retention_snapshot.entries
        ):
            latest = runtime_retention_snapshot.entries[0]
            latest_age_seconds = _age_seconds(latest.generated_at_utc)

            runtime_retention_age = GaugeMetricFamily(
                "lotus_performance_runtime_retention_latest_age_seconds",
                "Age in seconds of the latest retained runtime-retention cleanup.",
            )
            runtime_retention_age.add_metric([], latest_age_seconds)
            yield runtime_retention_age

            runtime_retention_breach = GaugeMetricFamily(
                "lotus_performance_runtime_retention_degradation_breach",
                "Whether retained runtime-retention cleanup history currently breaches a lifecycle-governance policy.",
                labels=["reason"],
            )
            runtime_retention_breach.add_metric(
                ["runtime_retention_latest_not_applied"],
                1 if latest.cleanup_mode != "apply" else 0,
            )
            runtime_retention_breach.add_metric(
                ["runtime_retention_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS", 0.0),
                    observed_value=latest_age_seconds,
                ),
            )
            runtime_retention_breach.add_metric(
                ["runtime_retention_active_run_age_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(
                        settings,
                        "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS",
                        0.0,
                    ),
                    observed_value=(
                        0.0
                        if runtime_retention_action_snapshot is None
                        or runtime_retention_action_snapshot.status != "available"
                        or not runtime_retention_action_snapshot.active_leases
                        else _age_seconds(runtime_retention_action_snapshot.active_leases[0].acquired_at_utc)
                    ),
                ),
            )
            runtime_retention_breach.add_metric(
                ["runtime_retention_reclaim_pressure_exceeded"],
                threshold_breach_flag(
                    threshold_value=getattr(settings, "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT", 0),
                    observed_value=(
                        0
                        if runtime_retention_action_snapshot is None
                        or runtime_retention_action_snapshot.status != "available"
                        or runtime_retention_action_snapshot.latest_reclaimed_lease is None
                        else runtime_retention_action_snapshot.latest_reclaimed_lease.reclaim_count
                    ),
                ),
            )
            yield runtime_retention_breach


def _age_seconds(timestamp_utc: str) -> float:
    generated_at = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    return max(0.0, (datetime.now(UTC) - generated_at).total_seconds())
