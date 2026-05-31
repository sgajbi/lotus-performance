from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services import runtime_status_service
from app.services.compute_job_store import ComputeQueueInspectionAnchors, ComputeQueueStats, ComputeRecoveryEvent
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageQueueInspectionAnchors, LineageQueueStats, LineageRecoveryEvent
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import RuntimeRetentionHistoryEntry, RuntimeRetentionHistorySnapshot
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
from app.services.runtime_status_service import build_runtime_status_snapshot


@pytest.fixture(autouse=True)
def _isolate_runtime_assurance_history(mocker):
    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        side_effect=lambda **kwargs: type(
            "LeaseSnapshot",
            (),
            {
                "status": "available",
                "reason": None,
                "active_leases": (),
                "latest_reclaimed_lease": None,
                "recent_reclaimed_leases": (),
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RecoveryDrillHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    operator_id="ops-user",
                    backup_identifier="backup-123",
                    status="passed",
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_runtime_retention_history_snapshot",
        return_value=RuntimeRetentionHistorySnapshot(
            status="available",
            artifact_directory="artifacts/runtime-retention-cleanup",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RuntimeRetentionHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    operator_id="ops-user",
                    trigger_mode="scheduled",
                    job_id="retention-nightly",
                    cleanup_mode="apply",
                    status="applied",
                    retention_days=30,
                    prunable_execution_count=0,
                    prunable_compute_job_count=0,
                    prunable_async_result_count=0,
                    prunable_lineage_record_count=0,
                    prunable_lineage_artifact_count=0,
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.run_runtime_retention_cleanup",
        return_value=RuntimeRetentionCleanupSummary(
            dry_run=True,
            retention_days=30,
            cutoff_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            prunable_execution_count=0,
            prunable_compute_job_count=0,
            prunable_async_result_count=0,
            prunable_lineage_record_count=0,
            prunable_lineage_artifact_count=0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.get_lineage_storage_capacity",
        return_value=type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 700,
                "free_bytes": 300,
                "free_ratio": 0.3,
                "used_ratio": 0.7,
            },
        )(),
    )


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
                "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 2,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
        "app.services.runtime_status_service.compute_job_store.get_queue_inspection_anchors",
        return_value=ComputeQueueInspectionAnchors(
            oldest_pending_calculation_id="calc-pending",
            oldest_leased_calculation_id="calc-leased",
            oldest_running_calculation_id="calc-running",
            latest_terminal_failure_calculation_id="calc-failed",
            latest_recovered_calculation_id="calc-recovered",
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.list_recent_recoveries",
        return_value=[
            ComputeRecoveryEvent(
                calculation_id="calc-recovered",
                analytics_type="ReturnsSeries",
                recovery_kind="retryable_failure",
                recovered_at_utc="2026-03-14T00:00:00Z",
                attempt_count=1,
                error_type="RuntimeError",
            )
        ],
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        return_value=LineageQueueStats(
            pending_payload_count=6,
            leased_payload_count=1,
            retry_backlog_count=2,
            terminal_failure_count=1,
            oldest_pending_age_seconds=45.0,
            oldest_leased_age_seconds=12.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_queue_inspection_anchors",
        return_value=LineageQueueInspectionAnchors(
            oldest_pending_calculation_id="lineage-pending",
            oldest_leased_calculation_id="lineage-leased",
            latest_terminal_failure_calculation_id="lineage-failed",
            latest_recovered_calculation_id="lineage-recovered",
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.list_recent_recoveries",
        return_value=[
            LineageRecoveryEvent(
                calculation_id="lineage-recovered",
                calculation_type="TWR",
                recovery_kind="retryable_materialization_failure",
                recovered_at_utc="2026-03-14T00:00:01Z",
                attempt_count=2,
            )
        ],
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason=None,
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
    assert snapshot.compute_queue.inspection_anchors is not None
    assert snapshot.compute_queue.inspection_anchors.oldest_running_calculation_id == "calc-running"
    assert snapshot.compute_queue.inspection_anchors.latest_recovered_calculation_id == "calc-recovered"
    assert len(snapshot.compute_queue.recent_recoveries) == 1
    assert snapshot.compute_queue.recent_recoveries[0].calculation_id == "calc-recovered"
    assert snapshot.lineage_queue.status == "available"
    assert snapshot.lineage_queue.degradation_reasons == ()
    assert snapshot.lineage_queue.degradation_details == ()
    assert snapshot.lineage_queue.stats is not None
    assert snapshot.lineage_queue.stats.pending_payload_count == 6
    assert snapshot.lineage_queue.stats.leased_payload_count == 1
    assert snapshot.lineage_queue.stats.retry_backlog_count == 2
    assert snapshot.lineage_queue.inspection_anchors is not None
    assert snapshot.lineage_queue.inspection_anchors.latest_terminal_failure_calculation_id == "lineage-failed"
    assert snapshot.lineage_queue.inspection_anchors.latest_recovered_calculation_id == "lineage-recovered"
    assert len(snapshot.lineage_queue.recent_recoveries) == 1
    assert snapshot.lineage_queue.recent_recoveries[0].calculation_id == "lineage-recovered"
    assert isinstance(snapshot.generated_at, datetime)
    assert snapshot.generated_at.tzinfo == UTC
    assert snapshot.recovery_drill.status == "available"
    assert snapshot.recovery_drill.active_run_status == "available"
    assert snapshot.recovery_drill.active_run_count == 0
    assert snapshot.recovery_drill.latest_reclaimed_run_operator_id is None
    assert snapshot.recovery_drill.reclaimed_run_count == 0
    assert snapshot.recovery_drill.latest_status is None
    assert snapshot.recovery_drill.degradation_reasons == ()
    assert snapshot.recovery_drill_policy.max_age_seconds == 0.0
    assert snapshot.recovery_drill_policy.active_run_age_seconds == 0.0
    assert snapshot.recovery_drill_policy.reclaim_count == 0
    assert snapshot.runtime_retention.status == "available"
    assert snapshot.runtime_retention.active_run_status == "available"
    assert snapshot.runtime_retention.active_run_count == 0
    assert snapshot.runtime_retention.latest_reclaimed_run_operator_id is None
    assert snapshot.runtime_retention.reclaimed_run_count == 0
    assert snapshot.runtime_retention.preview_status == "available"
    assert snapshot.runtime_retention.current_prunable_execution_count == 0
    assert snapshot.runtime_retention.latest_status == "applied"
    assert snapshot.runtime_retention_policy.active_run_age_seconds == 0.0
    assert snapshot.runtime_retention_policy.reclaim_count == 0


def test_runtime_status_snapshot_reports_active_governed_actions(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        side_effect=[
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "reason": None,
                    "active_leases": (
                        type(
                            "Lease",
                            (),
                            {
                                "operator_id": "ops-user",
                                "tenant_id": "tenant-a",
                                "governed_target": "backup-123",
                                "acquired_at_utc": "2026-03-14T00:00:00Z",
                            },
                        )(),
                    ),
                    "latest_reclaimed_lease": type(
                        "Reclaim",
                        (),
                        {
                            "operator_id": "ops-user-old",
                            "tenant_id": "tenant-a",
                            "governed_target": "backup-old",
                            "acquired_at_utc": "2026-03-13T23:00:00Z",
                            "reclaimed_at_utc": "2026-03-14T00:30:00Z",
                            "reclaim_count": 3,
                        },
                    )(),
                    "recent_reclaimed_leases": (
                        type(
                            "Reclaim",
                            (),
                            {
                                "operator_id": "ops-user-old",
                                "tenant_id": "tenant-a",
                                "governed_target": "backup-old",
                                "acquired_at_utc": "2026-03-13T23:00:00Z",
                                "reclaimed_at_utc": "2026-03-14T00:30:00Z",
                                "reclaim_count": 3,
                            },
                        )(),
                    ),
                },
            )(),
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "reason": None,
                    "active_leases": (
                        type(
                            "Lease",
                            (),
                            {
                                "operator_id": "ops-batch",
                                "tenant_id": "tenant-b",
                                "governed_target": "apply:30:retention-nightly",
                                "acquired_at_utc": "2026-03-14T01:00:00Z",
                            },
                        )(),
                        type(
                            "Lease",
                            (),
                            {
                                "operator_id": "ops-batch-2",
                                "tenant_id": "tenant-b",
                                "governed_target": "dry-run:30:no-job",
                                "acquired_at_utc": "2026-03-14T02:00:00Z",
                            },
                        )(),
                    ),
                    "latest_reclaimed_lease": type(
                        "Reclaim",
                        (),
                        {
                            "operator_id": "ops-batch-old",
                            "tenant_id": "tenant-b",
                            "governed_target": "apply:30:old-job",
                            "acquired_at_utc": "2026-03-13T22:00:00Z",
                            "reclaimed_at_utc": "2026-03-14T01:30:00Z",
                            "reclaim_count": 4,
                        },
                    )(),
                    "recent_reclaimed_leases": (
                        type(
                            "Reclaim",
                            (),
                            {
                                "operator_id": "ops-batch-old",
                                "tenant_id": "tenant-b",
                                "governed_target": "apply:30:old-job",
                                "acquired_at_utc": "2026-03-13T22:00:00Z",
                                "reclaimed_at_utc": "2026-03-14T01:30:00Z",
                                "reclaim_count": 4,
                            },
                        )(),
                    ),
                },
            )(),
        ],
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.recovery_drill.active_run_status == "active"
    assert snapshot.recovery_drill.active_run_count == 1
    assert snapshot.recovery_drill.oldest_active_run_operator_id == "ops-user"
    assert snapshot.recovery_drill.oldest_active_run_governed_target == "backup-123"
    assert snapshot.recovery_drill.oldest_active_run_age_seconds is not None
    assert snapshot.recovery_drill.latest_reclaimed_run_operator_id == "ops-user-old"
    assert snapshot.recovery_drill.latest_reclaimed_run_governed_target == "backup-old"
    assert snapshot.recovery_drill.latest_reclaimed_run_age_seconds is not None
    assert snapshot.recovery_drill.reclaimed_run_count == 3
    assert snapshot.recovery_drill.recent_reclaimed_runs[0].operator_id == "ops-user-old"
    assert snapshot.runtime_retention.active_run_status == "active"
    assert snapshot.runtime_retention.active_run_count == 2
    assert snapshot.runtime_retention.oldest_active_run_operator_id == "ops-batch"
    assert snapshot.runtime_retention.oldest_active_run_governed_target == "apply:30:retention-nightly"
    assert snapshot.runtime_retention.latest_reclaimed_run_operator_id == "ops-batch-old"
    assert snapshot.runtime_retention.latest_reclaimed_run_governed_target == "apply:30:old-job"
    assert snapshot.runtime_retention.reclaimed_run_count == 4
    assert snapshot.runtime_retention.recent_reclaimed_runs[0].operator_id == "ops-batch-old"


def test_runtime_status_snapshot_degrades_when_runtime_retention_is_stale_or_not_applied(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 60.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_runtime_retention_history_snapshot",
        return_value=RuntimeRetentionHistorySnapshot(
            status="available",
            artifact_directory="artifacts/runtime-retention-cleanup",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RuntimeRetentionHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc="2026-03-14T00:00:00Z",
                    operator_id="ops-user",
                    trigger_mode="scheduled",
                    job_id="retention-nightly",
                    cleanup_mode="dry_run",
                    status="planned",
                    retention_days=30,
                    prunable_execution_count=1,
                    prunable_compute_job_count=1,
                    prunable_async_result_count=1,
                    prunable_lineage_record_count=1,
                    prunable_lineage_artifact_count=1,
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.run_runtime_retention_cleanup",
        return_value=RuntimeRetentionCleanupSummary(
            retention_days=30,
            cutoff_utc="2026-02-13T00:00:00Z",
            dry_run=True,
            prunable_execution_count=4,
            prunable_compute_job_count=3,
            prunable_async_result_count=2,
            prunable_lineage_record_count=1,
            prunable_lineage_artifact_count=1,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_retention.status == "degraded"
    assert snapshot.runtime_retention.reason == "runtime_retention_latest_not_applied"
    assert snapshot.runtime_retention.preview_status == "available"
    assert snapshot.runtime_retention.current_prunable_execution_count == 4
    assert snapshot.runtime_retention.latest_trigger_mode == "scheduled"
    assert snapshot.runtime_retention.latest_job_id == "retention-nightly"
    assert snapshot.runtime_retention.latest_cleanup_mode == "dry_run"
    assert snapshot.runtime_retention.latest_retention_days == 30
    assert snapshot.runtime_degradation_reasons == (
        "runtime_retention:runtime_retention_latest_not_applied",
        "runtime_retention:runtime_retention_age_exceeded",
    )


def test_runtime_status_snapshot_degrades_when_governed_action_reclaim_pressure_accumulates(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 2,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 3,
                "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        side_effect=[
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "reason": None,
                    "active_leases": (),
                    "latest_reclaimed_lease": type(
                        "Reclaim",
                        (),
                        {
                            "operator_id": "ops-user-old",
                            "tenant_id": "tenant-a",
                            "governed_target": "backup-old",
                            "acquired_at_utc": "2026-03-13T23:00:00Z",
                            "reclaimed_at_utc": "2026-03-14T00:30:00Z",
                            "reclaim_count": 2,
                        },
                    )(),
                },
            )(),
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "reason": None,
                    "active_leases": (),
                    "latest_reclaimed_lease": type(
                        "Reclaim",
                        (),
                        {
                            "operator_id": "ops-batch-old",
                            "tenant_id": "tenant-b",
                            "governed_target": "apply:30:old-job",
                            "acquired_at_utc": "2026-03-13T22:00:00Z",
                            "reclaimed_at_utc": "2026-03-14T01:30:00Z",
                            "reclaim_count": 3,
                        },
                    )(),
                },
            )(),
        ],
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.recovery_drill.status == "degraded"
    assert snapshot.recovery_drill.reason == "recovery_drill_reclaim_pressure_exceeded"
    assert snapshot.recovery_drill.degradation_reasons == ("recovery_drill_reclaim_pressure_exceeded",)
    assert snapshot.recovery_drill.degradation_details[0].threshold_value == 2
    assert snapshot.recovery_drill_policy.reclaim_count == 2
    assert snapshot.runtime_retention.status == "degraded"
    assert snapshot.runtime_retention.reason == "runtime_retention_reclaim_pressure_exceeded"
    assert snapshot.runtime_retention.degradation_reasons == ("runtime_retention_reclaim_pressure_exceeded",)
    assert snapshot.runtime_retention.degradation_details[0].threshold_value == 3
    assert snapshot.runtime_retention_policy.reclaim_count == 3
    assert "recovery_drill:recovery_drill_reclaim_pressure_exceeded" in snapshot.runtime_degradation_reasons
    assert "runtime_retention:runtime_retention_reclaim_pressure_exceeded" in snapshot.runtime_degradation_reasons


def test_runtime_status_snapshot_degrades_when_governed_active_run_age_accumulates(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 60.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS": 120.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        side_effect=[
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "reason": None,
                    "active_leases": (
                        type(
                            "Lease",
                            (),
                            {
                                "operator_id": "ops-user",
                                "tenant_id": "tenant-a",
                                "governed_target": "backup-123",
                                "acquired_at_utc": "2026-03-14T00:00:00Z",
                            },
                        )(),
                    ),
                    "latest_reclaimed_lease": None,
                    "recent_reclaimed_leases": (),
                },
            )(),
            type(
                "LeaseSnapshot",
                (),
                {
                    "status": "available",
                    "reason": None,
                    "active_leases": (
                        type(
                            "Lease",
                            (),
                            {
                                "operator_id": "ops-batch",
                                "tenant_id": "tenant-b",
                                "governed_target": "apply:30:retention-nightly",
                                "acquired_at_utc": "2026-03-14T00:00:00Z",
                            },
                        )(),
                    ),
                    "latest_reclaimed_lease": None,
                    "recent_reclaimed_leases": (),
                },
            )(),
        ],
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.recovery_drill.reason == "recovery_drill_active_run_age_exceeded"
    assert snapshot.recovery_drill.degradation_reasons == ("recovery_drill_active_run_age_exceeded",)
    assert snapshot.recovery_drill.degradation_details[0].threshold_value == 60
    assert snapshot.recovery_drill_policy.active_run_age_seconds == 60.0
    assert snapshot.runtime_retention.reason == "runtime_retention_active_run_age_exceeded"
    assert snapshot.runtime_retention.degradation_reasons == ("runtime_retention_active_run_age_exceeded",)
    assert snapshot.runtime_retention.degradation_details[0].threshold_value == 120
    assert snapshot.runtime_retention_policy.active_run_age_seconds == 120.0
    assert "recovery_drill:recovery_drill_active_run_age_exceeded" in snapshot.runtime_degradation_reasons
    assert "runtime_retention:runtime_retention_active_run_age_exceeded" in snapshot.runtime_degradation_reasons


def test_runtime_status_snapshot_reports_unavailable_runtime_retention_preview(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 0.0,
                "RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_runtime_retention_history_snapshot",
        return_value=RuntimeRetentionHistorySnapshot(
            status="available",
            artifact_directory="artifacts/runtime-retention-cleanup",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.run_runtime_retention_cleanup",
        side_effect=RuntimeError("preview-failed"),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "ready"
    assert snapshot.runtime_retention.status == "available"
    assert snapshot.runtime_retention.preview_status == "unavailable"
    assert snapshot.runtime_retention.preview_reason == "RuntimeError"
    assert snapshot.runtime_retention.current_prunable_execution_count is None


def test_runtime_status_snapshot_reports_unavailable_when_recovery_history_snapshot_is_unavailable(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason="artifact_directory_unreadable",
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("recovery_drill:artifact_directory_unreadable",)
    assert snapshot.recovery_drill.status == "unavailable"
    assert snapshot.recovery_drill.reason == "artifact_directory_unreadable"
    assert snapshot.recovery_drill.latest_status is None


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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.run_runtime_retention_cleanup",
        return_value=RuntimeRetentionCleanupSummary(
            retention_days=30,
            cutoff_utc="2026-02-13T00:00:00Z",
            dry_run=True,
            prunable_execution_count=0,
            prunable_compute_job_count=0,
            prunable_async_result_count=0,
            prunable_lineage_record_count=0,
            prunable_lineage_artifact_count=0,
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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


def test_runtime_status_snapshot_reports_unavailable_when_lineage_storage_is_unavailable(mocker):
    mocker.patch(
        "app.services.runtime_status_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "LINEAGE_STORAGE_PATH": "C:/missing-lineage-storage",
                "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": False, "reason": "lineage_storage_path_missing"})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("lineage_queue:lineage_storage_path_missing",)
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.lineage_queue.reason == "lineage_storage_path_missing"
    assert snapshot.lineage_queue.stats is None


def test_runtime_status_snapshot_degrades_when_lineage_storage_free_space_is_low(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 500,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.3,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.get_lineage_storage_capacity",
        return_value=type(
            "Capacity",
            (),
            {
                "total_bytes": 1000,
                "used_bytes": 800,
                "free_bytes": 200,
                "free_ratio": 0.2,
                "used_ratio": 0.8,
            },
        )(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == (
        "lineage_queue:lineage_storage_free_bytes_below_threshold",
        "lineage_queue:lineage_storage_free_ratio_below_threshold",
    )
    assert snapshot.lineage_queue.status == "degraded"
    assert snapshot.lineage_queue.reason == "lineage_storage_free_bytes_below_threshold"
    assert snapshot.lineage_queue.storage_capacity is not None
    assert snapshot.lineage_queue.storage_capacity.free_bytes == 200
    assert snapshot.lineage_queue.storage_capacity.free_ratio == 0.2
    assert snapshot.lineage_queue_policy.storage_min_free_bytes == 500
    assert snapshot.lineage_queue_policy.storage_min_free_ratio == 0.3


def test_runtime_status_snapshot_reports_unavailable_when_lineage_storage_capacity_is_unreadable(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 0.0,
                "RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES": 0,
                "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO": 0.0,
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
    )
    mocker.patch(
        "app.services.runtime_status_service.get_lineage_storage_capacity",
        side_effect=OSError("disk usage unavailable"),
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
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("lineage_queue:lineage_storage_capacity_unreadable",)
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.lineage_queue.reason == "lineage_storage_capacity_unreadable"


def test_runtime_status_snapshot_reports_unavailable_when_lineage_queue_read_fails(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
        "app.services.runtime_status_service.compute_job_store.get_queue_inspection_anchors",
        side_effect=RuntimeError("compute anchor unavailable"),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_pending_payload_stats",
        side_effect=RuntimeError("lineage queue unavailable"),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_queue_inspection_anchors",
        side_effect=RuntimeError("lineage anchor unavailable"),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("lineage_queue:RuntimeError",)
    assert snapshot.compute_queue.status == "available"
    assert snapshot.compute_queue.inspection_anchors is None
    assert snapshot.lineage_queue.status == "unavailable"
    assert snapshot.lineage_queue.reason == "RuntimeError"
    assert snapshot.lineage_queue.inspection_anchors is None


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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 5.0,
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=1,
            retry_backlog_count=1,
            terminal_failure_count=1,
            oldest_pending_age_seconds=10.0,
            oldest_leased_age_seconds=6.0,
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
    assert snapshot.lineage_queue.reason == "lineage_leased_age_exceeded"
    assert snapshot.lineage_queue.degradation_reasons == (
        "lineage_leased_age_exceeded",
        "lineage_retry_backlog_exceeded",
        "lineage_terminal_failure_exceeded",
        "lineage_pending_age_exceeded",
    )
    assert snapshot.lineage_queue.degradation_details == (
        snapshot.runtime_degradation_details[6],
        snapshot.runtime_degradation_details[7],
        snapshot.runtime_degradation_details[8],
        snapshot.runtime_degradation_details[9],
    )
    assert snapshot.runtime_degradation_reasons == (
        "compute_queue:compute_retry_backlog_exceeded",
        "compute_queue:compute_terminal_failure_exceeded",
        "compute_queue:compute_lease_expiry_pressure_exceeded",
        "compute_queue:compute_pending_age_exceeded",
        "compute_queue:compute_leased_age_exceeded",
        "compute_queue:compute_running_age_exceeded",
        "lineage_queue:lineage_leased_age_exceeded",
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
        "lineage_leased_age_exceeded",
        "lineage_retry_backlog_exceeded",
        "lineage_terminal_failure_exceeded",
        "lineage_pending_age_exceeded",
    )


def test_runtime_status_snapshot_degrades_when_lineage_leased_age_threshold_is_exceeded(mocker):
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
                "RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS": 10.0,
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
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=1,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=20.0,
            oldest_leased_age_seconds=15.0,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("lineage_queue:lineage_leased_age_exceeded",)
    assert snapshot.runtime_degradation_details[0].reason == "lineage_leased_age_exceeded"
    assert snapshot.lineage_queue.reason == "lineage_leased_age_exceeded"


def test_runtime_status_snapshot_degrades_when_recovery_drill_is_stale(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 60.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RecoveryDrillHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc="2026-03-13T00:00:00Z",
                    operator_id="ops-user",
                    backup_identifier="backup-123",
                    status="passed",
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("recovery_drill:recovery_drill_age_exceeded",)
    assert snapshot.recovery_drill.status == "degraded"
    assert snapshot.recovery_drill.reason == "recovery_drill_age_exceeded"
    assert snapshot.recovery_drill.latest_status == "passed"
    assert snapshot.recovery_drill.latest_age_seconds is not None
    assert snapshot.recovery_drill.latest_age_seconds > 60.0
    assert snapshot.recovery_drill_policy.max_age_seconds == 60.0


def test_runtime_status_snapshot_degrades_when_latest_recovery_drill_failed(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="available",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name="latest.json",
            retained_file_names=["latest.json"],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[
                RecoveryDrillHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    operator_id="ops-user",
                    backup_identifier="backup-123",
                    status="failed",
                )
            ],
            total_entries=1,
            matched_entries=1,
            returned_entries=1,
            next_offset=None,
            applied_filters={},
            reason=None,
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("recovery_drill:recovery_drill_latest_not_passed",)
    assert snapshot.recovery_drill.status == "degraded"
    assert snapshot.recovery_drill.reason == "recovery_drill_latest_not_passed"


def test_runtime_status_snapshot_reports_unavailable_when_recovery_history_read_raises(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 0.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        side_effect=RuntimeError("history read failed"),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("recovery_drill:RuntimeError",)
    assert snapshot.recovery_drill.status == "unavailable"
    assert snapshot.recovery_drill.reason == "RuntimeError"


def test_runtime_status_snapshot_degrades_when_missing_recovery_history_exceeds_policy(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 60.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
            leased_payload_count=0,
            retry_backlog_count=0,
            terminal_failure_count=0,
            oldest_pending_age_seconds=0.0,
            oldest_leased_age_seconds=0.0,
        ),
    )
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason="recovery_drill_artifact_directory_missing",
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("recovery_drill:recovery_drill_history_unavailable",)
    assert snapshot.recovery_drill.status == "degraded"
    assert snapshot.recovery_drill.reason == "recovery_drill_history_unavailable"
    assert snapshot.recovery_drill.latest_age_seconds is None


def test_runtime_status_snapshot_degrades_when_recovery_drill_history_is_required_but_missing(mocker):
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
                "RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS": 60.0,
            },
        )(),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_durable_metadata_store_ready",
        return_value=DurabilityHealthStatus(is_ready=True, status="ready", reason=None),
    )
    mocker.patch(
        "app.services.runtime_status_service.check_lineage_storage_ready",
        return_value=type("StorageStatus", (), {"is_ready": True, "reason": None})(),
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
    mocker.patch(
        "app.services.runtime_status_service.build_recovery_drill_history_snapshot",
        return_value=RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory="artifacts/durable-recovery-drill",
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=30,
            retention_max_age_days=90,
            entries=[],
            total_entries=0,
            matched_entries=0,
            returned_entries=0,
            next_offset=None,
            applied_filters={},
            reason="manifest_missing",
        ),
    )

    snapshot = build_runtime_status_snapshot(is_draining=False)

    assert snapshot.runtime_status == "degraded"
    assert snapshot.runtime_degradation_reasons == ("recovery_drill:manifest_missing",)
    assert snapshot.recovery_drill.status == "unavailable"
    assert snapshot.recovery_drill.reason == "manifest_missing"
    assert snapshot.recovery_drill.degradation_reasons == ()
    assert snapshot.recovery_drill.degradation_details == ()
    assert snapshot.recovery_drill.latest_generated_at_utc is None


def test_runtime_status_unavailable_recovery_drill_helper_preserves_action_context():
    active_run_status = runtime_status_service.OperatorActionStatus(
        status="available",
        reason=None,
        active_run_count=1,
        oldest_active_run_operator_id="ops-user",
        oldest_active_run_tenant_id="tenant-a",
        oldest_active_run_governed_target="durable-recovery-drill",
        oldest_active_run_acquired_at_utc="2026-05-31T00:00:00Z",
        oldest_active_run_age_seconds=45.0,
        latest_reclaimed_run_operator_id="ops-prior",
        latest_reclaimed_run_tenant_id="tenant-b",
        latest_reclaimed_run_governed_target="durable-recovery-drill",
        latest_reclaimed_run_acquired_at_utc="2026-05-30T23:00:00Z",
        latest_reclaimed_run_reclaimed_at_utc="2026-05-30T23:30:00Z",
        latest_reclaimed_run_age_seconds=1800.0,
        reclaimed_run_count=2,
        recent_reclaimed_runs=(),
    )

    status = runtime_status_service._build_unavailable_recovery_drill_status(
        reason="RuntimeError",
        active_run_status=active_run_status,
    )

    assert status.status == "unavailable"
    assert status.reason == "RuntimeError"
    assert status.active_run_count == 1
    assert status.oldest_active_run_operator_id == "ops-user"
    assert status.oldest_active_run_age_seconds == 45.0
    assert status.latest_reclaimed_run_operator_id == "ops-prior"
    assert status.reclaimed_run_count == 2
    assert status.latest_generated_at_utc is None
    assert status.degradation_reasons == ()
    assert status.degradation_details == ()


def test_runtime_status_safe_recent_recoveries_return_empty_on_disabled_limit_and_errors(mocker):
    settings = type("Settings", (), {"RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 0})()
    assert runtime_status_service._safe_compute_recent_recoveries(settings=settings) == ()
    assert runtime_status_service._safe_lineage_recent_recoveries(settings=settings) == ()

    error_settings = type("Settings", (), {"RUNTIME_STATUS_RECENT_RECOVERY_LIMIT": 2})()
    mocker.patch(
        "app.services.runtime_status_service.compute_job_store.list_recent_recoveries",
        side_effect=RuntimeError("boom"),
    )
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.list_recent_recoveries",
        side_effect=RuntimeError("boom"),
    )
    assert runtime_status_service._safe_compute_recent_recoveries(settings=error_settings) == ()
    assert runtime_status_service._safe_lineage_recent_recoveries(settings=error_settings) == ()


def test_runtime_status_safe_lineage_inspection_anchor_returns_none_on_error(mocker):
    mocker.patch(
        "app.services.runtime_status_service.lineage_metadata_store.get_queue_inspection_anchors",
        side_effect=RuntimeError("boom"),
    )

    assert runtime_status_service._safe_lineage_queue_inspection_anchors() is None


def test_runtime_status_build_missing_runtime_retention_status_degrades_when_threshold_present():
    active_run_status = type(
        "ActionStatus",
        (),
        {
            "status": "available",
            "reason": None,
            "active_run_count": 0,
            "oldest_active_run_operator_id": None,
            "oldest_active_run_tenant_id": None,
            "oldest_active_run_governed_target": None,
            "oldest_active_run_acquired_at_utc": None,
            "oldest_active_run_age_seconds": None,
            "latest_reclaimed_run_operator_id": None,
            "latest_reclaimed_run_tenant_id": None,
            "latest_reclaimed_run_governed_target": None,
            "latest_reclaimed_run_acquired_at_utc": None,
            "latest_reclaimed_run_reclaimed_at_utc": None,
            "latest_reclaimed_run_age_seconds": None,
            "reclaimed_run_count": 0,
            "recent_reclaimed_runs": (),
        },
    )()

    status = runtime_status_service._build_missing_runtime_retention_status(
        threshold=300.0,
        active_run_status=active_run_status,
        preview_status="available",
        preview_reason=None,
        preview_summary=None,
    )

    assert status.status == "degraded"
    assert status.degradation_reasons == ("runtime_retention_history_unavailable",)


def test_runtime_status_unavailable_runtime_retention_helper_preserves_preview_and_action_context():
    active_run_status = runtime_status_service.OperatorActionStatus(
        status="available",
        reason=None,
        active_run_count=1,
        oldest_active_run_operator_id="ops-user",
        oldest_active_run_tenant_id="tenant-a",
        oldest_active_run_governed_target="runtime-retention-cleanup",
        oldest_active_run_acquired_at_utc="2026-05-31T00:00:00Z",
        oldest_active_run_age_seconds=45.0,
        latest_reclaimed_run_operator_id=None,
        latest_reclaimed_run_tenant_id=None,
        latest_reclaimed_run_governed_target=None,
        latest_reclaimed_run_acquired_at_utc=None,
        latest_reclaimed_run_reclaimed_at_utc=None,
        latest_reclaimed_run_age_seconds=None,
        reclaimed_run_count=0,
        recent_reclaimed_runs=(),
    )
    preview_summary = RuntimeRetentionCleanupSummary(
        dry_run=True,
        retention_days=30,
        cutoff_utc="2026-05-01T00:00:00Z",
        prunable_execution_count=2,
        prunable_compute_job_count=3,
        prunable_async_result_count=4,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=6,
    )

    status = runtime_status_service._build_unavailable_runtime_retention_status(
        reason="history_snapshot_unavailable",
        active_run_status=active_run_status,
        preview_status="available",
        preview_reason=None,
        preview_summary=preview_summary,
    )

    assert status.status == "unavailable"
    assert status.reason == "history_snapshot_unavailable"
    assert status.active_run_count == 1
    assert status.oldest_active_run_operator_id == "ops-user"
    assert status.preview_status == "available"
    assert status.current_cutoff_utc == "2026-05-01T00:00:00Z"
    assert status.current_retention_days == 30
    assert status.current_prunable_execution_count == 2
    assert status.current_prunable_compute_job_count == 3
    assert status.current_prunable_async_result_count == 4
    assert status.current_prunable_lineage_record_count == 5
    assert status.current_prunable_lineage_artifact_count == 6
    assert status.latest_generated_at_utc is None
    assert status.degradation_reasons == ()
    assert status.degradation_details == ()


def test_runtime_status_runtime_retention_preview_fields_map_summary_counts():
    preview_summary = RuntimeRetentionCleanupSummary(
        dry_run=True,
        retention_days=45,
        cutoff_utc="2026-04-16T00:00:00Z",
        prunable_execution_count=2,
        prunable_compute_job_count=3,
        prunable_async_result_count=4,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=6,
    )

    fields = runtime_status_service._runtime_retention_preview_fields(
        preview_status="available",
        preview_reason=None,
        preview_summary=preview_summary,
    )

    assert fields.status == "available"
    assert fields.reason is None
    assert fields.cutoff_utc == "2026-04-16T00:00:00Z"
    assert fields.retention_days == 45
    assert fields.prunable_execution_count == 2
    assert fields.prunable_compute_job_count == 3
    assert fields.prunable_async_result_count == 4
    assert fields.prunable_lineage_record_count == 5
    assert fields.prunable_lineage_artifact_count == 6


def test_runtime_status_missing_history_degradation_helper_respects_threshold():
    assert runtime_status_service._missing_history_degradation(
        threshold=0.0,
        reason="runtime_retention_history_unavailable",
    ) == ((), ())

    reasons, details = runtime_status_service._missing_history_degradation(
        threshold=300.0,
        reason="runtime_retention_history_unavailable",
    )

    assert reasons == ("runtime_retention_history_unavailable",)
    assert len(details) == 1
    assert details[0].reason == "runtime_retention_history_unavailable"
    assert details[0].observed_value == Decimal("0")
    assert details[0].threshold_value == Decimal("300.0")


def test_runtime_status_operator_action_status_handles_exceptions_and_unavailable_snapshot(mocker):
    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        side_effect=RuntimeError("boom"),
    )
    unavailable = runtime_status_service._build_operator_action_status(
        artifact_directory="artifacts/runtime-retention-cleanup",
        action_name="runtime_retention_cleanup",
    )
    assert unavailable.status == "unavailable"
    assert unavailable.reason == "RuntimeError"

    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        return_value=type(
            "LeaseSnapshot",
            (),
            {
                "status": "unavailable",
                "reason": "operator_action_lease_invalid",
                "active_leases": (),
                "latest_reclaimed_lease": None,
                "recent_reclaimed_leases": (),
            },
        )(),
    )
    unavailable_snapshot = runtime_status_service._build_operator_action_status(
        artifact_directory="artifacts/runtime-retention-cleanup",
        action_name="runtime_retention_cleanup",
    )
    assert unavailable_snapshot.status == "unavailable"
    assert unavailable_snapshot.reason == "operator_action_lease_invalid"


def test_runtime_status_operator_action_status_normalizes_naive_timestamps(mocker):
    mocker.patch(
        "app.services.runtime_status_service.build_operator_action_lease_snapshot",
        return_value=type(
            "LeaseSnapshot",
            (),
            {
                "status": "available",
                "reason": None,
                "active_leases": (
                    type(
                        "Lease",
                        (),
                        {
                            "operator_id": "ops-user",
                            "tenant_id": None,
                            "governed_target": "backup-1",
                            "acquired_at_utc": "2026-03-15T00:00:00",
                        },
                    )(),
                ),
                "latest_reclaimed_lease": type(
                    "Reclaim",
                    (),
                    {
                        "operator_id": "ops-user",
                        "tenant_id": None,
                        "governed_target": "backup-1",
                        "acquired_at_utc": "2026-03-15T00:00:00Z",
                        "reclaimed_at_utc": "2026-03-15T01:00:00",
                        "reclaim_count": 1,
                    },
                )(),
                "recent_reclaimed_leases": (),
            },
        )(),
    )

    status = runtime_status_service._build_operator_action_status(
        artifact_directory="artifacts/durable-recovery-drill",
        action_name="recovery_drill",
    )

    assert status.status == "active"
    assert status.latest_reclaimed_run_age_seconds is not None
    assert status.oldest_active_run_age_seconds is not None


def test_runtime_status_collect_reasons_covers_runtime_retention_unavailable():
    reasons = runtime_status_service._collect_runtime_degradation_reasons(
        compute_queue=type("Queue", (), {"status": "available", "reason": None, "degradation_reasons": ()})(),
        lineage_queue=type("Queue", (), {"status": "available", "reason": None, "degradation_reasons": ()})(),
        recovery_drill=type("Recovery", (), {"status": "available", "reason": None, "degradation_reasons": ()})(),
        runtime_retention=type(
            "Retention",
            (),
            {"status": "unavailable", "reason": "runtime_retention_manifest_missing", "degradation_reasons": ()},
        )(),
    )

    assert reasons == ("runtime_retention:runtime_retention_manifest_missing",)


def test_runtime_status_degradation_detail_helper_uses_governed_threshold_semantics():
    details: list[runtime_status_service.RuntimeDegradationDetail] = []

    runtime_status_service._append_degradation_detail_if_breached(
        details,
        reason="disabled_threshold",
        observed_value=100,
        threshold_value=0,
    )
    runtime_status_service._append_degradation_detail_if_breached(
        details,
        reason="below_threshold",
        observed_value=9,
        threshold_value=10,
    )
    runtime_status_service._append_degradation_detail_if_breached(
        details,
        reason="at_threshold",
        observed_value=10,
        threshold_value=10,
    )

    assert len(details) == 1
    assert details[0].reason == "at_threshold"
    assert details[0].observed_value == runtime_status_service._as_decimal_number(10)
    assert details[0].threshold_value == runtime_status_service._as_decimal_number(10)


def test_runtime_status_operator_action_degradation_helper_reuses_threshold_semantics():
    details: list[runtime_status_service.RuntimeDegradationDetail] = []
    active_run_status = runtime_status_service.OperatorActionStatus(
        status="active",
        reason=None,
        active_run_count=1,
        oldest_active_run_operator_id="ops-user",
        oldest_active_run_tenant_id=None,
        oldest_active_run_governed_target="runtime-retention",
        oldest_active_run_acquired_at_utc="2026-03-15T00:00:00Z",
        oldest_active_run_age_seconds=120.0,
        latest_reclaimed_run_operator_id="ops-user",
        latest_reclaimed_run_tenant_id=None,
        latest_reclaimed_run_governed_target="runtime-retention",
        latest_reclaimed_run_acquired_at_utc="2026-03-15T00:00:00Z",
        latest_reclaimed_run_reclaimed_at_utc="2026-03-15T00:10:00Z",
        latest_reclaimed_run_age_seconds=60.0,
        reclaimed_run_count=3,
        recent_reclaimed_runs=(),
    )

    runtime_status_service._append_operator_action_degradation_details(
        details,
        active_run_status=active_run_status,
        active_run_age_threshold=60.0,
        active_run_reason="runtime_retention_active_run_age_exceeded",
        reclaim_threshold=3,
        reclaim_reason="runtime_retention_reclaim_pressure_exceeded",
    )

    assert tuple(detail.reason for detail in details) == (
        "runtime_retention_active_run_age_exceeded",
        "runtime_retention_reclaim_pressure_exceeded",
    )
    assert details[0].observed_value == runtime_status_service._as_decimal_number(120.0)
    assert details[0].threshold_value == runtime_status_service._as_decimal_number(60.0)
    assert details[1].observed_value == runtime_status_service._as_decimal_number(3)
    assert details[1].threshold_value == runtime_status_service._as_decimal_number(3)


def test_runtime_status_latest_history_age_degradation_helper_uses_governed_threshold_semantics():
    details: list[runtime_status_service.RuntimeDegradationDetail] = []

    runtime_status_service._append_latest_history_age_degradation_detail(
        details,
        reason="runtime_retention_age_exceeded",
        latest_age_seconds=59.9,
        threshold=60.0,
    )
    runtime_status_service._append_latest_history_age_degradation_detail(
        details,
        reason="runtime_retention_age_exceeded",
        latest_age_seconds=60.0,
        threshold=60.0,
    )

    assert len(details) == 1
    assert details[0].reason == "runtime_retention_age_exceeded"
    assert details[0].observed_value == runtime_status_service._as_decimal_number(60.0)
    assert details[0].threshold_value == runtime_status_service._as_decimal_number(60.0)


def test_runtime_status_lifecycle_state_degradation_helper_uses_zero_threshold_detail():
    details: list[runtime_status_service.RuntimeDegradationDetail] = []

    runtime_status_service._append_lifecycle_state_degradation_detail(
        details,
        is_healthy=True,
        reason="runtime_retention_latest_not_applied",
    )
    runtime_status_service._append_lifecycle_state_degradation_detail(
        details,
        is_healthy=False,
        reason="runtime_retention_latest_not_applied",
    )

    assert len(details) == 1
    assert details[0].reason == "runtime_retention_latest_not_applied"
    assert details[0].observed_value == runtime_status_service._as_decimal_number(0)
    assert details[0].threshold_value == runtime_status_service._as_decimal_number(0)
