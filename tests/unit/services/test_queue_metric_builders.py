from app.services.queue_metric_builders import (
    RECOVERY_DRILL_ACTION_METRICS,
    active_lease_age_seconds_or_zero,
    availability_metric,
    compute_queue_degradation_breach_metric,
    compute_queue_failure_pressure_metric,
    compute_queue_job_count_metric,
    compute_queue_oldest_age_metrics,
    labeled_metric,
    latest_reclaim_count_or_zero,
    lineage_queue_degradation_breach_metric,
    lineage_queue_payload_metrics,
    lineage_storage_pressure_breach_metric,
    operator_action_lease_metrics,
    policy_threshold_metric,
    reason_labeled_metric,
    recovery_drill_degradation_breach_metric,
    recovery_drill_latest_age_metric,
    runtime_retention_degradation_breach_metric,
    runtime_retention_latest_age_metric,
    runtime_retention_prunable_items_metric,
    single_sample_metric,
    snapshot_available,
)
from app.services.runtime_status_domain import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RecoveryDrillDegradationPolicy,
    RuntimeRetentionDegradationPolicy,
)


def test_availability_metric_emits_unlabelled_binary_sample():
    available = availability_metric(metric_name="available_metric", description="availability", is_available=True)
    unavailable = availability_metric(metric_name="unavailable_metric", description="availability", is_available=False)

    assert available.samples[0].value == 1
    assert unavailable.samples[0].value == 0


def test_single_sample_metric_emits_unlabelled_value():
    metric = single_sample_metric(metric_name="single_sample", description="single sample", value=123.4)

    assert metric.samples[0].labels == {}
    assert metric.samples[0].value == 123.4


def test_snapshot_available_requires_available_status():
    assert snapshot_available(type("Snapshot", (), {"status": "available"})()) is True
    assert snapshot_available(type("Snapshot", (), {"status": "unavailable"})()) is False
    assert snapshot_available(None) is False


def test_policy_threshold_metric_uses_governed_threshold_labels():
    metric = policy_threshold_metric(
        metric_name="policy_threshold",
        description="policy thresholds",
        max_age_seconds=3600.0,
        active_run_age_seconds=1800.0,
        reclaim_count=3,
    )

    samples = {sample.labels["threshold"]: sample.value for sample in metric.samples}
    assert samples == {
        "max_age_seconds": 3600.0,
        "active_run_age_seconds": 1800.0,
        "reclaim_count": 3,
    }


def test_labeled_metric_uses_supplied_label_name_and_values():
    metric = labeled_metric(
        metric_name="category_metric",
        description="category metric",
        label_name="category",
        samples=(("retry_backlog", 2), ("terminal_failure", 1)),
    )

    samples = {sample.labels["category"]: sample.value for sample in metric.samples}
    assert samples == {
        "retry_backlog": 2,
        "terminal_failure": 1,
    }


def test_reason_labeled_metric_uses_governed_reason_labels():
    metric = reason_labeled_metric(
        metric_name="degradation_breach",
        description="degradation breach",
        samples=(
            ("age_exceeded", 1),
            ("retry_backlog_exceeded", 0),
        ),
    )

    samples = {sample.labels["reason"]: sample.value for sample in metric.samples}
    assert samples == {
        "age_exceeded": 1,
        "retry_backlog_exceeded": 0,
    }


def test_compute_queue_job_count_metric_uses_governed_status_labels():
    stats = type(
        "ComputeStats",
        (),
        {
            "pending_count": 2,
            "leased_count": 1,
            "running_count": 3,
            "failed_count": 4,
            "complete_count": 5,
        },
    )()

    metric = compute_queue_job_count_metric(stats=stats)

    samples = {sample.labels["status"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_compute_queue_jobs"
    assert samples == {
        "pending": 2,
        "leased": 1,
        "running": 3,
        "failed": 4,
        "complete": 5,
    }


def test_compute_queue_failure_pressure_metric_uses_governed_category_labels():
    stats = type(
        "ComputeStats",
        (),
        {
            "retry_backlog_count": 6,
            "lease_expired_count": 7,
            "reclaimable_count": 2,
            "terminal_failure_count": 8,
        },
    )()

    metric = compute_queue_failure_pressure_metric(stats=stats)

    samples = {sample.labels["category"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_compute_queue_failure_pressure_jobs"
    assert samples == {
        "retry_backlog": 6,
        "lease_expired": 7,
        "reclaimable": 2,
        "terminal_failure": 8,
    }


def test_compute_queue_oldest_age_metrics_preserve_metric_contracts():
    stats = type(
        "ComputeStats",
        (),
        {
            "oldest_pending_age_seconds": 12.5,
            "oldest_leased_age_seconds": 6.25,
            "oldest_running_age_seconds": 3.5,
        },
    )()

    metrics = compute_queue_oldest_age_metrics(stats=stats)
    samples = {metric.name: metric.samples[0].value for metric in metrics}

    assert samples == {
        "lotus_performance_compute_queue_oldest_pending_age_seconds": 12.5,
        "lotus_performance_compute_queue_oldest_leased_age_seconds": 6.25,
        "lotus_performance_compute_queue_oldest_running_age_seconds": 3.5,
    }


def test_compute_queue_degradation_breach_metric_uses_policy_thresholds():
    stats = type(
        "ComputeStats",
        (),
        {
            "retry_backlog_count": 3,
            "terminal_failure_count": 2,
            "lease_expired_count": 2,
            "oldest_pending_age_seconds": 45.0,
            "oldest_leased_age_seconds": 20.0,
            "oldest_running_age_seconds": 15.0,
        },
    )()
    policy = ComputeQueueDegradationPolicy(
        retry_backlog_count=2,
        terminal_failure_count=1,
        lease_expiry_count=1,
        pending_age_seconds=30.0,
        leased_age_seconds=10.0,
        running_age_seconds=10.0,
    )

    metric = compute_queue_degradation_breach_metric(stats=stats, policy=policy)

    samples = {sample.labels["reason"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_compute_queue_degradation_breach"
    assert samples == {
        "compute_retry_backlog_exceeded": 1,
        "compute_terminal_failure_exceeded": 1,
        "compute_lease_expiry_pressure_exceeded": 1,
        "compute_pending_age_exceeded": 1,
        "compute_leased_age_exceeded": 1,
        "compute_running_age_exceeded": 1,
    }


def test_lineage_queue_degradation_breach_metric_uses_policy_thresholds():
    stats = type(
        "LineageStats",
        (),
        {
            "retry_backlog_count": 3,
            "terminal_failure_count": 2,
            "oldest_pending_age_seconds": 45.0,
            "oldest_leased_age_seconds": 20.0,
        },
    )()
    policy = LineageQueueDegradationPolicy(
        retry_backlog_count=2,
        terminal_failure_count=1,
        pending_age_seconds=30.0,
        leased_age_seconds=10.0,
        storage_min_free_bytes=100,
        storage_min_free_ratio=0.2,
    )

    metric = lineage_queue_degradation_breach_metric(stats=stats, policy=policy)

    samples = {sample.labels["reason"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_lineage_queue_degradation_breach"
    assert samples == {
        "lineage_retry_backlog_exceeded": 1,
        "lineage_terminal_failure_exceeded": 1,
        "lineage_pending_age_exceeded": 1,
        "lineage_leased_age_exceeded": 1,
    }


def test_lineage_queue_payload_metrics_preserve_metric_contracts():
    stats = type(
        "LineageStats",
        (),
        {
            "pending_payload_count": 6,
            "retry_backlog_count": 2,
            "reclaimable_count": 1,
            "terminal_failure_count": 1,
            "oldest_pending_age_seconds": 7.5,
        },
    )()

    metrics = lineage_queue_payload_metrics(stats=stats)
    metric_samples = {metric.name: metric.samples for metric in metrics}

    assert metric_samples["lotus_performance_lineage_queue_pending_payloads"][0].value == 6
    failure_samples = {
        sample.labels["category"]: sample.value
        for sample in metric_samples["lotus_performance_lineage_queue_failure_pressure_payloads"]
    }
    assert failure_samples == {
        "retry_backlog": 2,
        "reclaimable": 1,
        "terminal_failure": 1,
    }
    assert metric_samples["lotus_performance_lineage_queue_oldest_pending_age_seconds"][0].value == 7.5


def test_lineage_storage_pressure_breach_metric_uses_policy_thresholds():
    capacity = type(
        "Capacity",
        (),
        {
            "free_bytes": 100,
            "free_ratio": 0.1,
        },
    )()
    policy = LineageQueueDegradationPolicy(
        retry_backlog_count=2,
        terminal_failure_count=1,
        pending_age_seconds=30.0,
        leased_age_seconds=10.0,
        storage_min_free_bytes=250,
        storage_min_free_ratio=0.2,
    )

    metric = lineage_storage_pressure_breach_metric(capacity=capacity, policy=policy)

    samples = {sample.labels["reason"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_lineage_storage_pressure_breach"
    assert samples == {
        "lineage_storage_free_bytes_below_threshold": 1,
        "lineage_storage_free_ratio_below_threshold": 1,
    }


def test_recovery_drill_degradation_breach_metric_uses_latest_history_and_action_policy(monkeypatch):
    monkeypatch.setattr("app.services.queue_metric_builders.age_seconds_since", lambda timestamp_utc: 120.0)
    latest = type("RecoveryEntry", (), {"status": "failed"})()
    action_snapshot = type(
        "ActionSnapshot",
        (),
        {
            "status": "available",
            "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-05-31T10:00:00Z"})(),),
            "latest_reclaimed_lease": type("Reclaim", (), {"reclaim_count": 2})(),
        },
    )()
    policy = RecoveryDrillDegradationPolicy(
        max_age_seconds=60.0,
        active_run_age_seconds=30.0,
        reclaim_count=1,
    )

    metric = recovery_drill_degradation_breach_metric(
        latest=latest,
        latest_age_seconds=120.0,
        action_snapshot=action_snapshot,
        policy=policy,
    )

    samples = {sample.labels["reason"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_recovery_drill_degradation_breach"
    assert samples == {
        "recovery_drill_latest_not_passed": 1,
        "recovery_drill_age_exceeded": 1,
        "recovery_drill_active_run_age_exceeded": 1,
        "recovery_drill_reclaim_pressure_exceeded": 1,
    }


def test_runtime_retention_degradation_breach_metric_uses_latest_history_and_action_policy(monkeypatch):
    monkeypatch.setattr("app.services.queue_metric_builders.age_seconds_since", lambda timestamp_utc: 240.0)
    latest = type("RuntimeRetentionEntry", (), {"cleanup_mode": "dry_run"})()
    action_snapshot = type(
        "ActionSnapshot",
        (),
        {
            "status": "available",
            "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-05-31T10:00:00Z"})(),),
            "latest_reclaimed_lease": type("Reclaim", (), {"reclaim_count": 2})(),
        },
    )()
    policy = RuntimeRetentionDegradationPolicy(
        max_age_seconds=60.0,
        active_run_age_seconds=30.0,
        reclaim_count=1,
    )

    metric = runtime_retention_degradation_breach_metric(
        latest=latest,
        latest_age_seconds=240.0,
        action_snapshot=action_snapshot,
        policy=policy,
    )

    samples = {sample.labels["reason"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_runtime_retention_degradation_breach"
    assert samples == {
        "runtime_retention_latest_not_applied": 1,
        "runtime_retention_age_exceeded": 1,
        "runtime_retention_active_run_age_exceeded": 1,
        "runtime_retention_reclaim_pressure_exceeded": 1,
    }


def test_lifecycle_latest_age_metrics_preserve_metric_contracts():
    recovery_metric = recovery_drill_latest_age_metric(latest_age_seconds=120.0)
    retention_metric = runtime_retention_latest_age_metric(latest_age_seconds=240.0)

    assert recovery_metric.name == "lotus_performance_recovery_drill_latest_age_seconds"
    assert recovery_metric.samples[0].value == 120.0
    assert retention_metric.name == "lotus_performance_runtime_retention_latest_age_seconds"
    assert retention_metric.samples[0].value == 240.0


def test_runtime_retention_prunable_items_metric_uses_governed_categories():
    preview = type(
        "Preview",
        (),
        {
            "prunable_execution_count": 5,
            "prunable_compute_job_count": 4,
            "prunable_async_result_count": 3,
            "prunable_lineage_record_count": 2,
            "prunable_lineage_artifact_count": 1,
        },
    )()

    metric = runtime_retention_prunable_items_metric(preview=preview)

    samples = {sample.labels["category"]: sample.value for sample in metric.samples}
    assert metric.name == "lotus_performance_runtime_retention_prunable_items"
    assert samples == {
        "execution": 5,
        "compute_job": 4,
        "async_result": 3,
        "lineage_record": 2,
        "lineage_artifact": 1,
    }


def test_active_lease_age_seconds_or_zero_uses_available_active_lease(monkeypatch):
    monkeypatch.setattr("app.services.queue_metric_builders.age_seconds_since", lambda timestamp_utc: 42.0)
    snapshot = type(
        "Snapshot",
        (),
        {
            "status": "available",
            "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-05-31T10:00:00Z"})(),),
        },
    )()

    assert active_lease_age_seconds_or_zero(snapshot) == 42
    assert active_lease_age_seconds_or_zero(type("Snapshot", (), {"status": "available", "active_leases": ()})()) == 0
    assert active_lease_age_seconds_or_zero(None) == 0


def test_latest_reclaim_count_or_zero_uses_available_reclaimed_lease():
    snapshot = type(
        "Snapshot",
        (),
        {
            "status": "available",
            "latest_reclaimed_lease": type("Reclaim", (), {"reclaim_count": 3})(),
        },
    )()

    assert latest_reclaim_count_or_zero(snapshot) == 3
    assert (
        latest_reclaim_count_or_zero(type("Snapshot", (), {"status": "available", "latest_reclaimed_lease": None})())
        == 0
    )
    assert latest_reclaim_count_or_zero(None) == 0


def test_operator_action_lease_metrics_emit_active_and_reclaim_samples(monkeypatch):
    monkeypatch.setattr("app.services.queue_metric_builders.age_seconds_since", lambda timestamp_utc: 42.0)
    snapshot = type(
        "Snapshot",
        (),
        {
            "status": "available",
            "active_leases": (type("Lease", (), {"acquired_at_utc": "2026-05-31T10:00:00Z"})(),),
            "latest_reclaimed_lease": type(
                "Reclaim",
                (),
                {"reclaimed_at_utc": "2026-05-31T11:00:00Z", "reclaim_count": 2},
            )(),
        },
    )()

    metrics = operator_action_lease_metrics(snapshot=snapshot, spec=RECOVERY_DRILL_ACTION_METRICS)
    metric_samples = {metric.name: metric.samples[0].value for metric in metrics}

    assert metric_samples["lotus_performance_recovery_drill_active_actions"] == 1
    assert metric_samples["lotus_performance_recovery_drill_oldest_active_action_age_seconds"] == 42
    assert metric_samples["lotus_performance_recovery_drill_latest_reclaimed_action_age_seconds"] == 42
    assert metric_samples["lotus_performance_recovery_drill_reclaimed_actions"] == 2


def test_operator_action_lease_metrics_suppress_unavailable_snapshots():
    unavailable_snapshot = type("Snapshot", (), {"status": "unavailable"})()

    assert operator_action_lease_metrics(snapshot=None, spec=RECOVERY_DRILL_ACTION_METRICS) == ()
    assert operator_action_lease_metrics(snapshot=unavailable_snapshot, spec=RECOVERY_DRILL_ACTION_METRICS) == ()


def test_operator_action_lease_metrics_emit_active_zero_without_optional_age_or_reclaim():
    snapshot = type(
        "Snapshot",
        (),
        {
            "status": "available",
            "active_leases": (),
            "latest_reclaimed_lease": None,
        },
    )()

    metrics = operator_action_lease_metrics(snapshot=snapshot, spec=RECOVERY_DRILL_ACTION_METRICS)

    assert [metric.name for metric in metrics] == ["lotus_performance_recovery_drill_active_actions"]
    assert metrics[0].samples[0].value == 0
