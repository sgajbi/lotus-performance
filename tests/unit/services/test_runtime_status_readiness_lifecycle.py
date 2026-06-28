from datetime import UTC, datetime

from app.services.runtime_retention_history_service import (
    RUNTIME_RETENTION_MANIFEST_MISSING_REASON,
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
from app.services.runtime_status_domain import OperatorActionStatus, RuntimeRetentionDegradationPolicy
from app.services.runtime_status_lifecycle import (
    RUNTIME_RETENTION_HISTORY_UNAVAILABLE_REASON,
    _runtime_retention_status_from_latest_history,
    _runtime_retention_status_from_unavailable_history,
)


def _operator_action_status(*, active_run_count: int = 0) -> OperatorActionStatus:
    return OperatorActionStatus(
        status="available",
        reason=None,
        active_run_count=active_run_count,
        oldest_active_run_operator_id="ops-user" if active_run_count else None,
        oldest_active_run_tenant_id="tenant-a" if active_run_count else None,
        oldest_active_run_governed_target="runtime-assurance" if active_run_count else None,
        oldest_active_run_acquired_at_utc="2026-05-31T00:00:00Z" if active_run_count else None,
        oldest_active_run_age_seconds=45.0 if active_run_count else None,
        latest_reclaimed_run_operator_id=None,
        latest_reclaimed_run_tenant_id=None,
        latest_reclaimed_run_governed_target=None,
        latest_reclaimed_run_acquired_at_utc=None,
        latest_reclaimed_run_reclaimed_at_utc=None,
        latest_reclaimed_run_age_seconds=None,
        reclaimed_run_count=0,
        recent_reclaimed_runs=(),
    )


def _runtime_retention_policy() -> RuntimeRetentionDegradationPolicy:
    return RuntimeRetentionDegradationPolicy(
        max_age_seconds=300.0,
        active_run_age_seconds=30.0,
        reclaim_count=1,
    )


def _runtime_retention_snapshot(*, status: str, reason: str | None) -> RuntimeRetentionHistorySnapshot:
    return RuntimeRetentionHistorySnapshot(
        status=status,
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
        reason=reason,
    )


def _runtime_retention_preview_summary() -> RuntimeRetentionCleanupSummary:
    return RuntimeRetentionCleanupSummary(
        dry_run=True,
        retention_days=45,
        cutoff_utc="2026-04-16T00:00:00Z",
        prunable_execution_count=7,
        prunable_compute_job_count=8,
        prunable_async_result_count=9,
        prunable_lineage_record_count=10,
        prunable_lineage_artifact_count=11,
    )


def test_runtime_retention_readiness_unavailable_history_boundary_preserves_missing_artifact_semantics():
    status = _runtime_retention_status_from_unavailable_history(
        snapshot=_runtime_retention_snapshot(
            status="unavailable",
            reason=RUNTIME_RETENTION_MANIFEST_MISSING_REASON,
        ),
        policy=_runtime_retention_policy(),
        active_run_status=_operator_action_status(active_run_count=1),
        preview_status="available",
        preview_reason=None,
        preview_summary=_runtime_retention_preview_summary(),
    )

    assert status.status == "degraded"
    assert status.reason == RUNTIME_RETENTION_HISTORY_UNAVAILABLE_REASON
    assert status.active_run_count == 1
    assert status.preview_status == "available"
    assert status.current_retention_days == 45
    assert status.latest_generated_at_utc is None
    assert status.degradation_reasons == (RUNTIME_RETENTION_HISTORY_UNAVAILABLE_REASON,)


def test_runtime_retention_readiness_latest_history_boundary_preserves_degradation_and_preview():
    latest = RuntimeRetentionHistoryEntry(
        evidence_file_name="latest.json",
        generated_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        operator_id="ops-user",
        trigger_mode="manual",
        job_id="retention-ticket-7",
        cleanup_mode="dry_run",
        status="previewed",
        retention_days=30,
        prunable_execution_count=2,
        prunable_compute_job_count=3,
        prunable_async_result_count=4,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=6,
    )

    status = _runtime_retention_status_from_latest_history(
        latest=latest,
        policy=_runtime_retention_policy(),
        active_run_status=_operator_action_status(active_run_count=1),
        preview_status="available",
        preview_reason=None,
        preview_summary=_runtime_retention_preview_summary(),
    )

    assert status.status == "degraded"
    assert status.reason == "runtime_retention_latest_not_applied"
    assert status.active_run_count == 1
    assert status.preview_status == "available"
    assert status.current_retention_days == 45
    assert status.latest_status == "previewed"
    assert status.latest_trigger_mode == "manual"
    assert status.latest_job_id == "retention-ticket-7"
    assert status.latest_cleanup_mode == "dry_run"
    assert status.latest_age_seconds is not None
    assert status.degradation_reasons == ("runtime_retention_latest_not_applied",)
