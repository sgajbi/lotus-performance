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
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
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
            oldest_pending_age_seconds=120.0,
            oldest_leased_age_seconds=60.0,
            oldest_running_age_seconds=30.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(pending_payload_count=6, oldest_pending_age_seconds=45.0),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "ready"
    assert snapshot.compute_queue.status == "available"
    assert snapshot.compute_queue.stats is not None
    assert snapshot.compute_queue.stats.pending_count == 2
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.lineage_queue.stats is not None
    assert snapshot.lineage_queue.stats.pending_payload_count == 6
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
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
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
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
            oldest_running_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(pending_payload_count=0, oldest_pending_age_seconds=0.0),
    )

    snapshot = build_runtime_status_snapshot(is_draining=True)

    assert snapshot.runtime_status == "draining"
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
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
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
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "durable_metadata_store_unreachable"
    assert snapshot.compute_queue.stats is None
    assert snapshot.lineage_queue.status == "unavailable"
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
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
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
        return_value=LineageQueueStats(pending_payload_count=1, oldest_pending_age_seconds=30.0),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.compute_queue.status == "unavailable"
    assert snapshot.compute_queue.reason == "RuntimeError"
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
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
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
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
            oldest_running_age_seconds=45.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(pending_payload_count=0, oldest_pending_age_seconds=0.0),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.compute_queue.status == "degraded"
    assert snapshot.compute_queue.reason == "compute_running_age_exceeded"


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
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 10.0,
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
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
            oldest_running_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(pending_payload_count=1, oldest_pending_age_seconds=45.0),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.lineage_queue.status == "degraded"
    assert snapshot.lineage_queue.reason == "lineage_pending_age_exceeded"
