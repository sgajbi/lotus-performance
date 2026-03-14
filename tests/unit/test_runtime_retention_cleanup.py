import json
import sys
from datetime import UTC, datetime, timedelta

from scripts.runtime_retention_cleanup import (
    RuntimeRetentionCleanupEvidence,
    _persist_evidence_history,
    main,
)


def test_runtime_retention_cleanup_persists_history_and_manifest(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    evidence = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-14T00:00:00Z",
        evidence_file_name="2026-03-14t00-00-00z.json",
        operator_id="ops-user",
        trigger_mode="manual",
        job_id=None,
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
    assert latest["trigger_mode"] == "manual"
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
                "trigger_mode": "scheduled",
                "job_id": "retention-nightly",
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
        trigger_mode="manual",
        job_id=None,
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
        trigger_mode="scheduled",
        job_id="retention-nightly",
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


def test_runtime_retention_cleanup_scheduled_mode_records_automation_identity(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    monkeypatch.setattr(
        "scripts.runtime_retention_cleanup.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_RETENTION_ARTIFACT_PATH": output_dir,
                "RUNTIME_RETENTION_HISTORY_LIMIT": 30,
                "RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS": 90,
                "RUNTIME_RETENTION_AUTOMATION_OPERATOR_ID": "runtime-retention-automation",
                "RUNTIME_RETENTION_AUTOMATION_JOB_ID": "retention-nightly",
            },
        )(),
    )
    monkeypatch.setattr(
        "scripts.runtime_retention_cleanup.run_runtime_retention_cleanup",
        lambda retention_days, dry_run: type(
            "Summary",
            (),
            {
                "retention_days": 30,
                "cutoff_utc": "2026-02-13T00:00:00Z",
                "prunable_execution_count": 2,
                "prunable_compute_job_count": 2,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 2,
                "prunable_lineage_artifact_count": 2,
            },
        )(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runtime_retention_cleanup.py", "--scheduled", "--apply"],
    )

    main()

    captured = json.loads(capsys.readouterr().out)
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert captured["operator_id"] == "runtime-retention-automation"
    assert captured["trigger_mode"] == "scheduled"
    assert captured["job_id"] == "retention-nightly"
    assert latest["trigger_mode"] == "scheduled"
    assert latest["job_id"] == "retention-nightly"
