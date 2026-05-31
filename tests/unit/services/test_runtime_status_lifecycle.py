from decimal import Decimal

from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
from app.services.runtime_status_domain import OperatorActionStatus, RuntimeDegradationDetail
from app.services.runtime_status_lifecycle import (
    missing_recovery_drill_status,
    missing_runtime_retention_status,
    recovery_drill_status_from_latest,
    unavailable_recovery_drill_status,
    unavailable_runtime_retention_status,
)


def _operator_action_status(*, active_run_count: int = 0, reclaimed_run_count: int = 0) -> OperatorActionStatus:
    return OperatorActionStatus(
        status="available",
        reason=None,
        active_run_count=active_run_count,
        oldest_active_run_operator_id="ops-user" if active_run_count else None,
        oldest_active_run_tenant_id="tenant-a" if active_run_count else None,
        oldest_active_run_governed_target="runtime-assurance" if active_run_count else None,
        oldest_active_run_acquired_at_utc="2026-05-31T00:00:00Z" if active_run_count else None,
        oldest_active_run_age_seconds=45.0 if active_run_count else None,
        latest_reclaimed_run_operator_id="ops-prior" if reclaimed_run_count else None,
        latest_reclaimed_run_tenant_id="tenant-b" if reclaimed_run_count else None,
        latest_reclaimed_run_governed_target="runtime-assurance" if reclaimed_run_count else None,
        latest_reclaimed_run_acquired_at_utc="2026-05-30T23:00:00Z" if reclaimed_run_count else None,
        latest_reclaimed_run_reclaimed_at_utc="2026-05-30T23:30:00Z" if reclaimed_run_count else None,
        latest_reclaimed_run_age_seconds=1800.0 if reclaimed_run_count else None,
        reclaimed_run_count=reclaimed_run_count,
        recent_reclaimed_runs=(),
    )


def test_recovery_drill_status_from_latest_preserves_latest_evidence_and_degradation():
    latest = RecoveryDrillHistoryEntry(
        evidence_file_name="latest.json",
        generated_at_utc="2026-05-31T00:00:00Z",
        operator_id="ops-user",
        backup_identifier="backup-123",
        status="failed",
    )
    degradation_detail = RuntimeDegradationDetail(
        reason="recovery_drill_latest_not_passed",
        observed_value=Decimal("0"),
        threshold_value=Decimal("0"),
    )

    status = recovery_drill_status_from_latest(
        latest=latest,
        latest_age_seconds=120.0,
        active_run_status=_operator_action_status(active_run_count=1),
        degradation_details=(degradation_detail,),
    )

    assert status.status == "degraded"
    assert status.reason == "recovery_drill_latest_not_passed"
    assert status.latest_generated_at_utc == "2026-05-31T00:00:00Z"
    assert status.latest_status == "failed"
    assert status.latest_operator_id == "ops-user"
    assert status.latest_backup_identifier == "backup-123"
    assert status.latest_age_seconds == 120.0
    assert status.active_run_count == 1
    assert status.degradation_reasons == ("recovery_drill_latest_not_passed",)
    assert status.degradation_details == (degradation_detail,)


def test_unavailable_recovery_drill_status_preserves_action_context():
    status = unavailable_recovery_drill_status(
        reason="RuntimeError",
        active_run_status=_operator_action_status(active_run_count=1, reclaimed_run_count=2),
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


def test_missing_recovery_drill_status_degrades_when_threshold_present():
    status = missing_recovery_drill_status(
        threshold=300.0,
        active_run_status=_operator_action_status(),
    )

    assert status.status == "degraded"
    assert status.reason == "recovery_drill_history_unavailable"
    assert status.degradation_reasons == ("recovery_drill_history_unavailable",)
    assert status.latest_generated_at_utc is None


def test_missing_runtime_retention_status_degrades_when_threshold_present():
    status = missing_runtime_retention_status(
        threshold=300.0,
        active_run_status=_operator_action_status(),
        preview_status="available",
        preview_reason=None,
        preview_summary=None,
    )

    assert status.status == "degraded"
    assert status.reason == "runtime_retention_history_unavailable"
    assert status.degradation_reasons == ("runtime_retention_history_unavailable",)


def test_unavailable_runtime_retention_status_preserves_preview_and_action_context():
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

    status = unavailable_runtime_retention_status(
        reason="history_snapshot_unavailable",
        active_run_status=_operator_action_status(active_run_count=1),
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
