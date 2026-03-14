import json

import pytest

from app.services.runtime_retention_execution_service import (
    RuntimeRetentionCleanupEvidence,
    _persist_evidence_history,
    _prune_old_evidence,
    _write_text_atomic,
    execute_runtime_retention_cleanup,
)


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


def test_runtime_retention_execution_prunes_stale_history_by_limit_and_age(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    stale_payload = {"generated_at_utc": "2026-01-01T00:00:00Z"}
    for name in ("2026-03-15t00-00-00z.json", "2026-03-14t00-00-00z.json", "2026-03-13t00-00-00z.json"):
        (output_dir / name).write_text(
            json.dumps(
                {
                    "evidence_file_name": name,
                    "generated_at_utc": "2026-03-15T00:00:00Z",
                    "operator_id": "ops",
                    "tenant_id": None,
                    "correlation_id": None,
                    "trigger_mode": "manual",
                    "job_id": None,
                    "cleanup_mode": "dry_run",
                    "status": "planned",
                    "retention_days": 30,
                    "prunable_execution_count": 1,
                    "prunable_compute_job_count": 1,
                    "prunable_async_result_count": 1,
                    "prunable_lineage_record_count": 1,
                    "prunable_lineage_artifact_count": 1,
                }
            ),
            encoding="utf-8",
        )
    (output_dir / "2026-01-01t00-00-00z.json").write_text(json.dumps(stale_payload), encoding="utf-8")

    evidence = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-16T00:00:00Z",
        evidence_file_name="2026-03-16t00-00-00z.json",
        operator_id="ops",
        tenant_id=None,
        correlation_id=None,
        trigger_mode="manual",
        job_id=None,
        cleanup_mode="dry_run",
        status="planned",
        retention_days=30,
        cutoff_utc="2026-02-15T00:00:00Z",
        prunable_execution_count=1,
        prunable_compute_job_count=1,
        prunable_async_result_count=1,
        prunable_lineage_record_count=1,
        prunable_lineage_artifact_count=1,
    )

    _persist_evidence_history(
        output_dir=output_dir,
        evidence=evidence,
        retention_limit=2,
        retention_max_age_days=30,
    )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["retained_file_names"] == ["2026-03-16t00-00-00z.json", "2026-03-15t00-00-00z.json"]
    assert not (output_dir / "2026-03-14t00-00-00z.json").exists()
    assert not (output_dir / "2026-01-01t00-00-00z.json").exists()


def test_runtime_retention_execution_skips_old_prune_when_policy_disabled(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    evidence_path = output_dir / "2026-01-01t00-00-00z.json"
    evidence_path.write_text(json.dumps({"generated_at_utc": "2026-01-01T00:00:00Z"}), encoding="utf-8")

    _prune_old_evidence(output_dir=output_dir, retention_max_age_days=0)

    assert evidence_path.exists()


def test_runtime_retention_execution_skips_invalid_old_evidence_payloads(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    malformed = output_dir / "bad.json"
    malformed.write_text("{not-json", encoding="utf-8")

    _prune_old_evidence(output_dir=output_dir, retention_max_age_days=90)

    assert malformed.exists()


def test_runtime_retention_execution_atomic_write_cleans_up_temp_file_on_replace_failure(tmp_path, monkeypatch):
    output_path = tmp_path / "artifacts" / "runtime-retention-cleanup" / "latest.json"
    original_replace = type(output_path).replace
    captured_temp_paths: list[type(output_path)] = []

    def _failing_replace(self, target):
        if self.suffix == ".tmp":
            captured_temp_paths.append(self)
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(type(output_path), "replace", _failing_replace)

    with pytest.raises(OSError, match="replace failed"):
        _write_text_atomic(output_path, '{"ok": true}')

    assert captured_temp_paths
    assert not output_path.exists()
    assert all(not temp_path.exists() for temp_path in captured_temp_paths)
