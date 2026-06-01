from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.services.operator_action_guard_service import (
    _find_latest_recovery_drill_entry,
    _find_latest_runtime_retention_entry,
    enforce_recovery_drill_manual_run_cooldown,
    enforce_runtime_retention_apply_preview,
    enforce_runtime_retention_manual_run_cooldown,
)
from app.services.recovery_drill_history_service import (
    RecoveryDrillHistoryEntry,
    RecoveryDrillHistorySnapshot,
)
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)


def test_runtime_retention_manual_run_cooldown_raises_conflict_for_recent_manual_run():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="2026-03-15t00-00-00z.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                trigger_mode="manual",
                job_id=None,
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
        applied_filters={"limit": 1, "trigger_mode": "manual"},
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_runtime_retention_manual_run_cooldown(
            snapshot,
            apply=False,
            operator_id="ops-user",
            tenant_id=None,
            retention_days=30,
            job_id=None,
            cooldown_seconds=300.0,
            now_utc=datetime(2026, 3, 15, 0, 2, 0, tzinfo=UTC),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.headers == {"Retry-After": "180"}
    assert exc_info.value.detail["code"] == "runtime_retention_manual_run_cooldown_active"


def test_recovery_drill_manual_run_cooldown_allows_when_prior_run_is_outside_window():
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory="artifacts/durable-recovery-drill",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="2026-03-15t00-00-00z.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                backup_identifier="backup-123",
                status="passed",
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 1},
    )

    enforce_recovery_drill_manual_run_cooldown(
        snapshot,
        operator_id="ops-user",
        tenant_id=None,
        backup_identifier="backup-123",
        cooldown_seconds=300.0,
        now_utc=datetime(2026, 3, 15, 0, 10, 0, tzinfo=UTC),
    )


def test_recovery_drill_manual_run_cooldown_matches_canonicalized_backup_identifier():
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory="artifacts/durable-recovery-drill",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="2026-03-15t00-00-00z.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                backup_identifier="backup-123",
                status="passed",
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 1},
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_recovery_drill_manual_run_cooldown(
            snapshot,
            operator_id="ops-user",
            tenant_id=None,
            backup_identifier=" backup-123 ",
            cooldown_seconds=300.0,
            now_utc=datetime(2026, 3, 15, 0, 2, 0, tzinfo=UTC),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "recovery_drill_manual_run_cooldown_active"


def test_runtime_retention_apply_preview_requires_recent_matching_dry_run():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="2026-03-15t00-00-00z.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id=None,
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="ticket-7",
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
        applied_filters={"limit": 100, "trigger_mode": "manual"},
    )

    enforce_runtime_retention_apply_preview(
        snapshot,
        operator_id="ops-user",
        tenant_id=None,
        retention_days=30,
        job_id=" ticket-7 ",
        preview_max_age_seconds=3600.0,
        now_utc=datetime(2026, 3, 15, 0, 30, 0, tzinfo=UTC),
    )


def test_runtime_retention_manual_run_cooldown_matches_canonicalized_job_id():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="2026-03-15t00-00-00z.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id=None,
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="ticket-7",
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
        applied_filters={"limit": 1, "trigger_mode": "manual"},
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_runtime_retention_manual_run_cooldown(
            snapshot,
            apply=False,
            operator_id="ops-user",
            tenant_id=None,
            retention_days=30,
            job_id=" ticket-7 ",
            cooldown_seconds=300.0,
            now_utc=datetime(2026, 3, 15, 0, 2, 0, tzinfo=UTC),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "runtime_retention_manual_run_cooldown_active"


def test_runtime_retention_manual_run_cooldown_clamps_future_evidence_age():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="2026-03-15t00-05-00z.json",
        retained_file_names=["2026-03-15t00-05-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="2026-03-15t00-05-00z.json",
                generated_at_utc="2026-03-15T00:05:00Z",
                operator_id="ops-user",
                tenant_id=None,
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="ticket-7",
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
        applied_filters={"limit": 1, "trigger_mode": "manual"},
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_runtime_retention_manual_run_cooldown(
            snapshot,
            apply=False,
            operator_id="ops-user",
            tenant_id=None,
            retention_days=30,
            job_id="ticket-7",
            cooldown_seconds=300.0,
            now_utc=datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC),
        )

    assert exc_info.value.headers == {"Retry-After": "300"}


def test_runtime_retention_apply_preview_rejects_missing_matching_dry_run():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name=None,
        retained_file_names=[],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[],
        total_entries=0,
        matched_entries=0,
        returned_entries=0,
        next_offset=None,
        applied_filters={"limit": 100, "trigger_mode": "manual"},
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_runtime_retention_apply_preview(
            snapshot,
            operator_id="ops-user",
            tenant_id=None,
            retention_days=30,
            job_id=None,
            preview_max_age_seconds=3600.0,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "runtime_retention_apply_preview_required"


def test_recovery_drill_manual_run_cooldown_ignores_different_backup_identifier():
    snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory="artifacts/durable-recovery-drill",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RecoveryDrillHistoryEntry(
                evidence_file_name="2026-03-15t00-00-00z.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id=None,
                correlation_id="corr-1",
                backup_identifier="backup-123",
                status="passed",
            )
        ],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={"limit": 1},
    )

    enforce_recovery_drill_manual_run_cooldown(
        snapshot,
        operator_id="ops-user",
        tenant_id=None,
        backup_identifier="backup-999",
        cooldown_seconds=300.0,
        now_utc=datetime(2026, 3, 15, 0, 2, 0, tzinfo=UTC),
    )


def test_runtime_retention_apply_preview_skips_when_threshold_disabled():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
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
    )

    enforce_runtime_retention_apply_preview(
        snapshot,
        operator_id="ops-user",
        tenant_id=None,
        retention_days=30,
        job_id=None,
        preview_max_age_seconds=0.0,
    )


def test_runtime_retention_apply_preview_rejects_stale_preview():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="latest.json",
        retained_file_names=["latest.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="latest.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id=None,
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id=None,
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
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_runtime_retention_apply_preview(
            snapshot,
            operator_id="ops-user",
            tenant_id=None,
            retention_days=30,
            job_id=None,
            preview_max_age_seconds=60.0,
            now_utc=datetime(2026, 3, 15, 0, 5, 0, tzinfo=UTC),
        )

    assert exc_info.value.detail["latest_preview_evidence_file_name"] == "latest.json"
    assert exc_info.value.detail["preview_max_age_seconds"] == 60


def test_runtime_retention_manual_run_cooldown_ignores_mismatched_entry_shape():
    snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="latest.json",
        retained_file_names=["latest.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[
            RuntimeRetentionHistoryEntry(
                evidence_file_name="latest.json",
                generated_at_utc="2026-03-15T00:00:00Z",
                operator_id="ops-user",
                tenant_id="tenant-a",
                correlation_id="corr-1",
                trigger_mode="manual",
                job_id="job-1",
                cleanup_mode="apply",
                status="applied",
                retention_days=60,
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
    )

    enforce_runtime_retention_manual_run_cooldown(
        snapshot,
        apply=False,
        operator_id="ops-user",
        tenant_id=None,
        retention_days=30,
        job_id=None,
        cooldown_seconds=300.0,
        now_utc=datetime(2026, 3, 15, 0, 1, 0, tzinfo=UTC),
    )


def test_find_latest_helpers_and_resolvers_cover_mismatch_paths():
    retention_entry = RuntimeRetentionHistoryEntry(
        evidence_file_name="retention.json",
        generated_at_utc="2026-03-15T00:00:00Z",
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        trigger_mode="manual",
        job_id="job-1",
        cleanup_mode="dry_run",
        status="planned",
        retention_days=30,
        prunable_execution_count=1,
        prunable_compute_job_count=1,
        prunable_async_result_count=1,
        prunable_lineage_record_count=1,
        prunable_lineage_artifact_count=1,
    )
    recovery_entry = RecoveryDrillHistoryEntry(
        evidence_file_name="recovery.json",
        generated_at_utc="2026-03-15T00:00:00Z",
        operator_id="ops-user",
        tenant_id="tenant-a",
        correlation_id="corr-1",
        backup_identifier="backup-1",
        status="passed",
    )
    retention_snapshot = RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="retention.json",
        retained_file_names=["retention.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[retention_entry],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={},
    )
    recovery_snapshot = RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory="artifacts/durable-recovery-drill",
        latest_file_name="recovery.json",
        retained_file_names=["recovery.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[recovery_entry],
        total_entries=1,
        matched_entries=1,
        returned_entries=1,
        next_offset=None,
        applied_filters={},
    )

    assert (
        _find_latest_runtime_retention_entry(
            retention_snapshot,
            apply=False,
            operator_id="ops-user",
            tenant_id="tenant-b",
            retention_days=30,
            job_id="job-1",
        )
        is None
    )
    assert (
        _find_latest_recovery_drill_entry(
            recovery_snapshot,
            operator_id="ops-user",
            tenant_id="tenant-b",
            backup_identifier="backup-1",
        )
        is None
    )
