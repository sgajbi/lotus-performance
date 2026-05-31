from app.services.queue_metric_builders import (
    RECOVERY_DRILL_ACTION_METRICS,
    active_lease_age_seconds_or_zero,
    availability_metric,
    compute_queue_degradation_breach_metric,
    labeled_metric,
    latest_reclaim_count_or_zero,
    lineage_queue_degradation_breach_metric,
    operator_action_lease_metrics,
    policy_threshold_metric,
    reason_labeled_metric,
    single_sample_metric,
    snapshot_available,
)
from app.services.runtime_status_domain import ComputeQueueDegradationPolicy, LineageQueueDegradationPolicy


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
