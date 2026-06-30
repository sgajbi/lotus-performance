from __future__ import annotations

import logging
from typing import Any

from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary, run_runtime_retention_cleanup
from app.services.runtime_status_diagnostics import (
    RUNTIME_RETENTION_PREVIEW_READ_FAILED,
    log_runtime_status_read_failure,
)
from app.services.runtime_status_domain import RuntimeRetentionPreviewFields

RuntimeRetentionPreviewResult = tuple[str, str | None, RuntimeRetentionCleanupSummary | None]

logger = logging.getLogger(__name__)


def runtime_retention_preview_fields(
    *,
    preview_status: str,
    preview_reason: str | None,
    preview_summary: RuntimeRetentionCleanupSummary | None,
) -> RuntimeRetentionPreviewFields:
    return RuntimeRetentionPreviewFields(
        status=preview_status,
        reason=preview_reason,
        **_runtime_retention_preview_summary_fields(preview_summary),
    )


def _runtime_retention_preview_summary_fields(
    preview_summary: RuntimeRetentionCleanupSummary | None,
) -> dict[str, Any]:
    if preview_summary is None:
        return {
            "cutoff_utc": None,
            "retention_days": None,
            "prunable_execution_count": None,
            "prunable_compute_job_count": None,
            "prunable_async_result_count": None,
            "prunable_lineage_record_count": None,
            "prunable_lineage_artifact_count": None,
        }
    return {
        "cutoff_utc": preview_summary.cutoff_utc,
        "retention_days": preview_summary.retention_days,
        "prunable_execution_count": preview_summary.prunable_execution_count,
        "prunable_compute_job_count": preview_summary.prunable_compute_job_count,
        "prunable_async_result_count": preview_summary.prunable_async_result_count,
        "prunable_lineage_record_count": preview_summary.prunable_lineage_record_count,
        "prunable_lineage_artifact_count": preview_summary.prunable_lineage_artifact_count,
    }


def build_runtime_retention_preview() -> RuntimeRetentionPreviewResult:
    try:
        summary = run_runtime_retention_cleanup(dry_run=True)
        return "available", None, summary
    except Exception as exc:
        reason = log_runtime_status_read_failure(
            logger=logger,
            component="runtime_retention",
            operation="current_preview",
            reason=RUNTIME_RETENTION_PREVIEW_READ_FAILED,
            exception=exc,
        )
        return "unavailable", reason, None
