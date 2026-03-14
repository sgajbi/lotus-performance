import json

from app.services.runtime_retention_execution_service import execute_runtime_retention_cleanup


def test_execute_runtime_retention_cleanup_persists_scheduled_evidence(tmp_path, monkeypatch):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    monkeypatch.setattr(
        "app.services.runtime_retention_execution_service.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "RUNTIME_RETENTION_ARTIFACT_PATH": output_dir,
                "RUNTIME_RETENTION_HISTORY_LIMIT": 30,
                "RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS": 90,
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_execution_service.run_runtime_retention_cleanup",
        lambda retention_days, dry_run: type(
            "Summary",
            (),
            {
                "retention_days": 30,
                "cutoff_utc": "2026-02-13T00:00:00Z",
                "prunable_execution_count": 4,
                "prunable_compute_job_count": 3,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 1,
                "prunable_lineage_artifact_count": 1,
            },
        )(),
    )

    evidence = execute_runtime_retention_cleanup(
        apply=False,
        operator_id="runtime-retention-automation",
        trigger_mode="scheduled",
        job_id="retention-nightly",
    )

    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert evidence.trigger_mode == "scheduled"
    assert evidence.job_id == "retention-nightly"
    assert evidence.cleanup_mode == "dry_run"
    assert latest["operator_id"] == "runtime-retention-automation"
    assert latest["trigger_mode"] == "scheduled"
    assert latest["job_id"] == "retention-nightly"
