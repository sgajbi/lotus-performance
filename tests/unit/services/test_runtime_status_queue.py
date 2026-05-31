from decimal import Decimal

from app.services.compute_job_store import ComputeQueueStats, ComputeRecoveryEvent
from app.services.durability_health_service import DurabilityHealthStatus, LineageStorageCapacitySnapshot
from app.services.lineage_metadata_store import LineageQueueStats, LineageRecoveryEvent
from app.services.runtime_status_domain import RuntimeDegradationDetail
from app.services.runtime_status_queue import (
    build_compute_queue_status,
    build_lineage_queue_status,
    recent_recovery_limit,
    runtime_queue_status_from_degradation,
    safe_compute_queue_inspection_anchors,
    safe_compute_recent_recoveries,
    safe_lineage_queue_inspection_anchors,
    safe_lineage_recent_recoveries,
    unavailable_runtime_queue_status,
)


def test_unavailable_runtime_queue_status_clears_queue_evidence():
    status = unavailable_runtime_queue_status(reason="durable_metadata_store_unreachable")

    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_store_unreachable"
    assert status.degradation_reasons == ()
    assert status.degradation_details == ()
    assert status.stats is None
    assert status.inspection_anchors is None
    assert status.recent_recoveries == ()
    assert status.storage_capacity is None


def test_runtime_queue_status_from_degradation_maps_available_and_degraded_states():
    stats = ComputeQueueStats(
        pending_count=0,
        leased_count=0,
        running_count=0,
        failed_count=0,
        complete_count=0,
        retry_backlog_count=0,
        lease_expired_count=0,
        terminal_failure_count=0,
        oldest_pending_age_seconds=0.0,
        oldest_leased_age_seconds=0.0,
        oldest_running_age_seconds=0.0,
    )

    available = runtime_queue_status_from_degradation(
        stats=stats,
        inspection_anchors=None,
        recent_recoveries=(),
        degradation_details=(),
    )
    degraded = runtime_queue_status_from_degradation(
        stats=stats,
        inspection_anchors=None,
        recent_recoveries=(),
        degradation_details=(
            RuntimeDegradationDetail(
                reason="compute_pending_age_exceeded",
                observed_value=Decimal("120"),
                threshold_value=Decimal("60"),
            ),
        ),
    )

    assert available.status == "available"
    assert available.reason is None
    assert available.degradation_reasons == ()
    assert available.degradation_details == ()
    assert available.stats is stats
    assert degraded.status == "degraded"
    assert degraded.reason == "compute_pending_age_exceeded"
    assert degraded.degradation_reasons == ("compute_pending_age_exceeded",)
    assert degraded.degradation_details[0].observed_value == Decimal("120")
    assert degraded.stats is stats


def test_build_compute_queue_status_maps_unavailable_durable_store_without_queue_reads(mocker):
    stats_reader = mocker.patch("app.services.runtime_status_queue.compute_job_store.get_queue_stats")

    status = build_compute_queue_status(
        DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
        settings=type("Settings", (), {})(),
    )

    assert status.status == "unavailable"
    assert status.reason == "durable_metadata_store_unreachable"
    assert status.stats is None
    stats_reader.assert_not_called()


def test_build_compute_queue_status_collects_stats_and_recovery_evidence(mocker):
    settings = type(
        "Settings",
        (),
        {
            "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 2,
            "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
            "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
            "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
            "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
            "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
        },
    )()
    stats = ComputeQueueStats(
        pending_count=0,
        leased_count=0,
        running_count=0,
        failed_count=0,
        complete_count=1,
        retry_backlog_count=0,
        lease_expired_count=0,
        terminal_failure_count=0,
        oldest_pending_age_seconds=0.0,
        oldest_leased_age_seconds=0.0,
        oldest_running_age_seconds=0.0,
    )
    recovery_event = ComputeRecoveryEvent(
        calculation_id="calc-recovered",
        analytics_type="ReturnsSeries",
        recovery_kind="retryable_failure",
        recovered_at_utc="2026-03-14T00:00:00Z",
        attempt_count=1,
        error_type="RuntimeError",
    )
    mocker.patch("app.services.runtime_status_queue.compute_job_store.get_queue_stats", return_value=stats)
    mocker.patch(
        "app.services.runtime_status_queue.compute_job_store.list_recent_recoveries",
        return_value=type("Page", (), {"items": [recovery_event]})(),
    )

    status = build_compute_queue_status(
        DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        settings=settings,
    )

    assert status.status == "available"
    assert status.stats is stats
    assert status.recent_recoveries == (recovery_event,)


def test_build_lineage_queue_status_maps_unavailable_storage_without_queue_reads(mocker):
    stats_reader = mocker.patch("app.services.runtime_status_queue.lineage_metadata_store.get_pending_payload_stats")
    mocker.patch(
        "app.services.runtime_status_queue.check_lineage_storage_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="lineage_storage_unavailable",
        ),
    )

    status = build_lineage_queue_status(
        DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        settings=type("Settings", (), {})(),
    )

    assert status.status == "unavailable"
    assert status.reason == "lineage_storage_unavailable"
    assert status.stats is None
    stats_reader.assert_not_called()


def test_build_lineage_queue_status_collects_stats_capacity_and_recovery_evidence(mocker):
    settings = type(
        "Settings",
        (),
        {
            "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 2,
            "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
            "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
            "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
            "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
            "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
        },
    )()
    stats = LineageQueueStats(
        pending_payload_count=0,
        leased_payload_count=0,
        retry_backlog_count=0,
        terminal_failure_count=0,
        oldest_pending_age_seconds=0.0,
        oldest_leased_age_seconds=0.0,
    )
    storage_capacity = LineageStorageCapacitySnapshot(
        total_bytes=1000,
        used_bytes=700,
        free_bytes=300,
        free_ratio=0.3,
        used_ratio=0.7,
    )
    recovery_event = LineageRecoveryEvent(
        calculation_id="lineage-recovered",
        calculation_type="TWR",
        recovery_kind="retryable_materialization_failure",
        recovered_at_utc="2026-03-14T00:00:01Z",
        attempt_count=2,
    )
    mocker.patch(
        "app.services.runtime_status_queue.check_lineage_storage_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch("app.services.runtime_status_queue.get_lineage_storage_capacity", return_value=storage_capacity)
    mocker.patch(
        "app.services.runtime_status_queue.lineage_metadata_store.get_pending_payload_stats",
        return_value=stats,
    )
    mocker.patch(
        "app.services.runtime_status_queue.lineage_metadata_store.list_recent_recoveries",
        return_value=[recovery_event],
    )

    status = build_lineage_queue_status(
        DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        settings=settings,
    )

    assert status.status == "available"
    assert status.stats is stats
    assert status.storage_capacity is storage_capacity
    assert status.recent_recoveries == (recovery_event,)


def test_safe_recent_recoveries_return_empty_on_disabled_limit_and_errors(mocker):
    settings = type("Settings", (), {"RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0})()
    assert recent_recovery_limit(settings=settings) == 0
    assert safe_compute_recent_recoveries(settings=settings) == ()
    assert safe_lineage_recent_recoveries(settings=settings) == ()

    error_settings = type("Settings", (), {"RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 2})()
    assert recent_recovery_limit(settings=error_settings) == 2
    mocker.patch(
        "app.services.runtime_status_queue.compute_job_store.list_recent_recoveries",
        side_effect=RuntimeError("boom"),
    )
    mocker.patch(
        "app.services.runtime_status_queue.lineage_metadata_store.list_recent_recoveries",
        side_effect=RuntimeError("boom"),
    )
    assert safe_compute_recent_recoveries(settings=error_settings) == ()
    assert safe_lineage_recent_recoveries(settings=error_settings) == ()


def test_safe_recent_recoveries_normalize_paged_items(mocker):
    settings = type("Settings", (), {"RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 2})()
    compute_event = ComputeRecoveryEvent(
        calculation_id="calc-recovered",
        analytics_type="ReturnsSeries",
        recovery_kind="retryable_failure",
        recovered_at_utc="2026-03-14T00:00:00Z",
        attempt_count=1,
        error_type="RuntimeError",
    )
    lineage_event = LineageRecoveryEvent(
        calculation_id="lineage-recovered",
        calculation_type="TWR",
        recovery_kind="retryable_materialization_failure",
        recovered_at_utc="2026-03-14T00:00:01Z",
        attempt_count=2,
    )
    mocker.patch(
        "app.services.runtime_status_queue.compute_job_store.list_recent_recoveries",
        return_value=type("Page", (), {"items": [compute_event]})(),
    )
    mocker.patch(
        "app.services.runtime_status_queue.lineage_metadata_store.list_recent_recoveries",
        return_value=[lineage_event],
    )

    assert safe_compute_recent_recoveries(settings=settings) == (compute_event,)
    assert safe_lineage_recent_recoveries(settings=settings) == (lineage_event,)


def test_safe_lineage_inspection_anchor_returns_none_on_error(mocker):
    mocker.patch(
        "app.services.runtime_status_queue.lineage_metadata_store.get_queue_inspection_anchors",
        side_effect=RuntimeError("boom"),
    )

    assert safe_lineage_queue_inspection_anchors() is None


def test_safe_compute_inspection_anchor_returns_none_on_error(mocker):
    mocker.patch(
        "app.services.runtime_status_queue.compute_job_store.get_queue_inspection_anchors",
        side_effect=RuntimeError("boom"),
    )

    assert safe_compute_queue_inspection_anchors() is None
