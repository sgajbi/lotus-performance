from app.services.queue_metrics_service import DurableQueueCollector


def test_queue_metrics_collector_emits_compute_and_lineage_metrics(monkeypatch):
    class _ComputeStats:
        pending_count = 2
        leased_count = 1
        running_count = 3
        failed_count = 4
        complete_count = 5
        oldest_pending_age_seconds = 12.5
        oldest_leased_age_seconds = 6.25
        oldest_running_age_seconds = 3.5

    class _LineageStats:
        pending_payload_count = 6
        oldest_pending_age_seconds = 7.5

    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: _ComputeStats(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: _LineageStats(),
    )

    metrics = list(DurableQueueCollector().collect())
    metric_names = {metric.name for metric in metrics}

    assert "lotus_performance_compute_queue_jobs" in metric_names
    assert "lotus_performance_compute_queue_oldest_pending_age_seconds" in metric_names
    assert "lotus_performance_compute_queue_oldest_leased_age_seconds" in metric_names
    assert "lotus_performance_compute_queue_oldest_running_age_seconds" in metric_names
    assert "lotus_performance_lineage_queue_pending_payloads" in metric_names
    assert "lotus_performance_lineage_queue_oldest_pending_age_seconds" in metric_names
