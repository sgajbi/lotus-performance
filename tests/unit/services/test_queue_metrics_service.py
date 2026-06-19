import logging
from pathlib import Path
from types import SimpleNamespace

from app.services.queue_metrics_service import (
    DurableQueueCollector,
    _availability_and_preview_metrics,
    _core_queue_and_storage_metrics,
    _DurableQueueMetricSources,
    _lifecycle_history_metrics,
    _load_durable_queue_metric_sources,
    _load_metric_source,
)
from app.services.runtime_status_domain import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RecoveryDrillDegradationPolicy,
    RuntimeRetentionDegradationPolicy,
)


def test_load_metric_source_returns_value_and_availability():
    source, available = _load_metric_source(lambda: "metric-source")

    assert source == "metric-source"
    assert available is True


def test_load_metric_source_suppresses_source_failures():
    source, available = _load_metric_source(lambda: (_ for _ in ()).throw(RuntimeError("source unavailable")))

    assert source is None
    assert available is False


def test_load_metric_source_logs_source_failures(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.queue_metrics_service")

    source, available = _load_metric_source(
        lambda: (_ for _ in ()).throw(RuntimeError("source unavailable")),
        source_name="compute queue stats",
    )

    assert source is None
    assert available is False
    assert "Queue metric source load failed for compute queue stats." in caplog.text
    assert "RuntimeError: source unavailable" in caplog.text


def test_durable_queue_collector_describe_preserves_metric_catalog_order_and_labels():
    metrics = list(DurableQueueCollector().describe())

    metric_names = [metric.name for metric in metrics]
    assert metric_names == [
        "lotus_performance_durable_queue_store_availability",
        "lotus_performance_compute_queue_jobs",
        "lotus_performance_compute_queue_failure_pressure_jobs",
        "lotus_performance_compute_queue_oldest_pending_age_seconds",
        "lotus_performance_compute_queue_oldest_leased_age_seconds",
        "lotus_performance_compute_queue_oldest_running_age_seconds",
        "lotus_performance_compute_queue_degradation_breach",
        "lotus_performance_lineage_queue_pending_payloads",
        "lotus_performance_lineage_queue_failure_pressure_payloads",
        "lotus_performance_lineage_queue_oldest_pending_age_seconds",
        "lotus_performance_lineage_queue_degradation_breach",
        "lotus_performance_lineage_storage_capacity_availability",
        "lotus_performance_lineage_storage_capacity_bytes",
        "lotus_performance_lineage_storage_free_ratio",
        "lotus_performance_lineage_storage_pressure_threshold",
        "lotus_performance_lineage_storage_pressure_breach",
        "lotus_performance_recovery_drill_availability",
        "lotus_performance_recovery_drill_action_availability",
        "lotus_performance_recovery_drill_active_actions",
        "lotus_performance_recovery_drill_oldest_active_action_age_seconds",
        "lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds",
        "lotus_performance_recovery_drill_reclaimed_actions",
        "lotus_performance_recovery_drill_latest_age_seconds",
        "lotus_performance_recovery_drill_policy_threshold",
        "lotus_performance_recovery_drill_degradation_breach",
        "lotus_performance_runtime_retention_availability",
        "lotus_performance_runtime_retention_action_availability",
        "lotus_performance_runtime_retention_active_actions",
        "lotus_performance_runtime_retention_oldest_active_action_age_seconds",
        "lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds",
        "lotus_performance_runtime_retention_reclaimed_actions",
        "lotus_performance_runtime_retention_latest_age_seconds",
        "lotus_performance_runtime_retention_policy_threshold",
        "lotus_performance_runtime_retention_degradation_breach",
        "lotus_performance_runtime_retention_preview_availability",
        "lotus_performance_runtime_retention_prunable_items",
    ]
    assert len(metric_names) == len(set(metric_names))

    label_names_by_metric = {metric.name: metric._labelnames for metric in metrics}
    assert label_names_by_metric["lotus_performance_durable_queue_store_availability"] == ("store",)
    assert label_names_by_metric["lotus_performance_compute_queue_jobs"] == ("status",)
    assert label_names_by_metric["lotus_performance_compute_queue_degradation_breach"] == ("reason",)
    assert label_names_by_metric["lotus_performance_lineage_storage_capacity_bytes"] == ("segment",)
    assert label_names_by_metric["lotus_performance_recovery_drill_policy_threshold"] == ("threshold",)
    assert label_names_by_metric["lotus_performance_runtime_retention_prunable_items"] == ("category",)
    assert label_names_by_metric["lotus_performance_runtime_retention_latest_age_seconds"] == ()


def test_load_durable_queue_metric_sources_captures_availability_and_action_paths(monkeypatch):
    lease_calls: list[dict[str, object]] = []
    monkeypatch.setattr("app.services.queue_metrics_service.compute_job_store.get_queue_stats", lambda: "compute")
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: "lineage",
    )
    monkeypatch.setattr("app.services.queue_metrics_service.get_lineage_storage_capacity", lambda: "capacity")
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: "recovery",
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_runtime_retention_history_snapshot",
        lambda limit=1: "retention",
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_operator_action_lease_snapshot",
        lambda **kwargs: lease_calls.append(kwargs) or {"status": "available", **kwargs},
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.run_runtime_retention_cleanup",
        lambda dry_run=True: {"dry_run": dry_run},
    )

    sources = _load_durable_queue_metric_sources(
        type(
            "Settings",
            (),
            {
                "RECOVERY_DRILL_ARTIFACT_PATH": Path("custom-recovery"),
                "RUNTIME_RETENTION_ARTIFACT_PATH": Path("custom-retention"),
            },
        )()
    )

    assert sources.compute_stats == "compute"
    assert sources.lineage_available is True
    assert sources.lineage_storage_capacity == "capacity"
    assert sources.recovery_drill_snapshot == "recovery"
    assert sources.runtime_retention_preview == {"dry_run": True}
    assert lease_calls == [
        {"artifact_directory": Path("custom-recovery"), "action_name": "recovery_drill"},
        {"artifact_directory": Path("custom-retention"), "action_name": "runtime_retention_cleanup"},
    ]


def test_core_queue_and_storage_metrics_emit_compute_lineage_and_storage_families():
    sources = _DurableQueueMetricSources(
        compute_stats=SimpleNamespace(
            pending_count=1,
            leased_count=2,
            running_count=3,
            failed_count=4,
            complete_count=5,
            retry_backlog_count=0,
            lease_expired_count=0,
            reclaimable_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
            oldest_running_age_seconds=0.0,
        ),
        compute_available=True,
        lineage_stats=SimpleNamespace(
            pending_payload_count=1,
            retry_backlog_count=0,
            reclaimable_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
        lineage_available=True,
        lineage_storage_capacity=SimpleNamespace(
            total_bytes=100,
            used_bytes=50,
            free_bytes=50,
            free_ratio=0.5,
        ),
        lineage_storage_capacity_available=True,
        recovery_drill_snapshot=None,
        recovery_drill_available=False,
        recovery_drill_action_snapshot=None,
        runtime_retention_snapshot=None,
        runtime_retention_available=False,
        runtime_retention_action_snapshot=None,
        runtime_retention_preview=None,
        runtime_retention_preview_available=False,
    )

    metrics = _core_queue_and_storage_metrics(
        sources=sources,
        compute_queue_policy=ComputeQueueDegradationPolicy(
            pending_age_seconds=10.0,
            leased_age_seconds=10.0,
            running_age_seconds=10.0,
            retry_backlog_count=1,
            lease_expiry_count=1,
            terminal_failure_count=1,
        ),
        lineage_queue_policy=LineageQueueDegradationPolicy(
            pending_age_seconds=10.0,
            leased_age_seconds=10.0,
            retry_backlog_count=1,
            terminal_failure_count=1,
            storage_min_free_bytes=1,
            storage_min_free_ratio=0.1,
        ),
    )

    metric_names = {metric.name for metric in metrics}
    assert "lotus_performance_compute_queue_jobs" in metric_names
    assert "lotus_performance_lineage_queue_pending_payloads" in metric_names
    assert "lotus_performance_lineage_storage_capacity_bytes" in metric_names
    assert "lotus_performance_lineage_storage_pressure_threshold" in metric_names


def test_availability_and_preview_metrics_preserve_order_and_preview_samples():
    metrics = _availability_and_preview_metrics(
        _DurableQueueMetricSources(
            compute_stats=None,
            compute_available=True,
            lineage_stats=None,
            lineage_available=False,
            lineage_storage_capacity=None,
            lineage_storage_capacity_available=False,
            recovery_drill_snapshot=type("RecoverySnapshot", (), {"status": "available"})(),
            recovery_drill_available=True,
            recovery_drill_action_snapshot=None,
            runtime_retention_snapshot=type("RuntimeRetentionSnapshot", (), {"status": "available"})(),
            runtime_retention_available=True,
            runtime_retention_action_snapshot=None,
            runtime_retention_preview=type(
                "RuntimeRetentionPreview",
                (),
                {
                    "prunable_execution_count": 4,
                    "prunable_compute_job_count": 3,
                    "prunable_async_result_count": 2,
                    "prunable_lineage_record_count": 1,
                    "prunable_lineage_artifact_count": 1,
                },
            )(),
            runtime_retention_preview_available=True,
        )
    )

    metric_names = [metric.name for metric in metrics]
    assert metric_names[:3] == [
        "lotus_performance_durable_queue_store_availability",
        "lotus_performance_lineage_storage_capacity_availability",
        "lotus_performance_recovery_drill_availability",
    ]
    assert metric_names[-1] == "lotus_performance_runtime_retention_prunable_items"
    availability_samples = {(sample.labels["store"], sample.value) for sample in metrics[0].samples}
    assert availability_samples == {("compute", 1), ("lineage", 0)}
    prunable_samples = {sample.labels["category"]: sample.value for sample in metrics[-1].samples}
    assert prunable_samples["execution"] == 4
    assert prunable_samples["compute_job"] == 3


def test_lifecycle_history_metrics_emit_policy_and_latest_history_metrics(monkeypatch):
    monkeypatch.setattr("app.services.queue_metrics_service.age_seconds_since", lambda timestamp_utc: 120.0)
    sources = _DurableQueueMetricSources(
        compute_stats=None,
        compute_available=True,
        lineage_stats=None,
        lineage_available=True,
        lineage_storage_capacity=None,
        lineage_storage_capacity_available=True,
        recovery_drill_snapshot=SimpleNamespace(
            status="available",
            entries=(SimpleNamespace(generated_at_utc="2026-03-15T00:00:00Z", status="passed"),),
        ),
        recovery_drill_available=True,
        recovery_drill_action_snapshot=SimpleNamespace(
            status="available",
            active_leases=(),
            latest_reclaimed_lease=None,
        ),
        runtime_retention_snapshot=SimpleNamespace(
            status="available",
            entries=(SimpleNamespace(generated_at_utc="2026-03-15T00:00:00Z", cleanup_mode="apply"),),
        ),
        runtime_retention_available=True,
        runtime_retention_action_snapshot=SimpleNamespace(
            status="available",
            active_leases=(),
            latest_reclaimed_lease=None,
        ),
        runtime_retention_preview=None,
        runtime_retention_preview_available=False,
    )

    metrics = _lifecycle_history_metrics(
        sources=sources,
        recovery_drill_policy=RecoveryDrillDegradationPolicy(
            max_age_seconds=3600.0,
            active_run_age_seconds=1800.0,
            reclaim_count=2,
        ),
        runtime_retention_policy=RuntimeRetentionDegradationPolicy(
            max_age_seconds=7200.0,
            active_run_age_seconds=2400.0,
            reclaim_count=3,
        ),
    )

    metric_names = {metric.name for metric in metrics}
    assert "lotus_performance_recovery_drill_policy_threshold" in metric_names
    assert "lotus_performance_recovery_drill_active_actions" in metric_names
    assert "lotus_performance_recovery_drill_latest_age_seconds" in metric_names
    assert "lotus_performance_recovery_drill_degradation_breach" in metric_names
    assert "lotus_performance_runtime_retention_policy_threshold" in metric_names
    assert "lotus_performance_runtime_retention_active_actions" in metric_names
    assert "lotus_performance_runtime_retention_latest_age_seconds" in metric_names
    assert "lotus_performance_runtime_retention_degradation_breach" in metric_names


def test_lifecycle_history_metrics_omit_latest_history_metrics_when_snapshots_unavailable():
    sources = _DurableQueueMetricSources(
        compute_stats=None,
        compute_available=True,
        lineage_stats=None,
        lineage_available=True,
        lineage_storage_capacity=None,
        lineage_storage_capacity_available=True,
        recovery_drill_snapshot=SimpleNamespace(status="unavailable", entries=()),
        recovery_drill_available=False,
        recovery_drill_action_snapshot=None,
        runtime_retention_snapshot=None,
        runtime_retention_available=False,
        runtime_retention_action_snapshot=None,
        runtime_retention_preview=None,
        runtime_retention_preview_available=False,
    )

    metrics = _lifecycle_history_metrics(
        sources=sources,
        recovery_drill_policy=RecoveryDrillDegradationPolicy(
            max_age_seconds=3600.0,
            active_run_age_seconds=1800.0,
            reclaim_count=2,
        ),
        runtime_retention_policy=RuntimeRetentionDegradationPolicy(
            max_age_seconds=7200.0,
            active_run_age_seconds=2400.0,
            reclaim_count=3,
        ),
    )

    metric_names = {metric.name for metric in metrics}
    assert "lotus_performance_recovery_drill_policy_threshold" in metric_names
    assert "lotus_performance_runtime_retention_policy_threshold" in metric_names
    assert "lotus_performance_recovery_drill_latest_age_seconds" not in metric_names
    assert "lotus_performance_recovery_drill_degradation_breach" not in metric_names
    assert "lotus_performance_runtime_retention_latest_age_seconds" not in metric_names
    assert "lotus_performance_runtime_retention_degradation_breach" not in metric_names


def test_queue_metrics_collector_emits_compute_and_lineage_metrics(monkeypatch):
    class _ComputeStats:
        pending_count = 2
        leased_count = 1
        running_count = 3
        failed_count = 4
        complete_count = 5
        retry_backlog_count = 6
        lease_expired_count = 7
        reclaimable_count = 2
        terminal_failure_count = 8
        oldest_pending_age_seconds = 12.5
        oldest_leased_age_seconds = 6.25
        oldest_running_age_seconds = 3.5

    class _LineageStats:
        pending_payload_count = 6
        leased_payload_count = 1
        retry_backlog_count = 2
        reclaimable_count = 1
        terminal_failure_count = 1
        oldest_pending_age_seconds = 7.5
        oldest_leased_age_seconds = 4.0

    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: _ComputeStats(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: _LineageStats(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 650,
                "free_bytes": 350,
                "free_ratio": 0.35,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 30.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 5.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 10,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 10,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 10,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 10,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 10,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 200,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.25,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 3600.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 1800.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 2,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 3600.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 1800.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 3,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: type(
            "RecoverySnapshot",
            (),
            {
                "status": "available",
                "entries": [
                    type(
                        "RecoveryEntry",
                        (),
                        {
                            "generated_at_utc": "2099-01-01T00:00:00Z",
                            "status": "passed",
                        },
                    )()
                ],
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_operator_action_lease_snapshot",
        lambda **kwargs: type(
            "LeaseSnapshot",
            (),
            {
                "status": "available",
                "active_leases": (),
                "latest_reclaimed_lease": None,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_runtime_retention_history_snapshot",
        lambda limit=1: type(
            "RuntimeRetentionSnapshot",
            (),
            {
                "status": "available",
                "entries": [
                    type(
                        "RuntimeRetentionEntry",
                        (),
                        {
                            "generated_at_utc": "2099-01-01T00:00:00Z",
                            "cleanup_mode": "apply",
                        },
                    )()
                ],
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.run_runtime_retention_cleanup",
        lambda dry_run=True: type(
            "RuntimeRetentionPreview",
            (),
            {
                "prunable_execution_count": 4,
                "prunable_compute_job_count": 3,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 1,
                "prunable_lineage_artifact_count": 1,
            },
        )(),
    )
    metrics = list(DurableQueueCollector().collect())
    metric_names = {metric.name for metric in metrics}

    assert "lotus_performance_durable_queue_store_availability" in metric_names
    assert "lotus_performance_compute_queue_jobs" in metric_names
    assert "lotus_performance_compute_queue_failure_pressure_jobs" in metric_names
    assert "lotus_performance_compute_queue_oldest_pending_age_seconds" in metric_names
    assert "lotus_performance_compute_queue_oldest_leased_age_seconds" in metric_names
    assert "lotus_performance_compute_queue_oldest_running_age_seconds" in metric_names
    assert "lotus_performance_compute_queue_degradation_breach" in metric_names
    assert "lotus_performance_lineage_queue_pending_payloads" in metric_names
    assert "lotus_performance_lineage_queue_failure_pressure_payloads" in metric_names
    assert "lotus_performance_lineage_queue_oldest_pending_age_seconds" in metric_names
    assert "lotus_performance_lineage_queue_degradation_breach" in metric_names
    assert "lotus_performance_lineage_storage_capacity_availability" in metric_names
    assert "lotus_performance_lineage_storage_capacity_bytes" in metric_names
    assert "lotus_performance_lineage_storage_free_ratio" in metric_names
    assert "lotus_performance_lineage_storage_pressure_threshold" in metric_names
    assert "lotus_performance_lineage_storage_pressure_breach" in metric_names
    assert "lotus_performance_recovery_drill_availability" in metric_names
    assert "lotus_performance_recovery_drill_action_availability" in metric_names
    assert "lotus_performance_recovery_drill_active_actions" in metric_names
    assert "lotus_performance_recovery_drill_latest_age_seconds" in metric_names
    assert "lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds" not in metric_names
    assert "lotus_performance_recovery_drill_reclaimed_actions" not in metric_names
    assert "lotus_performance_recovery_drill_policy_threshold" in metric_names
    assert "lotus_performance_recovery_drill_degradation_breach" in metric_names
    assert "lotus_performance_runtime_retention_availability" in metric_names
    assert "lotus_performance_runtime_retention_action_availability" in metric_names
    assert "lotus_performance_runtime_retention_active_actions" in metric_names
    assert "lotus_performance_runtime_retention_latest_age_seconds" in metric_names
    assert "lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds" not in metric_names
    assert "lotus_performance_runtime_retention_reclaimed_actions" not in metric_names
    assert "lotus_performance_runtime_retention_policy_threshold" in metric_names
    assert "lotus_performance_runtime_retention_degradation_breach" in metric_names
    assert "lotus_performance_runtime_retention_preview_availability" in metric_names
    assert "lotus_performance_runtime_retention_prunable_items" in metric_names

    compute_breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_compute_queue_degradation_breach"
    )
    compute_breach_samples = {sample.labels["reason"]: sample.value for sample in compute_breach_metric.samples}
    assert compute_breach_samples["compute_pending_age_exceeded"] == 0
    assert compute_breach_samples["compute_leased_age_exceeded"] == 0
    assert compute_breach_samples["compute_running_age_exceeded"] == 0

    lineage_breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_lineage_queue_degradation_breach"
    )
    lineage_breach_samples = {sample.labels["reason"]: sample.value for sample in lineage_breach_metric.samples}
    assert lineage_breach_samples["lineage_pending_age_exceeded"] == 0
    assert lineage_breach_samples["lineage_leased_age_exceeded"] == 0

    breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_lineage_storage_pressure_breach"
    )
    breach_samples = {sample.labels["reason"]: sample.value for sample in breach_metric.samples}
    assert breach_samples["lineage_storage_free_bytes_below_threshold"] == 0
    assert breach_samples["lineage_storage_free_ratio_below_threshold"] == 0

    recovery_breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_degradation_breach"
    )
    recovery_breach_samples = {sample.labels["reason"]: sample.value for sample in recovery_breach_metric.samples}
    assert recovery_breach_samples["recovery_drill_latest_not_passed"] == 0
    assert recovery_breach_samples["recovery_drill_age_exceeded"] == 0
    assert recovery_breach_samples["recovery_drill_active_run_age_exceeded"] == 0
    assert recovery_breach_samples["recovery_drill_reclaim_pressure_exceeded"] == 0

    recovery_threshold_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_policy_threshold"
    )
    recovery_threshold_samples = {
        sample.labels["threshold"]: sample.value for sample in recovery_threshold_metric.samples
    }
    assert recovery_threshold_samples["active_run_age_seconds"] == 1800
    assert recovery_threshold_samples["reclaim_count"] == 2
    runtime_threshold_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_runtime_retention_policy_threshold"
    )
    runtime_threshold_samples = {
        sample.labels["threshold"]: sample.value for sample in runtime_threshold_metric.samples
    }
    assert runtime_threshold_samples["active_run_age_seconds"] == 1800
    assert runtime_threshold_samples["reclaim_count"] == 3


def test_queue_metrics_collector_exposes_store_unavailability_without_false_zero_backlog(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("compute unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("lineage unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: (_ for _ in ()).throw(RuntimeError("recovery unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_operator_action_lease_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("lease unavailable")),
    )

    metrics = list(DurableQueueCollector().collect())
    metric_names = {metric.name for metric in metrics}

    assert "lotus_performance_durable_queue_store_availability" in metric_names
    assert "lotus_performance_lineage_storage_capacity_availability" in metric_names
    assert "lotus_performance_lineage_storage_pressure_threshold" in metric_names
    assert "lotus_performance_recovery_drill_availability" in metric_names
    assert "lotus_performance_recovery_drill_action_availability" in metric_names
    assert "lotus_performance_recovery_drill_policy_threshold" in metric_names
    assert "lotus_performance_runtime_retention_action_availability" in metric_names
    assert "lotus_performance_compute_queue_jobs" not in metric_names
    assert "lotus_performance_lineage_queue_pending_payloads" not in metric_names
    assert "lotus_performance_compute_queue_degradation_breach" not in metric_names
    assert "lotus_performance_lineage_queue_degradation_breach" not in metric_names
    assert "lotus_performance_lineage_storage_capacity_bytes" not in metric_names
    assert "lotus_performance_lineage_storage_free_ratio" not in metric_names
    assert "lotus_performance_lineage_storage_pressure_breach" not in metric_names
    assert "lotus_performance_recovery_drill_latest_age_seconds" not in metric_names
    assert "lotus_performance_recovery_drill_degradation_breach" not in metric_names
    assert "lotus_performance_recovery_drill_active_actions" not in metric_names
    assert "lotus_performance_runtime_retention_active_actions" not in metric_names

    availability_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_durable_queue_store_availability"
    )
    samples = {(sample.labels["store"], sample.value) for sample in availability_metric.samples}
    assert ("compute", 0) in samples
    assert ("lineage", 0) in samples

    storage_availability_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_lineage_storage_capacity_availability"
    )
    assert storage_availability_metric.samples[0].value == 0

    recovery_availability_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_availability"
    )
    assert recovery_availability_metric.samples[0].value == 0
    recovery_action_availability_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_action_availability"
    )
    assert recovery_action_availability_metric.samples[0].value == 0
    runtime_retention_action_availability_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_runtime_retention_action_availability"
    )
    assert runtime_retention_action_availability_metric.samples[0].value == 0


def test_queue_metrics_collector_emits_governed_action_reclaim_pressure_breaches(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: type(
            "ComputeStats",
            (),
            {
                "pending_count": 0,
                "leased_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "complete_count": 0,
                "retry_backlog_count": 0,
                "lease_expired_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
                "oldest_running_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: type(
            "LineageStats",
            (),
            {
                "pending_payload_count": 0,
                "leased_payload_count": 0,
                "retry_backlog_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: type("Capacity", (), {"total_bytes": 1000, "used_bytes": 600, "free_bytes": 400, "free_ratio": 0.4})(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 60.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 2,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 120.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 3,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: type(
            "RecoverySnapshot",
            (),
            {
                "status": "available",
                "entries": [type("Entry", (), {"generated_at_utc": "2099-01-01T00:00:00Z", "status": "passed"})()],
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_runtime_retention_history_snapshot",
        lambda limit=1: type(
            "RuntimeRetentionSnapshot",
            (),
            {
                "status": "available",
                "entries": [type("Entry", (), {"generated_at_utc": "2099-01-01T00:00:00Z", "cleanup_mode": "apply"})()],
            },
        )(),
    )
    action_snapshots = iter(
        [
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-03-14T00:00:00Z"})(),),
                    "latest_reclaimed_lease": type(
                        "Reclaim", (), {"reclaimed_at_utc": "2099-01-01T00:00:00Z", "reclaim_count": 2}
                    )(),
                },
            )(),
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-03-14T00:00:00Z"})(),),
                    "latest_reclaimed_lease": type(
                        "Reclaim", (), {"reclaimed_at_utc": "2099-01-01T00:00:00Z", "reclaim_count": 3}
                    )(),
                },
            )(),
        ]
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_operator_action_lease_snapshot",
        lambda **kwargs: next(action_snapshots),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.run_runtime_retention_cleanup",
        lambda dry_run=True: type(
            "RuntimeRetentionPreview",
            (),
            {
                "prunable_execution_count": 0,
                "prunable_compute_job_count": 0,
                "prunable_async_result_count": 0,
                "prunable_lineage_record_count": 0,
                "prunable_lineage_artifact_count": 0,
            },
        )(),
    )
    metrics = list(DurableQueueCollector().collect())

    recovery_breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_degradation_breach"
    )
    recovery_breach_samples = {sample.labels["reason"]: sample.value for sample in recovery_breach_metric.samples}
    assert recovery_breach_samples["recovery_drill_active_run_age_exceeded"] == 1
    assert recovery_breach_samples["recovery_drill_reclaim_pressure_exceeded"] == 1

    retention_breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_runtime_retention_degradation_breach"
    )
    retention_breach_samples = {sample.labels["reason"]: sample.value for sample in retention_breach_metric.samples}
    assert retention_breach_samples["runtime_retention_active_run_age_exceeded"] == 1
    assert retention_breach_samples["runtime_retention_reclaim_pressure_exceeded"] == 1


def test_queue_metrics_collector_emits_governed_action_lease_metrics(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: type(
            "ComputeStats",
            (),
            {
                "pending_count": 0,
                "leased_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "complete_count": 0,
                "retry_backlog_count": 0,
                "lease_expired_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
                "oldest_running_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: type(
            "LineageStats",
            (),
            {
                "pending_payload_count": 0,
                "leased_payload_count": 0,
                "retry_backlog_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 600,
                "free_bytes": 400,
                "free_ratio": 0.4,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: type("RecoverySnapshot", (), {"status": "available", "entries": []})(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_runtime_retention_history_snapshot",
        lambda limit=1: type("RuntimeRetentionSnapshot", (), {"status": "available", "entries": []})(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.run_runtime_retention_cleanup",
        lambda dry_run=True: type(
            "RuntimeRetentionPreview",
            (),
            {
                "prunable_execution_count": 0,
                "prunable_compute_job_count": 0,
                "prunable_async_result_count": 0,
                "prunable_lineage_record_count": 0,
                "prunable_lineage_artifact_count": 0,
            },
        )(),
    )
    lease_snapshots = iter(
        (
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-03-14T00:00:00Z"})(),),
                    "latest_reclaimed_lease": type(
                        "Reclaim",
                        (),
                        {"reclaimed_at_utc": "2026-03-14T00:30:00Z", "reclaim_count": 3},
                    )(),
                },
            )(),
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "active_leases": (
                        type("Lease", (), {"acquired_at_utc": "2026-03-14T00:00:00Z"})(),
                        type("Lease", (), {"acquired_at_utc": "2026-03-14T01:00:00Z"})(),
                    ),
                    "latest_reclaimed_lease": type(
                        "Reclaim",
                        (),
                        {"reclaimed_at_utc": "2026-03-14T01:30:00Z", "reclaim_count": 4},
                    )(),
                },
            )(),
        )
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_operator_action_lease_snapshot",
        lambda **kwargs: next(lease_snapshots),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    monkeypatch.setattr("app.services.queue_metric_builders.age_seconds_since", lambda timestamp_utc: 42.0)

    metrics = list(DurableQueueCollector().collect())

    recovery_actions = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_active_actions"
    )
    assert recovery_actions.samples[0].value == 1
    recovery_reclaimed = next(
        metric
        for metric in metrics
        if metric.name == "lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds"
    )
    assert recovery_reclaimed.samples[0].value == 42
    recovery_reclaimed_count = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_reclaimed_actions"
    )
    assert recovery_reclaimed_count.samples[0].value == 3
    runtime_retention_actions = next(
        metric for metric in metrics if metric.name == "lotus_performance_runtime_retention_active_actions"
    )
    assert runtime_retention_actions.samples[0].value == 2
    runtime_retention_reclaimed = next(
        metric
        for metric in metrics
        if metric.name == "lotus_performance_runtime_retention_latest_reclaimed_action_age_seconds"
    )
    assert runtime_retention_reclaimed.samples[0].value == 42
    runtime_retention_reclaimed_count = next(
        metric for metric in metrics if metric.name == "lotus_performance_runtime_retention_reclaimed_actions"
    )
    assert runtime_retention_reclaimed_count.samples[0].value == 4


def test_queue_metrics_collector_emits_lineage_storage_breach_state(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: type(
            "ComputeStats",
            (),
            {
                "pending_count": 0,
                "leased_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "complete_count": 0,
                "retry_backlog_count": 0,
                "lease_expired_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
                "oldest_running_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: type(
            "LineageStats",
            (),
            {
                "pending_payload_count": 0,
                "retry_backlog_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 900,
                "free_bytes": 100,
                "free_ratio": 0.1,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 250,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.2,
            },
        )(),
    )

    metrics = list(DurableQueueCollector().collect())

    breach_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_lineage_storage_pressure_breach"
    )
    breach_samples = {sample.labels["reason"]: sample.value for sample in breach_metric.samples}
    assert breach_samples["lineage_storage_free_bytes_below_threshold"] == 1
    assert breach_samples["lineage_storage_free_ratio_below_threshold"] == 1


def test_queue_metrics_collector_emits_queue_policy_breach_state(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: type(
            "ComputeStats",
            (),
            {
                "pending_count": 0,
                "leased_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "complete_count": 0,
                "retry_backlog_count": 2,
                "lease_expired_count": 1,
                "reclaimable_count": 0,
                "terminal_failure_count": 1,
                "oldest_pending_age_seconds": 40.0,
                "oldest_leased_age_seconds": 20.0,
                "oldest_running_age_seconds": 8.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: type(
            "LineageStats",
            (),
            {
                "pending_payload_count": 0,
                "retry_backlog_count": 2,
                "reclaimable_count": 0,
                "terminal_failure_count": 1,
                "oldest_pending_age_seconds": 25.0,
                "oldest_leased_age_seconds": 15.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 600,
                "free_bytes": 400,
                "free_ratio": 0.4,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 30.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 5.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 2,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 20.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 2,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
            },
        )(),
    )

    metrics = list(DurableQueueCollector().collect())

    compute_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_compute_queue_degradation_breach"
    )
    compute_samples = {sample.labels["reason"]: sample.value for sample in compute_metric.samples}
    assert compute_samples["compute_retry_backlog_exceeded"] == 1
    assert compute_samples["compute_lease_expiry_pressure_exceeded"] == 1
    assert compute_samples["compute_terminal_failure_exceeded"] == 1
    assert compute_samples["compute_pending_age_exceeded"] == 1
    assert compute_samples["compute_leased_age_exceeded"] == 1
    assert compute_samples["compute_running_age_exceeded"] == 1

    lineage_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_lineage_queue_degradation_breach"
    )
    lineage_samples = {sample.labels["reason"]: sample.value for sample in lineage_metric.samples}
    assert lineage_samples["lineage_retry_backlog_exceeded"] == 1
    assert lineage_samples["lineage_terminal_failure_exceeded"] == 1
    assert lineage_samples["lineage_pending_age_exceeded"] == 1
    assert lineage_samples["lineage_leased_age_exceeded"] == 1


def test_queue_metrics_collector_emits_recovery_drill_breach_state(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: type(
            "ComputeStats",
            (),
            {
                "pending_count": 0,
                "leased_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "complete_count": 0,
                "retry_backlog_count": 0,
                "lease_expired_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
                "oldest_running_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: type(
            "LineageStats",
            (),
            {
                "pending_payload_count": 0,
                "retry_backlog_count": 0,
                "reclaimable_count": 0,
                "terminal_failure_count": 0,
                "oldest_pending_age_seconds": 0.0,
                "oldest_leased_age_seconds": 0.0,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 400,
                "free_bytes": 600,
                "free_ratio": 0.6,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: type(
            "RecoverySnapshot",
            (),
            {
                "status": "available",
                "entries": [
                    type(
                        "RecoveryEntry",
                        (),
                        {
                            "generated_at_utc": "2026-03-13T00:00:00Z",
                            "status": "failed",
                        },
                    )()
                ],
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 60.0,
            },
        )(),
    )

    metrics = list(DurableQueueCollector().collect())

    recovery_metric = next(
        metric for metric in metrics if metric.name == "lotus_performance_recovery_drill_degradation_breach"
    )
    recovery_samples = {sample.labels["reason"]: sample.value for sample in recovery_metric.samples}
    assert recovery_samples["recovery_drill_latest_not_passed"] == 1
    assert recovery_samples["recovery_drill_age_exceeded"] == 1


def test_queue_metrics_collector_exposes_runtime_retention_unavailability_without_false_breach(monkeypatch):
    monkeypatch.setattr(
        "app.services.queue_metrics_service.compute_job_store.get_queue_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("compute unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.lineage_metadata_store.get_pending_payload_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("lineage unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_lineage_storage_capacity",
        lambda: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_recovery_drill_history_snapshot",
        lambda limit=1: type("RecoverySnapshot", (), {"status": "unavailable", "entries": []})(),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.build_runtime_retention_history_snapshot",
        lambda limit=1: (_ for _ in ()).throw(RuntimeError("retention unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.run_runtime_retention_cleanup",
        lambda dry_run=True: (_ for _ in ()).throw(RuntimeError("preview unavailable")),
    )
    monkeypatch.setattr(
        "app.services.queue_metrics_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 3600.0,
            },
        )(),
    )

    metrics = list(DurableQueueCollector().collect())
    metric_names = {metric.name for metric in metrics}

    assert "lotus_performance_runtime_retention_availability" in metric_names
    assert "lotus_performance_runtime_retention_policy_threshold" in metric_names
    assert "lotus_performance_runtime_retention_preview_availability" in metric_names
    assert "lotus_performance_runtime_retention_latest_age_seconds" not in metric_names
    assert "lotus_performance_runtime_retention_degradation_breach" not in metric_names
    assert "lotus_performance_runtime_retention_prunable_items" not in metric_names
