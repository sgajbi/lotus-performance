from app.services import runtime_status_retention_preview
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary


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

    fields = runtime_status_retention_preview.runtime_retention_preview_fields(
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


def test_runtime_status_runtime_retention_preview_fields_map_missing_summary_to_empty_counts():
    fields = runtime_status_retention_preview.runtime_retention_preview_fields(
        preview_status="unavailable",
        preview_reason="RuntimeError",
        preview_summary=None,
    )

    assert fields.status == "unavailable"
    assert fields.reason == "RuntimeError"
    assert fields.cutoff_utc is None
    assert fields.retention_days is None
    assert fields.prunable_execution_count is None
    assert fields.prunable_compute_job_count is None
    assert fields.prunable_async_result_count is None
    assert fields.prunable_lineage_record_count is None
    assert fields.prunable_lineage_artifact_count is None


def test_runtime_status_runtime_retention_preview_reports_unavailable_dependency(mocker, caplog):
    mocker.patch(
        "app.services.runtime_status_retention_preview.run_runtime_retention_cleanup",
        side_effect=RuntimeError("boom"),
    )

    with caplog.at_level("WARNING", logger="app.services.runtime_status_retention_preview"):
        status, reason, summary = runtime_status_retention_preview.build_runtime_retention_preview()

    assert status == "unavailable"
    assert reason == "RuntimeError"
    assert summary is None
    assert "Runtime retention preview unavailable while running dry-run cleanup." in caplog.text
