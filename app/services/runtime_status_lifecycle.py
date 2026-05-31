from __future__ import annotations

from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary
from app.services.runtime_status_degradation import missing_history_degradation
from app.services.runtime_status_domain import OperatorActionStatus, RecoveryDrillStatus, RuntimeRetentionStatus
from app.services.runtime_status_operator_action import operator_action_status_fields
from app.services.runtime_status_retention_preview import runtime_retention_preview_fields


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
