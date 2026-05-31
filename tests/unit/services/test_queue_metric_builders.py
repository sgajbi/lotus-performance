from app.services.queue_metric_builders import (
    RECOVERY_DRILL_ACTION_METRICS,
    active_lease_age_seconds_or_zero,
    availability_metric,
    latest_reclaim_count_or_zero,
    operator_action_lease_metrics,
    policy_threshold_metric,
    reason_labeled_metric,
    snapshot_available,
)


def test_availability_metric_emits_unlabelled_binary_sample():
    available = availability_metric(metric_name="available_metric", description="availability", is_available=True)
    unavailable = availability_metric(metric_name="unavailable_metric", description="availability", is_available=False)

    assert available.samples[0].value == 1
    assert unavailable.samples[0].value == 0


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
