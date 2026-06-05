from datetime import UTC, datetime

from app.models.runtime_status import (
    _compute_queue_response,
    _compute_queue_stats_fields,
    _lineage_queue_response,
    build_runtime_status_response,
)
from app.services.compute_job_store import ComputeQueueInspectionAnchors, ComputeQueueStats, ComputeRecoveryEvent
from app.services.durability_health_service import DurabilityHealthStatus, LineageStorageCapacitySnapshot
from app.services.lineage_metadata_store import LineageQueueInspectionAnchors, LineageQueueStats, LineageRecoveryEvent
from app.services.runtime_status_domain import (
    ComputeQueueDegradationPolicy,
    LineageQueueDegradationPolicy,
    RecoveryDrillDegradationPolicy,
    RecoveryDrillStatus,
    RuntimeDegradationDetail,
    RuntimeQueueStatus,
    RuntimeRetentionDegradationPolicy,
    RuntimeRetentionStatus,
    RuntimeStatusSnapshot,
)


def test_compute_queue_response_maps_stats_anchors_and_recoveries():
    response = _compute_queue_response(
        RuntimeQueueStatus(
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
                reclaimable_count=9,
            ),
            inspection_anchors=ComputeQueueInspectionAnchors(
                oldest_pending_calculation_id="calc-pending",
                oldest_leased_calculation_id="calc-leased",
                oldest_running_calculation_id="calc-running",
                latest_terminal_failure_calculation_id="calc-failed",
                latest_recovered_calculation_id="calc-recovered",
            ),
            recent_recoveries=(
                ComputeRecoveryEvent(
                    calculation_id="calc-recovered",
                    analytics_type="ReturnsSeries",
                    recovery_kind="retryable_failure",
                    recovered_at_utc="2026-03-14T00:00:00Z",
                    attempt_count=1,
                    error_type="RuntimeError",
                ),
            ),
        )
    )

    assert response.status == "degraded"
    assert response.pending_jobs == 1
    assert response.reclaimable_jobs == 9
    assert response.degradation_details[0].reason == "compute_pending_age_exceeded"
    assert response.inspection_anchors is not None
    assert response.inspection_anchors.latest_recovered_calculation_id == "calc-recovered"
    assert response.recent_recoveries[0].calculation_id == "calc-recovered"
    assert response.recent_recoveries[0].error_type == "RuntimeError"


def test_compute_queue_response_omits_optional_fields_when_stats_are_unavailable():
    response = _compute_queue_response(
        RuntimeQueueStatus(
            status="unavailable",
            reason="RuntimeError",
            degradation_reasons=(),
            degradation_details=(),
            stats=None,
            inspection_anchors=None,
            recent_recoveries=(),
        )
    )

    assert response.status == "unavailable"
    assert response.reason == "RuntimeError"
    assert response.pending_jobs is None
    assert response.inspection_anchors is None
    assert response.recent_recoveries == []


def test_compute_queue_stats_fields_map_available_and_unavailable_stats():
    stats = ComputeQueueStats(
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
        reclaimable_count=9,
    )

    assert _compute_queue_stats_fields(stats) == {
        "pending_jobs": 1,
        "leased_jobs": 2,
        "running_jobs": 3,
        "failed_jobs": 4,
        "complete_jobs": 5,
        "retry_backlog_jobs": 6,
        "lease_expired_jobs": 7,
        "reclaimable_jobs": 9,
        "terminal_failure_jobs": 8,
        "oldest_pending_age_seconds": 120.0,
        "oldest_leased_age_seconds": 90.0,
        "oldest_running_age_seconds": 60.0,
    }
    assert all(value is None for value in _compute_queue_stats_fields(None).values())


def test_lineage_queue_response_maps_stats_storage_anchors_and_recoveries():
    response = _lineage_queue_response(
        RuntimeQueueStatus(
            status="degraded",
            reason="lineage_storage_low_free_ratio",
            degradation_reasons=("lineage_storage_low_free_ratio",),
            degradation_details=(
                RuntimeDegradationDetail(
                    reason="lineage_storage_low_free_ratio",
                    observed_value=0.1,
                    threshold_value=0.25,
                ),
            ),
            stats=LineageQueueStats(
                pending_payload_count=3,
                leased_payload_count=4,
                retry_backlog_count=5,
                terminal_failure_count=6,
                oldest_pending_age_seconds=70.0,
                oldest_leased_age_seconds=80.0,
                reclaimable_count=7,
            ),
            inspection_anchors=LineageQueueInspectionAnchors(
                oldest_pending_calculation_id="lineage-pending",
                oldest_leased_calculation_id="lineage-leased",
                latest_terminal_failure_calculation_id="lineage-failed",
                latest_recovered_calculation_id="lineage-recovered",
            ),
            recent_recoveries=(
                LineageRecoveryEvent(
                    calculation_id="lineage-recovered",
                    calculation_type="TWR",
                    recovery_kind="retryable_materialization_failure",
                    recovered_at_utc="2026-03-14T00:00:00Z",
                    attempt_count=2,
                ),
            ),
            storage_capacity=LineageStorageCapacitySnapshot(
                total_bytes=1000,
                used_bytes=900,
                free_bytes=100,
                free_ratio=0.1,
                used_ratio=0.9,
            ),
        )
    )

    assert response.status == "degraded"
    assert response.reason == "lineage_storage_low_free_ratio"
    assert response.degradation_details[0].reason == "lineage_storage_low_free_ratio"
    assert response.pending_payloads == 3
    assert response.reclaimable_payloads == 7
    assert response.storage_free_ratio == 0.1
    assert response.inspection_anchors is not None
    assert response.inspection_anchors.latest_recovered_calculation_id == "lineage-recovered"
    assert response.recent_recoveries[0].calculation_id == "lineage-recovered"
    assert response.recent_recoveries[0].calculation_type == "TWR"


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
            active_run_status="active",
            active_run_reason=None,
            active_run_count=1,
            oldest_active_run_operator_id="ops-user",
            oldest_active_run_tenant_id="tenant-a",
            oldest_active_run_governed_target="backup-123",
            oldest_active_run_acquired_at_utc="2026-03-14T00:30:00Z",
            oldest_active_run_age_seconds=1800.0,
            latest_reclaimed_run_operator_id="ops-old",
            latest_reclaimed_run_tenant_id="tenant-a",
            latest_reclaimed_run_governed_target="backup-old",
            latest_reclaimed_run_acquired_at_utc="2026-03-13T22:30:00Z",
            latest_reclaimed_run_reclaimed_at_utc="2026-03-14T00:15:00Z",
            latest_reclaimed_run_age_seconds=2700.0,
            reclaimed_run_count=3,
            recent_reclaimed_runs=(
                type(
                    "RecentReclaim",
                    (),
                    {
                        "operator_id": "ops-old",
                        "tenant_id": "tenant-a",
                        "governed_target": "backup-old",
                        "acquired_at_utc": "2026-03-13T22:30:00Z",
                        "reclaimed_at_utc": "2026-03-14T00:15:00Z",
                        "reclaimed_age_seconds": 2700.0,
                        "reclaim_count": 3,
                    },
                )(),
            ),
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
        runtime_retention=RuntimeRetentionStatus(
            status="degraded",
            reason="runtime_retention_age_exceeded",
            active_run_status="active",
            active_run_reason=None,
            active_run_count=2,
            oldest_active_run_operator_id="ops-batch",
            oldest_active_run_tenant_id="tenant-a",
            oldest_active_run_governed_target="apply:30:retention-nightly",
            oldest_active_run_acquired_at_utc="2026-03-13T23:30:00Z",
            oldest_active_run_age_seconds=1800.0,
            latest_reclaimed_run_operator_id="ops-old-batch",
            latest_reclaimed_run_tenant_id="tenant-a",
            latest_reclaimed_run_governed_target="apply:30:old-job",
            latest_reclaimed_run_acquired_at_utc="2026-03-13T22:00:00Z",
            latest_reclaimed_run_reclaimed_at_utc="2026-03-13T23:15:00Z",
            latest_reclaimed_run_age_seconds=4500.0,
            reclaimed_run_count=4,
            recent_reclaimed_runs=(
                type(
                    "RecentReclaim",
                    (),
                    {
                        "operator_id": "ops-old-batch",
                        "tenant_id": "tenant-a",
                        "governed_target": "apply:30:old-job",
                        "acquired_at_utc": "2026-03-13T22:00:00Z",
                        "reclaimed_at_utc": "2026-03-13T23:15:00Z",
                        "reclaimed_age_seconds": 4500.0,
                        "reclaim_count": 4,
                    },
                )(),
            ),
            preview_status="available",
            preview_reason=None,
            current_cutoff_utc="2026-02-13T00:00:00Z",
            current_retention_days=30,
            current_prunable_execution_count=7,
            current_prunable_compute_job_count=6,
            current_prunable_async_result_count=5,
            current_prunable_lineage_record_count=4,
            current_prunable_lineage_artifact_count=3,
            latest_generated_at_utc="2026-03-12T00:00:00Z",
            latest_status="applied",
            latest_operator_id="ops-batch",
            latest_trigger_mode="scheduled",
            latest_job_id="retention-nightly",
            latest_cleanup_mode="apply",
            latest_retention_days=30,
            latest_age_seconds=172800.0,
            degradation_reasons=("runtime_retention_age_exceeded",),
            degradation_details=(
                RuntimeDegradationDetail(
                    reason="runtime_retention_age_exceeded",
                    observed_value=172800.0,
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
        recovery_drill_policy=RecoveryDrillDegradationPolicy(
            max_age_seconds=3600.0,
            active_run_age_seconds=900.0,
            reclaim_count=2,
        ),
        runtime_retention_policy=RuntimeRetentionDegradationPolicy(
            max_age_seconds=3600.0,
            active_run_age_seconds=1200.0,
            reclaim_count=3,
        ),
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
    assert response.recovery_drill.active_run_status == "active"
    assert response.recovery_drill.active_run_count == 1
    assert response.recovery_drill.oldest_active_run_governed_target == "backup-123"
    assert response.recovery_drill.latest_reclaimed_run_operator_id == "ops-old"
    assert response.recovery_drill.latest_reclaimed_run_governed_target == "backup-old"
    assert response.recovery_drill.reclaimed_run_count == 3
    assert response.recovery_drill.recent_reclaimed_runs[0].operator_id == "ops-old"
    assert response.recovery_drill.latest_status == "passed"
    assert response.recovery_drill.latest_operator_id == "ops-user"
    assert response.recovery_drill.degradation_reasons == ["recovery_drill_age_exceeded"]
    assert response.runtime_retention.status == "degraded"
    assert response.runtime_retention.active_run_status == "active"
    assert response.runtime_retention.active_run_count == 2
    assert response.runtime_retention.oldest_active_run_governed_target == "apply:30:retention-nightly"
    assert response.runtime_retention.latest_reclaimed_run_operator_id == "ops-old-batch"
    assert response.runtime_retention.latest_reclaimed_run_governed_target == "apply:30:old-job"
    assert response.runtime_retention.reclaimed_run_count == 4
    assert response.runtime_retention.recent_reclaimed_runs[0].operator_id == "ops-old-batch"
    assert response.runtime_retention.preview_status == "available"
    assert response.runtime_retention.current_cutoff_utc == "2026-02-13T00:00:00Z"
    assert response.runtime_retention.current_prunable_execution_count == 7
    assert response.runtime_retention.latest_trigger_mode == "scheduled"
    assert response.runtime_retention.latest_job_id == "retention-nightly"
    assert response.runtime_retention.latest_cleanup_mode == "apply"
    assert response.runtime_retention.latest_retention_days == 30
    assert response.runtime_retention.degradation_reasons == ["runtime_retention_age_exceeded"]
    assert response.compute_queue_policy.pending_age_seconds == 30.0
    assert response.lineage_queue_policy.leased_age_seconds == 8.0
    assert response.lineage_queue_policy.terminal_failure_count == 5
    assert response.lineage_queue_policy.storage_min_free_bytes == 200
    assert response.lineage_queue_policy.storage_min_free_ratio == 0.25
    assert response.recovery_drill_policy.max_age_seconds == 3600.0
    assert response.recovery_drill_policy.active_run_age_seconds == 900.0
    assert response.recovery_drill_policy.reclaim_count == 2
    assert response.runtime_retention_policy.max_age_seconds == 3600.0
    assert response.runtime_retention_policy.active_run_age_seconds == 1200.0
    assert response.runtime_retention_policy.reclaim_count == 3


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
            active_run_status="available",
            active_run_reason=None,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=None,
            latest_reclaimed_run_tenant_id=None,
            latest_reclaimed_run_governed_target=None,
            latest_reclaimed_run_acquired_at_utc=None,
            latest_reclaimed_run_reclaimed_at_utc=None,
            latest_reclaimed_run_age_seconds=None,
            reclaimed_run_count=0,
            recent_reclaimed_runs=(),
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_backup_identifier=None,
            latest_age_seconds=None,
            degradation_reasons=(),
            degradation_details=(),
        ),
        runtime_retention=RuntimeRetentionStatus(
            status="available",
            reason=None,
            active_run_status="available",
            active_run_reason=None,
            active_run_count=0,
            oldest_active_run_operator_id=None,
            oldest_active_run_tenant_id=None,
            oldest_active_run_governed_target=None,
            oldest_active_run_acquired_at_utc=None,
            oldest_active_run_age_seconds=None,
            latest_reclaimed_run_operator_id=None,
            latest_reclaimed_run_tenant_id=None,
            latest_reclaimed_run_governed_target=None,
            latest_reclaimed_run_acquired_at_utc=None,
            latest_reclaimed_run_reclaimed_at_utc=None,
            latest_reclaimed_run_age_seconds=None,
            reclaimed_run_count=0,
            recent_reclaimed_runs=(),
            preview_status="unavailable",
            preview_reason="RuntimeError",
            current_cutoff_utc=None,
            current_retention_days=None,
            current_prunable_execution_count=None,
            current_prunable_compute_job_count=None,
            current_prunable_async_result_count=None,
            current_prunable_lineage_record_count=None,
            current_prunable_lineage_artifact_count=None,
            latest_generated_at_utc=None,
            latest_status=None,
            latest_operator_id=None,
            latest_trigger_mode=None,
            latest_job_id=None,
            latest_cleanup_mode=None,
            latest_retention_days=None,
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
        recovery_drill_policy=RecoveryDrillDegradationPolicy(
            max_age_seconds=0.0,
            active_run_age_seconds=0.0,
            reclaim_count=0,
        ),
        runtime_retention_policy=RuntimeRetentionDegradationPolicy(
            max_age_seconds=0.0,
            active_run_age_seconds=0.0,
            reclaim_count=0,
        ),
    )

    response = build_runtime_status_response(snapshot)

    assert response.compute_queue.status == "unavailable"
    assert response.compute_queue.reason == "RuntimeError"
    assert response.compute_queue.pending_jobs is None
    assert response.lineage_queue.pending_payloads is None
    assert response.recovery_drill.status == "available"
    assert response.recovery_drill.active_run_status == "available"
    assert response.recovery_drill.latest_status is None
    assert response.runtime_retention.status == "available"
    assert response.runtime_retention.active_run_status == "available"
    assert response.runtime_retention.preview_status == "unavailable"
    assert response.runtime_retention.preview_reason == "RuntimeError"
    assert response.runtime_retention.latest_status is None
