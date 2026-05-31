from __future__ import annotations

from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry
from app.services.runtime_retention_history_service import RuntimeRetentionHistoryEntry
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
from app.services.runtime_status_degradation import (
    append_latest_history_age_degradation_detail,
    append_lifecycle_state_degradation_detail,
    append_operator_action_degradation_details,
    lifecycle_status_from_degradation_details,
    missing_history_degradation,
)
from app.services.runtime_status_domain import (
    OperatorActionStatus,
    RecoveryDrillStatus,
    RuntimeDegradationDetail,
    RuntimeRetentionStatus,
)
from app.services.runtime_status_operator_action import operator_action_status_fields
from app.services.runtime_status_retention_preview import runtime_retention_preview_fields


def recovery_drill_status_from_latest(
    *,
    latest: RecoveryDrillHistoryEntry,
    latest_age_seconds: float,
    active_run_status: OperatorActionStatus,
    degradation_details: tuple[RuntimeDegradationDetail, ...],
) -> RecoveryDrillStatus:
    status, reason, reasons = lifecycle_status_from_degradation_details(degradation_details)
    return RecoveryDrillStatus(
        status=status,
        reason=reason,
        **operator_action_status_fields(active_run_status),
        latest_generated_at_utc=latest.generated_at_utc,
        latest_status=latest.status,
        latest_operator_id=latest.operator_id,
        latest_backup_identifier=latest.backup_identifier,
        latest_age_seconds=latest_age_seconds,
        degradation_reasons=reasons,
        degradation_details=degradation_details,
    )


def recovery_drill_degradation_details(
    *,
    latest: RecoveryDrillHistoryEntry,
    latest_age_seconds: float,
    threshold: float,
    active_run_status: OperatorActionStatus,
    active_run_age_threshold: float,
    reclaim_threshold: int,
) -> tuple[RuntimeDegradationDetail, ...]:
    details: list[RuntimeDegradationDetail] = []
    append_lifecycle_state_degradation_detail(
        details,
        is_healthy=latest.status == "passed",
        reason="recovery_drill_latest_not_passed",
    )
    append_latest_history_age_degradation_detail(
        details,
        reason="recovery_drill_age_exceeded",
        latest_age_seconds=latest_age_seconds,
        threshold=threshold,
    )
    append_operator_action_degradation_details(
        details,
        active_run_status=active_run_status,
        active_run_age_threshold=active_run_age_threshold,
        active_run_reason="recovery_drill_active_run_age_exceeded",
        reclaim_threshold=reclaim_threshold,
        reclaim_reason="recovery_drill_reclaim_pressure_exceeded",
    )
    return tuple(details)


def unavailable_recovery_drill_status(
    *,
    reason: str,
    active_run_status: OperatorActionStatus,
) -> RecoveryDrillStatus:
    return RecoveryDrillStatus(
        status="unavailable",
        reason=reason,
        **operator_action_status_fields(active_run_status),
        latest_generated_at_utc=None,
        latest_status=None,
        latest_operator_id=None,
        latest_backup_identifier=None,
        latest_age_seconds=None,
        degradation_reasons=(),
        degradation_details=(),
    )


def missing_recovery_drill_status(
    *,
    threshold: float,
    active_run_status: OperatorActionStatus,
) -> RecoveryDrillStatus:
    missing_history_reasons, details = missing_history_degradation(
        threshold=threshold,
        reason="recovery_drill_history_unavailable",
    )
    return RecoveryDrillStatus(
        status="available" if not missing_history_reasons else "degraded",
        reason=None if not missing_history_reasons else missing_history_reasons[0],
        **operator_action_status_fields(active_run_status),
        latest_generated_at_utc=None,
        latest_status=None,
        latest_operator_id=None,
        latest_backup_identifier=None,
        latest_age_seconds=None,
        degradation_reasons=missing_history_reasons,
        degradation_details=details,
    )


def unavailable_runtime_retention_status(
    *,
    reason: str,
    active_run_status: OperatorActionStatus,
    preview_status: str,
    preview_reason: str | None,
    preview_summary: RuntimeRetentionCleanupSummary | None,
) -> RuntimeRetentionStatus:
    preview_fields = runtime_retention_preview_fields(
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
    )
    return RuntimeRetentionStatus(
        status="unavailable",
        reason=reason,
        **operator_action_status_fields(active_run_status),
        preview_status=preview_fields.status,
        preview_reason=preview_fields.reason,
        current_cutoff_utc=preview_fields.cutoff_utc,
        current_retention_days=preview_fields.retention_days,
        current_prunable_execution_count=preview_fields.prunable_execution_count,
        current_prunable_compute_job_count=preview_fields.prunable_compute_job_count,
        current_prunable_async_result_count=preview_fields.prunable_async_result_count,
        current_prunable_lineage_record_count=preview_fields.prunable_lineage_record_count,
        current_prunable_lineage_artifact_count=preview_fields.prunable_lineage_artifact_count,
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
    )


def runtime_retention_status_from_latest(
    *,
    latest: RuntimeRetentionHistoryEntry,
    latest_age_seconds: float,
    active_run_status: OperatorActionStatus,
    preview_status: str,
    preview_reason: str | None,
    preview_summary: RuntimeRetentionCleanupSummary | None,
    degradation_details: tuple[RuntimeDegradationDetail, ...],
) -> RuntimeRetentionStatus:
    status, reason, reasons = lifecycle_status_from_degradation_details(degradation_details)
    preview_fields = runtime_retention_preview_fields(
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
    )
    return RuntimeRetentionStatus(
        status=status,
        reason=reason,
        **operator_action_status_fields(active_run_status),
        preview_status=preview_fields.status,
        preview_reason=preview_fields.reason,
        current_cutoff_utc=preview_fields.cutoff_utc,
        current_retention_days=preview_fields.retention_days,
        current_prunable_execution_count=preview_fields.prunable_execution_count,
        current_prunable_compute_job_count=preview_fields.prunable_compute_job_count,
        current_prunable_async_result_count=preview_fields.prunable_async_result_count,
        current_prunable_lineage_record_count=preview_fields.prunable_lineage_record_count,
        current_prunable_lineage_artifact_count=preview_fields.prunable_lineage_artifact_count,
        latest_generated_at_utc=latest.generated_at_utc,
        latest_status=latest.status,
        latest_operator_id=latest.operator_id,
        latest_trigger_mode=latest.trigger_mode,
        latest_job_id=latest.job_id,
        latest_cleanup_mode=latest.cleanup_mode,
        latest_retention_days=latest.retention_days,
        latest_age_seconds=latest_age_seconds,
        degradation_reasons=reasons,
        degradation_details=degradation_details,
    )


def missing_runtime_retention_status(
    *,
    threshold: float,
    active_run_status: OperatorActionStatus,
    preview_status: str,
    preview_reason: str | None,
    preview_summary: RuntimeRetentionCleanupSummary | None,
) -> RuntimeRetentionStatus:
    missing_history_reasons, details = missing_history_degradation(
        threshold=threshold,
        reason="runtime_retention_history_unavailable",
    )
    preview_fields = runtime_retention_preview_fields(
        preview_status=preview_status,
        preview_reason=preview_reason,
        preview_summary=preview_summary,
    )
    return RuntimeRetentionStatus(
        status="available" if not missing_history_reasons else "degraded",
        reason=None if not missing_history_reasons else missing_history_reasons[0],
        **operator_action_status_fields(active_run_status),
        preview_status=preview_fields.status,
        preview_reason=preview_fields.reason,
        current_cutoff_utc=preview_fields.cutoff_utc,
        current_retention_days=preview_fields.retention_days,
        current_prunable_execution_count=preview_fields.prunable_execution_count,
        current_prunable_compute_job_count=preview_fields.prunable_compute_job_count,
        current_prunable_async_result_count=preview_fields.prunable_async_result_count,
        current_prunable_lineage_record_count=preview_fields.prunable_lineage_record_count,
        current_prunable_lineage_artifact_count=preview_fields.prunable_lineage_artifact_count,
        latest_generated_at_utc=None,
        latest_status=None,
        latest_operator_id=None,
        latest_trigger_mode=None,
        latest_job_id=None,
        latest_cleanup_mode=None,
        latest_retention_days=None,
        latest_age_seconds=None,
        degradation_reasons=missing_history_reasons,
        degradation_details=details,
    )
