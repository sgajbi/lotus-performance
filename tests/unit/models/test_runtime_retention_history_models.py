from app.models.runtime_retention_history import build_runtime_retention_history_response
from app.services.runtime_retention_history_service import RuntimeRetentionHistoryEntry, RuntimeRetentionHistorySnapshot


def test_runtime_retention_history_response_omits_next_offset_when_absent():
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
                trigger_mode="scheduled",
                job_id="retention-nightly",
                cleanup_mode="apply",
                status="applied",
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

    response = build_runtime_retention_history_response(snapshot)
    dumped = response.model_dump(exclude_none=True)

    assert dumped["entries"][0]["cleanup_mode"] == "apply"
    assert dumped["entries"][0]["trigger_mode"] == "scheduled"
    assert dumped["entries"][0]["job_id"] == "retention-nightly"
    assert dumped["entries"][0]["prunable_execution_count"] == 1
    assert "next_offset" not in dumped
