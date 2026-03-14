from datetime import UTC, datetime

from app.services.compute_job_store import ComputeQueueStats
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageQueueStats
from app.services.runtime_status_service import build_runtime_status_snapshot


def test_runtime_status_snapshot_reports_ready_with_queue_stats(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
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
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
            pending_count=2,
            leased_count=1,
            running_count=3,
            failed_count=4,
            complete_count=5,
            retry_backlog_count=1,
            lease_expired_count=2,
            terminal_failure_count=3,
            oldest_pending_age_seconds=120.0,
            oldest_leased_age_seconds=60.0,
            oldest_running_age_seconds=30.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=6,
            retry_backlog_count=2,
            terminal_failure_count=1,
            oldest_pending_age_seconds=45.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "ready"
    assert snapshot.runtime_degradation_reasons == ()
    assert snapshot.runtime_degradation_details == ()
    assert snapshot.compute_queue_policy.pending_age_seconds == 0.0
    assert snapshot.compute_queue_policy.retry_backlog_count == 0
    assert snapshot.lineage_queue_policy.pending_age_seconds == 0.0
    assert snapshot.lineage_queue_policy.terminal_failure_count == 0
    assert snapshot.compute_queue.status == "available"
    assert snapshot.compute_queue.degradation_reasons == ()
    assert snapshot.compute_queue.degradation_details == ()
    assert snapshot.compute_queue.stats is not None
    assert snapshot.compute_queue.stats.pending_count == 2
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.lineage_queue.degradation_reasons == ()
    assert snapshot.lineage_queue.degradation_details == ()
    assert snapshot.lineage_queue.stats is not None
    assert snapshot.lineage_queue.stats.pending_payload_count == 6
    assert snapshot.lineage_queue.stats.retry_backlog_count == 2
    assert isinstance(snapshot.generated_at, datetime)
    assert snapshot.generated_at.tzinfo == UTC


def test_runtime_status_snapshot_reports_draining_when_app_is_draining(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
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
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
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
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=True)

    assert snapshot.runtime_status == "draining"
    assert snapshot.runtime_degradation_reasons == ()
    assert snapshot.runtime_degradation_details == ()
    assert snapshot.draining is True


def test_runtime_status_snapshot_reports_degraded_when_durable_store_is_unavailable(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
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
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(
            is_ready=False,
            status="unavailable",
            reason="durable_metadata_store_unreachable",
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "unavailable"
    assert snapshot.runtime_degradation_reasons == (
        "compute_queue:durable_metadata_store_unreachable",
        "lineage_queue:durable_metadata_store_unreachable",
    )
    assert snapshot.runtime_degradation_details == ()
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "durable_metadata_store_unreachable"
    assert snapshot.compute_queue.degradation_reasons == ()
    assert snapshot.compute_queue.degradation_details == ()
    assert snapshot.compute_queue.stats is None
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.lineage_queue.degradation_reasons == ()
    assert snapshot.lineage_queue.degradation_details == ()
    assert snapshot.lineage_queue.stats is None


def test_runtime_status_snapshot_reports_degraded_when_queue_read_fails(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
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
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        side_effect=RuntimeError("db timeout"),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=1,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=30.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("compute_queue:RuntimeError",)
    assert snapshot.runtime_degradation_details == ()
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "RuntimeError"
    assert snapshot.compute_queue.degradation_reasons == ()
    assert snapshot.lineage_queue.status == "available"


def test_runtime_status_snapshot_degrades_when_compute_age_threshold_is_exceeded(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 20.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
            pending_count=0,
            leased_count=0,
            running_count=2,
            failed_count=0,
            complete_count=0,
            retry_backlog_count=0,
            lease_expired_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
            oldest_running_age_seconds=45.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("compute_queue:compute_running_age_exceeded",)
    assert len(snapshot.runtime_degradation_details) == 1
    assert snapshot.runtime_degradation_details[0].reason == "compute_running_age_exceeded"
    assert snapshot.runtime_degradation_details[0].observed_value == 45.0
    assert snapshot.runtime_degradation_details[0].threshold_value == 20.0
    assert snapshot.compute_queue.status == "degraded"
    assert snapshot.compute_queue.reason == "compute_running_age_exceeded"
    assert snapshot.compute_queue.degradation_reasons == ("compute_running_age_exceeded",)
    assert snapshot.compute_queue.degradation_details == snapshot.runtime_degradation_details


def test_runtime_status_snapshot_degrades_when_lineage_age_threshold_is_exceeded(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
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
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=1,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=45.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("lineage_queue:lineage_pending_age_exceeded",)
    assert len(snapshot.runtime_degradation_details) == 1
    assert snapshot.runtime_degradation_details[0].reason == "lineage_pending_age_exceeded"
    assert snapshot.runtime_degradation_details[0].observed_value == 45.0
    assert snapshot.runtime_degradation_details[0].threshold_value == 10.0
    assert snapshot.lineage_queue.status == "degraded"
    assert snapshot.lineage_queue.reason == "lineage_pending_age_exceeded"
    assert snapshot.lineage_queue.degradation_reasons == ("lineage_pending_age_exceeded",)
    assert snapshot.lineage_queue.degradation_details == snapshot.runtime_degradation_details


def test_runtime_status_snapshot_degrades_when_compute_failure_pressure_threshold_is_exceeded(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 2,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
            pending_count=2,
            leased_count=0,
            running_count=0,
            failed_count=0,
            complete_count=0,
            retry_backlog_count=2,
            lease_expired_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
            oldest_running_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("compute_queue:compute_retry_backlog_exceeded",)
    assert len(snapshot.runtime_degradation_details) == 1
    assert snapshot.runtime_degradation_details[0].reason == "compute_retry_backlog_exceeded"
    assert snapshot.runtime_degradation_details[0].observed_value == 2.0
    assert snapshot.runtime_degradation_details[0].threshold_value == 2.0
    assert snapshot.compute_queue.status == "degraded"
    assert snapshot.compute_queue.reason == "compute_retry_backlog_exceeded"
    assert snapshot.compute_queue.degradation_reasons == ("compute_retry_backlog_exceeded",)
    assert snapshot.compute_queue.degradation_details == snapshot.runtime_degradation_details
    assert snapshot.compute_queue_policy.retry_backlog_count == 2


def test_runtime_status_snapshot_degrades_when_lineage_failure_pressure_threshold_is_exceeded(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
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
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 1,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
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
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=1,
            oldest_pending_age_seconds=0.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("lineage_queue:lineage_terminal_failure_exceeded",)
    assert len(snapshot.runtime_degradation_details) == 1
    assert snapshot.runtime_degradation_details[0].reason == "lineage_terminal_failure_exceeded"
    assert snapshot.runtime_degradation_details[0].observed_value == 1.0
    assert snapshot.runtime_degradation_details[0].threshold_value == 1.0
    assert snapshot.lineage_queue.status == "degraded"
    assert snapshot.lineage_queue.reason == "lineage_terminal_failure_exceeded"
    assert snapshot.lineage_queue.degradation_reasons == ("lineage_terminal_failure_exceeded",)
    assert snapshot.lineage_queue.degradation_details == snapshot.runtime_degradation_details
    assert snapshot.lineage_queue_policy.terminal_failure_count == 1


def test_runtime_status_snapshot_reports_all_active_degradation_reasons(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 10.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 5.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 1.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 5.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 1,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 1,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.get_queue_stats",
        return_value=ComputeQueueStats(
            pending_count=1,
            leased_count=1,
            running_count=1,
            failed_count=1,
            complete_count=0,
            retry_backlog_count=1,
            lease_expired_count=1,
            terminal_failure_count=1,
            oldest_pending_age_seconds=20.0,
            oldest_leased_age_seconds=10.0,
            oldest_running_age_seconds=2.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=1,
            retry_backlog_count=1,
            terminal_failure_count=1,
            oldest_pending_age_seconds=10.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.compute_queue_policy.pending_age_seconds == 10.0
    assert snapshot.compute_queue_policy.leased_age_seconds == 5.0
    assert snapshot.compute_queue_policy.running_age_seconds == 1.0
    assert snapshot.compute_queue_policy.retry_backlog_count == 1
    assert snapshot.compute_queue_policy.lease_expiry_count == 1
    assert snapshot.compute_queue_policy.terminal_failure_count == 1
    assert snapshot.lineage_queue_policy.pending_age_seconds == 5.0
    assert snapshot.lineage_queue_policy.retry_backlog_count == 1
    assert snapshot.lineage_queue_policy.terminal_failure_count == 1
    assert snapshot.compute_queue.reason == "compute_retry_backlog_exceeded"
    assert snapshot.compute_queue.degradation_reasons == (
        "compute_retry_backlog_exceeded",
        "compute_terminal_failure_exceeded",
        "compute_lease_expiry_pressure_exceeded",
        "compute_pending_age_exceeded",
        "compute_leased_age_exceeded",
        "compute_running_age_exceeded",
    )
    assert snapshot.compute_queue.degradation_details == (
        snapshot.runtime_degradation_details[0],
        snapshot.runtime_degradation_details[1],
        snapshot.runtime_degradation_details[2],
        snapshot.runtime_degradation_details[3],
        snapshot.runtime_degradation_details[4],
        snapshot.runtime_degradation_details[5],
    )
    assert snapshot.lineage_queue.reason == "lineage_retry_backlog_exceeded"
    assert snapshot.lineage_queue.degradation_reasons == (
        "lineage_retry_backlog_exceeded",
        "lineage_terminal_failure_exceeded",
        "lineage_pending_age_exceeded",
    )
    assert snapshot.lineage_queue.degradation_details == (
        snapshot.runtime_degradation_details[6],
        snapshot.runtime_degradation_details[7],
        snapshot.runtime_degradation_details[8],
    )
    assert snapshot.runtime_degradation_reasons == (
        "compute_queue:compute_retry_backlog_exceeded",
        "compute_queue:compute_terminal_failure_exceeded",
        "compute_queue:compute_lease_expiry_pressure_exceeded",
        "compute_queue:compute_pending_age_exceeded",
        "compute_queue:compute_leased_age_exceeded",
        "compute_queue:compute_running_age_exceeded",
        "lineage_queue:lineage_retry_backlog_exceeded",
        "lineage_queue:lineage_terminal_failure_exceeded",
        "lineage_queue:lineage_pending_age_exceeded",
    )
    assert tuple(detail.reason for detail in snapshot.runtime_degradation_details) == (
        "compute_retry_backlog_exceeded",
        "compute_terminal_failure_exceeded",
        "compute_lease_expiry_pressure_exceeded",
        "compute_pending_age_exceeded",
        "compute_leased_age_exceeded",
        "compute_running_age_exceeded",
        "lineage_retry_backlog_exceeded",
        "lineage_terminal_failure_exceeded",
        "lineage_pending_age_exceeded",
    )
