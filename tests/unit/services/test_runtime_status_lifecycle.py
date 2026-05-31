from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import RuntimeRetentionHistoryEntry, RuntimeRetentionHistorySnapshot
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
from app.services.runtime_status_domain import (
    OperatorActionStatus,
    RecoveryDrillDegradationPolicy,
    RuntimeDegradationDetail,
    RuntimeRetentionDegradationPolicy,
)
from app.services.runtime_status_lifecycle import (
    build_recovery_drill_status,
    build_runtime_retention_status,
    missing_recovery_drill_status,
    missing_runtime_retention_status,
    recovery_drill_degradation_details,
    recovery_drill_operator_action_status,
    recovery_drill_status_from_latest,
    runtime_retention_degradation_details,
    runtime_retention_operator_action_status,
    runtime_retention_status_from_latest,
    unavailable_recovery_drill_status,
    unavailable_runtime_retention_status,
)


def _operator_action_status(
    *,
    status: str = "available",
    active_run_count: int = 0,
    reclaimed_run_count: int = 0,
) -> OperatorActionStatus:
    return OperatorActionStatus(
        status=status,
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


def _recovery_drill_policy(max_age_seconds: float = 300.0) -> RecoveryDrillDegradationPolicy:
    return RecoveryDrillDegradationPolicy(
        max_age_seconds=max_age_seconds,
        active_run_age_seconds=30.0,
        reclaim_count=1,
    )


def _recovery_drill_snapshot(
    *,
    status: str = "available",
    entries: list[RecoveryDrillHistoryEntry] | None = None,
    reason: str | None = None,
) -> RecoveryDrillHistorySnapshot:
    return RecoveryDrillHistorySnapshot(
        status=status,
        artifact_directory="artifacts/durable-recovery-drill",
        latest_file_name="latest.json" if entries else None,
        retained_file_names=["latest.json"] if entries else [],
        retention_limit=30,
        retention_max_age_days=90,
        entries=entries or [],
        total_entries=len(entries or []),
        matched_entries=len(entries or []),
        returned_entries=len(entries or []),
        next_offset=None,
        applied_filters={},
        reason=reason,
    )


def _runtime_retention_policy(max_age_seconds: float = 300.0) -> RuntimeRetentionDegradationPolicy:
    return RuntimeRetentionDegradationPolicy(
        max_age_seconds=max_age_seconds,
        active_run_age_seconds=30.0,
        reclaim_count=1,
    )


def _runtime_retention_snapshot(
    *,
    status: str = "available",
    entries: list[RuntimeRetentionHistoryEntry] | None = None,
    reason: str | None = None,
) -> RuntimeRetentionHistorySnapshot:
    return RuntimeRetentionHistorySnapshot(
        status=status,
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="latest.json" if entries else None,
        retained_file_names=["latest.json"] if entries else [],
        retention_limit=30,
        retention_max_age_days=90,
        entries=entries or [],
        total_entries=len(entries or []),
        matched_entries=len(entries or []),
        returned_entries=len(entries or []),
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


def test_lifecycle_operator_action_status_helpers_use_governed_defaults(mocker):
    captured_calls: list[tuple[Path, str]] = []
    returned_status = _operator_action_status()

    def fake_build_operator_action_status(*, artifact_directory: Path, action_name: str):
        captured_calls.append((artifact_directory, action_name))
        return returned_status

    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        side_effect=fake_build_operator_action_status,
    )
    settings = type("Settings", (), {})()

    recovery_status = recovery_drill_operator_action_status(settings=settings)
    retention_status = runtime_retention_operator_action_status(settings=settings)

    assert recovery_status is returned_status
    assert retention_status is returned_status
    assert captured_calls == [
        (Path("artifacts/durable-recovery-drill"), "recovery_drill"),
        (Path("artifacts/runtime-retention-cleanup"), "runtime_retention_cleanup"),
    ]


def test_build_recovery_drill_status_projects_latest_history_entry(mocker):
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        return_value=_operator_action_status(),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_recovery_drill_history_snapshot",
        return_value=_recovery_drill_snapshot(
            entries=[
                RecoveryDrillHistoryEntry(
                    evidence_file_name="latest.json",
                    generated_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    operator_id="ops-user",
                    backup_identifier="backup-123",
                    status="passed",
                )
            ],
        ),
    )

    status = build_recovery_drill_status(settings=type("Settings", (), {})(), policy=_recovery_drill_policy())

    assert status.status == "available"
    assert status.reason is None
    assert status.latest_status == "passed"
    assert status.latest_operator_id == "ops-user"
    assert status.latest_backup_identifier == "backup-123"
    assert status.latest_age_seconds is not None
    assert status.degradation_reasons == ()


def test_build_recovery_drill_status_returns_missing_when_artifacts_are_absent(mocker):
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        return_value=_operator_action_status(),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_recovery_drill_history_snapshot",
        return_value=_recovery_drill_snapshot(
            status="unavailable",
            reason="recovery_drill_manifest_missing",
        ),
    )

    status = build_recovery_drill_status(settings=type("Settings", (), {})(), policy=_recovery_drill_policy())

    assert status.status == "degraded"
    assert status.reason == "recovery_drill_history_unavailable"
    assert status.degradation_reasons == ("recovery_drill_history_unavailable",)


def test_build_recovery_drill_status_returns_unavailable_when_history_read_fails(mocker):
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        return_value=_operator_action_status(active_run_count=1),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_recovery_drill_history_snapshot",
        side_effect=RuntimeError("history read failed"),
    )

    status = build_recovery_drill_status(settings=type("Settings", (), {})(), policy=_recovery_drill_policy())

    assert status.status == "unavailable"
    assert status.reason == "RuntimeError"
    assert status.active_run_count == 1


def test_build_runtime_retention_status_projects_latest_history_and_preview(mocker):
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        return_value=_operator_action_status(),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_runtime_retention_history_snapshot",
        return_value=_runtime_retention_snapshot(
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
        ),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_runtime_retention_preview",
        return_value=("available", None, _runtime_retention_preview_summary()),
    )

    status = build_runtime_retention_status(settings=type("Settings", (), {})(), policy=_runtime_retention_policy())

    assert status.status == "available"
    assert status.reason is None
    assert status.preview_status == "available"
    assert status.current_retention_days == 45
    assert status.current_prunable_execution_count == 7
    assert status.latest_status == "applied"
    assert status.latest_job_id == "retention-nightly"
    assert status.latest_cleanup_mode == "apply"
    assert status.latest_age_seconds is not None
    assert status.degradation_reasons == ()


def test_build_runtime_retention_status_returns_missing_with_preview_when_artifacts_are_absent(mocker):
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        return_value=_operator_action_status(),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_runtime_retention_history_snapshot",
        return_value=_runtime_retention_snapshot(
            status="unavailable",
            reason="runtime_retention_manifest_missing",
        ),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_runtime_retention_preview",
        return_value=("available", None, _runtime_retention_preview_summary()),
    )

    status = build_runtime_retention_status(settings=type("Settings", (), {})(), policy=_runtime_retention_policy())

    assert status.status == "degraded"
    assert status.reason == "runtime_retention_history_unavailable"
    assert status.preview_status == "available"
    assert status.current_retention_days == 45
    assert status.degradation_reasons == ("runtime_retention_history_unavailable",)


def test_build_runtime_retention_status_returns_unavailable_when_history_read_fails(mocker):
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_operator_action_status",
        return_value=_operator_action_status(active_run_count=1),
    )
    mocker.patch(
        "app.services.runtime_status_lifecycle.build_runtime_retention_history_snapshot",
        side_effect=RuntimeError("history read failed"),
    )

    status = build_runtime_retention_status(settings=type("Settings", (), {})(), policy=_runtime_retention_policy())

    assert status.status == "unavailable"
    assert status.reason == "RuntimeError"
    assert status.active_run_count == 1
    assert status.preview_status == "unavailable"
    assert status.preview_reason == "runtime_retention_preview_unavailable"


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


def test_recovery_drill_degradation_details_collects_status_age_and_action_pressure():
    latest = RecoveryDrillHistoryEntry(
        evidence_file_name="latest.json",
        generated_at_utc="2026-05-31T00:00:00Z",
        operator_id="ops-user",
        backup_identifier="backup-123",
        status="failed",
    )

    details = recovery_drill_degradation_details(
        latest=latest,
        latest_age_seconds=600.0,
        threshold=300.0,
        active_run_status=_operator_action_status(status="active", active_run_count=1, reclaimed_run_count=2),
        active_run_age_threshold=30.0,
        reclaim_threshold=1,
    )

    assert tuple(detail.reason for detail in details) == (
        "recovery_drill_latest_not_passed",
        "recovery_drill_age_exceeded",
        "recovery_drill_active_run_age_exceeded",
        "recovery_drill_reclaim_pressure_exceeded",
    )


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


def test_runtime_retention_status_from_latest_preserves_preview_and_degradation():
    latest = RuntimeRetentionHistoryEntry(
        evidence_file_name="latest.json",
        generated_at_utc="2026-05-31T00:00:00Z",
        operator_id="ops-user",
        trigger_mode="scheduled",
        job_id="retention-nightly",
        cleanup_mode="dry_run",
        status="previewed",
        retention_days=30,
        prunable_execution_count=2,
        prunable_compute_job_count=3,
        prunable_async_result_count=4,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=6,
    )
    preview_summary = RuntimeRetentionCleanupSummary(
        dry_run=True,
        retention_days=45,
        cutoff_utc="2026-04-16T00:00:00Z",
        prunable_execution_count=7,
        prunable_compute_job_count=8,
        prunable_async_result_count=9,
        prunable_lineage_record_count=10,
        prunable_lineage_artifact_count=11,
    )
    degradation_detail = RuntimeDegradationDetail(
        reason="runtime_retention_latest_not_applied",
        observed_value=Decimal("0"),
        threshold_value=Decimal("0"),
    )

    status = runtime_retention_status_from_latest(
        latest=latest,
        latest_age_seconds=240.0,
        active_run_status=_operator_action_status(active_run_count=1),
        preview_status="available",
        preview_reason=None,
        preview_summary=preview_summary,
        degradation_details=(degradation_detail,),
    )

    assert status.status == "degraded"
    assert status.reason == "runtime_retention_latest_not_applied"
    assert status.preview_status == "available"
    assert status.current_cutoff_utc == "2026-04-16T00:00:00Z"
    assert status.current_retention_days == 45
    assert status.current_prunable_execution_count == 7
    assert status.latest_generated_at_utc == "2026-05-31T00:00:00Z"
    assert status.latest_status == "previewed"
    assert status.latest_trigger_mode == "scheduled"
    assert status.latest_job_id == "retention-nightly"
    assert status.latest_cleanup_mode == "dry_run"
    assert status.latest_retention_days == 30
    assert status.latest_age_seconds == 240.0
    assert status.active_run_count == 1
    assert status.degradation_reasons == ("runtime_retention_latest_not_applied",)
    assert status.degradation_details == (degradation_detail,)


def test_runtime_retention_degradation_details_collects_status_age_and_action_pressure():
    latest = RuntimeRetentionHistoryEntry(
        evidence_file_name="latest.json",
        generated_at_utc="2026-05-31T00:00:00Z",
        operator_id="ops-user",
        trigger_mode="scheduled",
        job_id="retention-nightly",
        cleanup_mode="dry_run",
        status="previewed",
        retention_days=30,
        prunable_execution_count=2,
        prunable_compute_job_count=3,
        prunable_async_result_count=4,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=6,
    )

    details = runtime_retention_degradation_details(
        latest=latest,
        latest_age_seconds=600.0,
        threshold=300.0,
        active_run_status=_operator_action_status(status="active", active_run_count=1, reclaimed_run_count=2),
        active_run_age_threshold=30.0,
        reclaim_threshold=1,
    )

    assert tuple(detail.reason for detail in details) == (
        "runtime_retention_latest_not_applied",
        "runtime_retention_age_exceeded",
        "runtime_retention_active_run_age_exceeded",
        "runtime_retention_reclaim_pressure_exceeded",
    )


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
