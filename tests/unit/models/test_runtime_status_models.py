from datetime import UTC, datetime

from app.models.runtime_status import build_runtime_status_response
from app.services.compute_job_store import ComputeQueueInspectionAnchors, ComputeQueueStats
from app.services.durability_health_service import DurabilityHealthStatus, LineageStorageCapacitySnapshot
from app.services.lineage_metadata_store import LineageQueueInspectionAnchors, LineageQueueStats
from app.services.runtime_status_service import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RecoveryDrillDegradationPolicy,
    RecoveryDrillStatus,
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
                reclaimable_count=2,
            ),
            inspection_anchors=ComputeQueueInspectionAnchors(
                oldest_pending_calculation_id="calc-pending",
                oldest_leased_calculation_id="calc-leased",
                oldest_running_calculation_id="calc-running",
                latest_terminal_failure_calculation_id="calc-failed",
                latest_recovered_calculation_id="calc-recovered",
            ),
            recent_recoveries=(
                type(
                    "ComputeRecovery",
                    (),
                    {
                        "calculation_id": "calc-recovered",
                        "analytics_type": "ReturnsSeries",
                        "recovery_kind": "retryable_failure",
                        "recovered_at_utc": "2026-03-14T00:00:00Z",
                        "attempt_count": 1,
                        "error_type": "RuntimeError",
                    },
                )(),
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
                reclaimable_count=1,
            ),
            inspection_anchors=LineageQueueInspectionAnchors(
                oldest_pending_calculation_id="lineage-pending",
                oldest_leased_calculation_id="lineage-leased",
                latest_terminal_failure_calculation_id="lineage-failed",
                latest_recovered_calculation_id="lineage-recovered",
            ),
            recent_recoveries=(
                type(
                    "LineageRecovery",
                    (),
                    {
                        "calculation_id": "lineage-recovered",
                        "calculation_type": "TWR",
                        "recovery_kind": "retryable_materialization_failure",
                        "recovered_at_utc": "2026-03-14T00:00:01Z",
                        "attempt_count": 2,
                    },
                )(),
            ),
            storage_capacity=LineageStorageCapacitySnapshot(
                total_bytes=1000,
                used_bytes=700,
                free_bytes=300,
                free_ratio=0.3,
                used_ratio=0.7,
            ),
        ),
        recovery_drill=RecoveryDrillStatus(
            status="degraded",
            reason="recovery_drill_age_exceeded",
            latest_generated_at_utc="2026-03-13T00:00:00Z",
            latest_status="passed",
            latest_operator_id="ops-user",
            latest_backup_identifier="backup-123",
            latest_age_seconds=86400.0,
            degradation_reasons=("recovery_drill_age_exceeded",),
            degradation_details=(
                RuntimeDegradationDetail(
                    reason="recovery_drill_age_exceeded",
                    observed_value=86400.0,
                    threshold_value=3600.0,
                ),
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
            storage_min_free_bytes=200,
            storage_min_free_ratio=0.25,
        ),
        recovery_drill_policy=RecoveryDrillDegradationPolicy(max_age_seconds=3600.0),
    )

    response = build_runtime_status_response(snapshot)

    assert response.runtime_status == "degraded"
    assert response.runtime_degradation_reasons == ["compute_queue:compute_pending_age_exceeded"]
    assert response.runtime_degradation_details[0].reason == "compute_pending_age_exceeded"
    assert response.compute_queue.pending_jobs == 1
    assert response.compute_queue.lease_expired_jobs == 7
    assert response.compute_queue.reclaimable_jobs == 2
    assert response.compute_queue.inspection_anchors is not None
    assert response.compute_queue.inspection_anchors.oldest_pending_calculation_id == "calc-pending"
    assert response.compute_queue.inspection_anchors.latest_recovered_calculation_id == "calc-recovered"
    assert response.compute_queue.recent_recoveries[0].calculation_id == "calc-recovered"
    assert response.compute_queue.recent_recoveries[0].recovery_kind == "retryable_failure"
    assert response.lineage_queue.pending_payloads == 9
    assert response.lineage_queue.leased_payloads == 2
    assert response.lineage_queue.reclaimable_payloads == 1
    assert response.lineage_queue.inspection_anchors is not None
    assert response.lineage_queue.inspection_anchors.latest_terminal_failure_calculation_id == "lineage-failed"
    assert response.lineage_queue.inspection_anchors.latest_recovered_calculation_id == "lineage-recovered"
    assert response.lineage_queue.recent_recoveries[0].calculation_id == "lineage-recovered"
    assert response.lineage_queue.storage_total_bytes == 1000
    assert response.lineage_queue.storage_free_bytes == 300
    assert response.lineage_queue.storage_free_ratio == 0.3
    assert response.recovery_drill.status == "degraded"
    assert response.recovery_drill.latest_status == "passed"
    assert response.recovery_drill.latest_operator_id == "ops-user"
    assert response.recovery_drill.degradation_reasons == ["recovery_drill_age_exceeded"]
    assert response.compute_queue_policy.pending_age_seconds == 30.0
    assert response.lineage_queue_policy.leased_age_seconds == 8.0
    assert response.lineage_queue_policy.terminal_failure_count == 5
    assert response.lineage_queue_policy.storage_min_free_bytes == 200
    assert response.lineage_queue_policy.storage_min_free_ratio == 0.25
    assert response.recovery_drill_policy.max_age_seconds == 3600.0


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
            inspection_anchors=None,
            recent_recoveries=(),
        ),
        lineage_queue=RuntimeQueueStatus(
            status="available",
            reason=None,
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        ),
        recovery_drill=RecoveryDrillStatus(
            status="available",
            reason=None,
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_backup_identifier=None,
            latest_age_seconds=None,
            degradation_reasons=(),
            degradation_details=(),
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
            storage_min_free_bytes=0,
            storage_min_free_ratio=0.0,
        ),
        recovery_drill_policy=RecoveryDrillDegradationPolicy(max_age_seconds=0.0),
    )

    response = build_runtime_status_response(snapshot)

    assert response.compute_queue.status == "unavailable"
    assert response.compute_queue.reason == "RuntimeError"
    assert response.compute_queue.pending_jobs is None
    assert response.lineage_queue.pending_payloads is None
    assert response.recovery_drill.status == "available"
    assert response.recovery_drill.latest_status is None
