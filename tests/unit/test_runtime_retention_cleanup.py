import json
from datetime import UTC, datetime, timedelta

from scripts.runtime_retention_cleanup import (
    RuntimeRetentionCleanupEvidence,
    _persist_evidence_history,
)


def test_runtime_retention_cleanup_persists_history_and_manifest(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    evidence = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-14T00:00:00Z",
        evidence_file_name="2026-03-14t00-00-00z.json",
        operator_id="ops-user",
        cleanup_mode="apply",
        status="applied",
        retention_days=30,
        cutoff_utc="2026-02-13T00:00:00Z",
        prunable_execution_count=2,
        prunable_compute_job_count=3,
        prunable_async_result_count=4,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=6,
    )

    _persist_evidence_history(
        output_dir=output_dir,
        evidence=evidence,
        retention_limit=30,
        retention_max_age_days=90,
    )

    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert latest["operator_id"] == "ops-user"
    assert latest["cleanup_mode"] == "apply"
    assert manifest["latest_file_name"] == "2026-03-14t00-00-00z.json"
    assert manifest["retained_file_names"] == ["2026-03-14t00-00-00z.json"]
    assert manifest["entries"][0]["prunable_lineage_artifact_count"] == 6


def test_runtime_retention_cleanup_prunes_by_limit_and_age(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    old_generated_at = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    old_file_name = "2025-11-14t00-00-00z.json"
    (output_dir / old_file_name).write_text(
        json.dumps(
            {
                "cleanup_name": "runtime_retention_cleanup",
                "generated_at_utc": old_generated_at,
                "evidence_file_name": old_file_name,
                "operator_id": "ops-old",
                "cleanup_mode": "dry_run",
                "status": "planned",
                "retention_days": 30,
                "cutoff_utc": "2025-10-15T00:00:00Z",
                "prunable_execution_count": 1,
                "prunable_compute_job_count": 1,
                "prunable_async_result_count": 1,
                "prunable_lineage_record_count": 1,
                "prunable_lineage_artifact_count": 1,
            }
        ),
        encoding="utf-8",
    )

    first = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-14T00:00:00Z",
        evidence_file_name="2026-03-14t00-00-00z.json",
        operator_id="ops-user",
        cleanup_mode="dry_run",
        status="planned",
        retention_days=30,
        cutoff_utc="2026-02-13T00:00:00Z",
        prunable_execution_count=2,
        prunable_compute_job_count=2,
        prunable_async_result_count=2,
        prunable_lineage_record_count=2,
        prunable_lineage_artifact_count=2,
    )
    second = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-15T00:00:00Z",
        evidence_file_name="2026-03-15t00-00-00z.json",
        operator_id="ops-user",
        cleanup_mode="apply",
        status="applied",
        retention_days=45,
        cutoff_utc="2026-01-29T00:00:00Z",
        prunable_execution_count=3,
        prunable_compute_job_count=3,
        prunable_async_result_count=3,
        prunable_lineage_record_count=3,
        prunable_lineage_artifact_count=3,
    )

    _persist_evidence_history(output_dir=output_dir, evidence=first, retention_limit=2, retention_max_age_days=90)
    _persist_evidence_history(output_dir=output_dir, evidence=second, retention_limit=2, retention_max_age_days=90)

    retained_names = {
        path.name for path in output_dir.glob("*.json") if path.name not in {"latest.json", "manifest.json"}
    }
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert old_file_name not in retained_names
    assert retained_names == {"2026-03-14t00-00-00z.json", "2026-03-15t00-00-00z.json"}
    assert manifest["latest_file_name"] == "2026-03-15t00-00-00z.json"
    assert manifest["retained_file_names"] == ["2026-03-15t00-00-00z.json", "2026-03-14t00-00-00z.json"]
