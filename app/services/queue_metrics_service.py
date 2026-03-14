from __future__ import annotations

from prometheus_client.core import GaugeMetricFamily

from app.core.config import get_settings
from app.services.compute_job_store import compute_job_store
from app.services.durability_health_service import get_lineage_storage_capacity
from app.services.lineage_metadata_store import lineage_metadata_store


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

    def collect(self):
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
        settings = get_settings()

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
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
                    observed=compute_stats.retry_backlog_count,
                ),
            )
            compute_breach.add_metric(
                ["compute_terminal_failure_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
                    observed=compute_stats.terminal_failure_count,
                ),
            )
            compute_breach.add_metric(
                ["compute_lease_expiry_pressure_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT", 0),
                    observed=compute_stats.lease_expired_count,
                ),
            )
            compute_breach.add_metric(
                ["compute_pending_age_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
                    observed=compute_stats.oldest_pending_age_seconds,
                ),
            )
            compute_breach.add_metric(
                ["compute_leased_age_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
                    observed=compute_stats.oldest_leased_age_seconds,
                ),
            )
            compute_breach.add_metric(
                ["compute_running_age_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS", 0.0),
                    observed=compute_stats.oldest_running_age_seconds,
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
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT", 0),
                    observed=lineage_stats.retry_backlog_count,
                ),
            )
            lineage_breach.add_metric(
                ["lineage_terminal_failure_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT", 0),
                    observed=lineage_stats.terminal_failure_count,
                ),
            )
            lineage_breach.add_metric(
                ["lineage_pending_age_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS", 0.0),
                    observed=lineage_stats.oldest_pending_age_seconds,
                ),
            )
            lineage_breach.add_metric(
                ["lineage_leased_age_exceeded"],
                _breach_flag(
                    threshold=getattr(settings, "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS", 0.0),
                    observed=getattr(lineage_stats, "oldest_leased_age_seconds", 0.0),
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
                1 if min_free_bytes > 0 and lineage_storage_capacity.free_bytes <= min_free_bytes else 0,
            )
            lineage_storage_breach.add_metric(
                ["lineage_storage_free_ratio_below_threshold"],
                1 if min_free_ratio > 0 and lineage_storage_capacity.free_ratio <= min_free_ratio else 0,
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


def _breach_flag(*, threshold: float | int, observed: float | int) -> int:
    return 1 if threshold > 0 and observed >= threshold else 0
