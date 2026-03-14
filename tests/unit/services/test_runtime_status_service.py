from datetime import UTC, datetime

from app.services.compute_job_store import ComputeQueueInspectionAnchors, ComputeQueueStats, ComputeRecoveryEvent
from app.services.durability_health_service import DurabilityHealthStatus
from app.services.lineage_metadata_store import LineageQueueInspectionAnchors, LineageQueueStats, LineageRecoveryEvent
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import RuntimeRetentionHistoryEntry, RuntimeRetentionHistorySnapshot
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
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
    assert snapshot.recovery_drill.latest_status is None
    assert snapshot.recovery_drill.degradation_reasons == ()
    assert snapshot.recovery_drill_policy.max_age_seconds == 0.0
    assert snapshot.runtime_retention.status == "available"
    assert snapshot.runtime_retention.preview_status == "available"
    assert snapshot.runtime_retention.current_prunable_execution_count == 0
    assert snapshot.runtime_retention.latest_status is None


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
                "RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS": 60.0,
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
    assert snapshot.runtime_retention.latest_cleanup_mode == "dry_run"
    assert snapshot.runtime_retention.latest_retention_days == 30
    assert snapshot.runtime_degradation_reasons == (
        "runtime_retention:runtime_retention_latest_not_applied",
        "runtime_retention:runtime_retention_age_exceeded",
    )


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
