from datetime import UTC, datetime

from app.models.runtime_status import build_runtime_status_response
from app.services.compute_job_store import ComputeQueueStats
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageQueueStats
from app.services.runtime_status_service import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RuntimeDegradationDetail,
    RuntimeQueueStatus,
    RuntimeStatusSnapshot,
)


def test_build_runtime_status_response_serializes_snapshot_details():
    snapshot = RuntimeStatusSnapshot(
        generated_at=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
        runtime_status="degraded",
        runtime_degradation_reasons=("compute_queue:compute_pending_age_exceeded",),
        runtime_degradation_details=(
            RuntimeDegradationDetail(
                reason="compute_pending_age_exceeded",
                observed_value=120.0,
                threshold_value=30.0,
            ),
        ),
        draining=False,
        durable_metadata_store=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        compute_queue=RuntimeQueueStatus(
            status="degraded",
            reason="compute_pending_age_exceeded",
            degradation_reasons=("compute_pending_age_exceeded",),
            degradation_details=(
                RuntimeDegradationDetail(
                    reason="compute_pending_age_exceeded",
                    observed_value=120.0,
                    threshold_value=30.0,
                ),
            ),
            stats=ComputeQueueStats(
                pending_count=1,
                leased_count=2,
                running_count=3,
                failed_count=4,
                complete_count=5,
                retry_backlog_count=6,
                lease_expired_count=7,
                terminal_failure_count=8,
                oldest_pending_age_seconds=120.0,
                oldest_leased_age_seconds=90.0,
                oldest_running_age_seconds=60.0,
            ),
        ),
        lineage_queue=RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=LineageQueueStats(
                pending_payload_count=9,
                leased_payload_count=2,
                retry_backlog_count=10,
                terminal_failure_count=11,
                oldest_pending_age_seconds=45.0,
                oldest_leased_age_seconds=12.0,
            ),
        ),
        compute_queue_policy=ComputeQueueDegradationPolicy(
            pending_age_seconds=30.0,
            leased_age_seconds=20.0,
            running_age_seconds=10.0,
            retry_backlog_count=3,
            lease_expiry_count=2,
            terminal_failure_count=1,
        ),
        lineage_queue_policy=LineageQueueDegradationPolicy(
            pending_age_seconds=15.0,
            leased_age_seconds=8.0,
            retry_backlog_count=4,
            terminal_failure_count=5,
        ),
    )

    response = build_runtime_status_response(snapshot)

    assert response.runtime_status == "degraded"
    assert response.runtime_degradation_reasons == ["compute_queue:compute_pending_age_exceeded"]
    assert response.runtime_degradation_details[0].reason == "compute_pending_age_exceeded"
    assert response.compute_queue.pending_jobs == 1
    assert response.compute_queue.lease_expired_jobs == 7
    assert response.lineage_queue.pending_payloads == 9
    assert response.lineage_queue.leased_payloads == 2
    assert response.compute_queue_policy.pending_age_seconds == 30.0
    assert response.lineage_queue_policy.leased_age_seconds == 8.0
    assert response.lineage_queue_policy.terminal_failure_count == 5


def test_build_runtime_status_response_handles_unavailable_queue_without_stats():
    snapshot = RuntimeStatusSnapshot(
        generated_at=datetime(2026, 3, 14, 0, 0, tzinfo=UTC),
        runtime_status="degraded",
        runtime_degradation_reasons=("compute_queue:RuntimeError",),
        runtime_degradation_details=(),
        draining=False,
        durable_metadata_store=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
        compute_queue=RuntimeQueueStatus(
            status="unavailable",
            reason="RuntimeError",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
        ),
        lineage_queue=RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
        ),
        compute_queue_policy=ComputeQueueDegradationPolicy(
            pending_age_seconds=30.0,
            leased_age_seconds=20.0,
            running_age_seconds=10.0,
            retry_backlog_count=3,
            lease_expiry_count=2,
            terminal_failure_count=1,
        ),
        lineage_queue_policy=LineageQueueDegradationPolicy(
            pending_age_seconds=15.0,
            leased_age_seconds=8.0,
            retry_backlog_count=4,
            terminal_failure_count=5,
        ),
    )

    response = build_runtime_status_response(snapshot)

    assert response.compute_queue.status == "unavailable"
    assert response.compute_queue.reason == "RuntimeError"
    assert response.compute_queue.pending_jobs is None
    assert response.lineage_queue.pending_payloads is None
