from __future__ import annotations

from prometheus_client.core import GaugeMetricFamily

from app.services.compute_job_store import compute_job_store
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

        availability = GaugeMetricFamily(
            "lotus_performance_durable_queue_store_availability",
            "Availability of durable queue metric sources by store.",
            labels=["store"],
        )
        availability.add_metric(["compute"], 1 if compute_available else 0)
        availability.add_metric(["lineage"], 1 if lineage_available else 0)
        yield availability

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
            lineage_failure_pressure.add_metric(["terminal_failure"], lineage_stats.terminal_failure_count)
            yield lineage_failure_pressure

        if lineage_stats is not None:
            lineage_oldest_pending = GaugeMetricFamily(
                "lotus_performance_lineage_queue_oldest_pending_age_seconds",
                "Age in seconds of the oldest pending lineage payload.",
            )
            lineage_oldest_pending.add_metric([], lineage_stats.oldest_pending_age_seconds)
            yield lineage_oldest_pending
