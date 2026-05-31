from __future__ import annotations

from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary, run_runtime_retention_cleanup
from app.services.runtime_status_domain import RuntimeRetentionPreviewFields

RuntimeRetentionPreviewResult = tuple[str, str | None, RuntimeRetentionCleanupSummary | None]


def runtime_retention_preview_fields(
    *,
    preview_status: str,
    preview_reason: str | None,
    preview_summary: RuntimeRetentionCleanupSummary | None,
) -> RuntimeRetentionPreviewFields:
    return RuntimeRetentionPreviewFields(
        status=preview_status,
        reason=preview_reason,
        cutoff_utc=None if preview_summary is None else preview_summary.cutoff_utc,
        retention_days=None if preview_summary is None else preview_summary.retention_days,
        prunable_execution_count=None if preview_summary is None else preview_summary.prunable_execution_count,
        prunable_compute_job_count=None if preview_summary is None else preview_summary.prunable_compute_job_count,
        prunable_async_result_count=None if preview_summary is None else preview_summary.prunable_async_result_count,
        prunable_lineage_record_count=None
        if preview_summary is None
        else preview_summary.prunable_lineage_record_count,
        prunable_lineage_artifact_count=None
        if preview_summary is None
        else preview_summary.prunable_lineage_artifact_count,
    )


def build_runtime_retention_preview() -> RuntimeRetentionPreviewResult:
    try:
        summary = run_runtime_retention_cleanup(dry_run=True)
        return "available", None, summary
    except Exception as exc:
        return "unavailable", type(exc).__name__, None
