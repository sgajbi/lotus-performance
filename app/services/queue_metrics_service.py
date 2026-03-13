from __future__ import annotations

from prometheus_client.core import GaugeMetricFamily

from app.services.compute_job_store import compute_job_store
from app.services.lineage_metadata_store import lineage_metadata_store


class DurableQueueCollector:
    def describe(self):
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_jobs",
            "Durable compute job counts by status.",
            labels=["status"],
        )
        yield GaugeMetricFamily(
            "lotus_performance_compute_queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending compute job.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_queue_pending_payloads",
            "Number of pending lineage payloads awaiting materialization.",
        )
        yield GaugeMetricFamily(
            "lotus_performance_lineage_queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending lineage payload.",
        )

    def collect(self):
        try:
            compute_stats = compute_job_store.get_queue_stats()
        except Exception:
            compute_stats = None
        try:
            lineage_stats = lineage_metadata_store.get_pending_payload_stats()
        except Exception:
            lineage_stats = None

        compute_jobs = GaugeMetricFamily(
            "lotus_performance_compute_queue_jobs",
            "Durable compute job counts by status.",
            labels=["status"],
        )
        compute_jobs.add_metric(["pending"], 0 if compute_stats is None else compute_stats.pending_count)
        compute_jobs.add_metric(["leased"], 0 if compute_stats is None else compute_stats.leased_count)
        compute_jobs.add_metric(["running"], 0 if compute_stats is None else compute_stats.running_count)
        compute_jobs.add_metric(["failed"], 0 if compute_stats is None else compute_stats.failed_count)
        compute_jobs.add_metric(["complete"], 0 if compute_stats is None else compute_stats.complete_count)
        yield compute_jobs

        compute_oldest_pending = GaugeMetricFamily(
            "lotus_performance_compute_queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending compute job.",
        )
        compute_oldest_pending.add_metric([], 0 if compute_stats is None else compute_stats.oldest_pending_age_seconds)
        yield compute_oldest_pending

        lineage_pending = GaugeMetricFamily(
            "lotus_performance_lineage_queue_pending_payloads",
            "Number of pending lineage payloads awaiting materialization.",
        )
        lineage_pending.add_metric([], 0 if lineage_stats is None else lineage_stats.pending_payload_count)
        yield lineage_pending

        lineage_oldest_pending = GaugeMetricFamily(
            "lotus_performance_lineage_queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending lineage payload.",
        )
        lineage_oldest_pending.add_metric([], 0 if lineage_stats is None else lineage_stats.oldest_pending_age_seconds)
        yield lineage_oldest_pending
