from decimal import Decimal

from app.services.compute_job_store import ComputeQueueStats
from app.services.runtime_status_domain import RuntimeDegradationDetail
from app.services.runtime_status_queue import (
    runtime_queue_status_from_degradation,
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
