import json

from app.services.runtime_retention_history_service import build_runtime_retention_history_snapshot


def test_runtime_retention_history_reports_unavailable_when_manifest_missing(tmp_path):
    snapshot = build_runtime_retention_history_snapshot(artifact_directory=tmp_path / "missing")

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "runtime_retention_artifact_directory_missing"


def test_runtime_retention_history_reports_unavailable_when_manifest_invalid(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    snapshot = build_runtime_retention_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == "runtime_retention_manifest_invalid"


def test_runtime_retention_history_applies_filters_and_paging(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-15t00-00-00z.json",
        "retained_file_names": [
            "2026-03-15t00-00-00z.json",
            "2026-03-14t00-00-00z.json",
            "2026-03-13t00-00-00z.json",
        ],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [
            {
                "evidence_file_name": "2026-03-15t00-00-00z.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": "ops-user",
                "cleanup_mode": "apply",
                "status": "applied",
                "retention_days": 45,
                "prunable_execution_count": 1,
                "prunable_compute_job_count": 1,
                "prunable_async_result_count": 1,
                "prunable_lineage_record_count": 1,
                "prunable_lineage_artifact_count": 1,
            },
            {
                "evidence_file_name": "2026-03-14t00-00-00z.json",
                "generated_at_utc": "2026-03-14T00:00:00Z",
                "operator_id": "ops-user",
                "cleanup_mode": "dry_run",
                "status": "planned",
                "retention_days": 30,
                "prunable_execution_count": 2,
                "prunable_compute_job_count": 2,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 2,
                "prunable_lineage_artifact_count": 2,
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00z.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-batch",
                "cleanup_mode": "apply",
                "status": "applied",
                "retention_days": 30,
                "prunable_execution_count": 3,
                "prunable_compute_job_count": 3,
                "prunable_async_result_count": 3,
                "prunable_lineage_record_count": 3,
                "prunable_lineage_artifact_count": 3,
            },
        ],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = build_runtime_retention_history_snapshot(
        artifact_directory=artifact_dir,
        limit=1,
        offset=0,
        operator_id="ops-user",
        cleanup_mode="apply",
        status_filter="applied",
        generated_after="2026-03-14T00:00:00Z",
    )

    assert snapshot.status == "available"
    assert snapshot.total_entries == 3
    assert snapshot.matched_entries == 1
    assert snapshot.returned_entries == 1
    assert snapshot.next_offset is None
    assert snapshot.applied_filters == {
        "limit": 1,
        "operator_id": "ops-user",
        "cleanup_mode": "apply",
        "status": "applied",
        "generated_after": "2026-03-14T00:00:00Z",
    }
    assert snapshot.entries[0].evidence_file_name == "2026-03-15t00-00-00z.json"
