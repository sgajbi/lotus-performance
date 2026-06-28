import json
import logging
from datetime import UTC, datetime

import pytest

from app.services.runtime_retention_execution_service import (
    RuntimeRetentionCleanupEvidence,
    _apply_retention_limit,
    _build_retention_manifest,
    _persist_evidence_history,
    _prune_evidence_path_if_stale,
    _prune_old_evidence,
    _retained_evidence_paths,
    _runtime_retention_cleanup_evidence,
    _runtime_retention_evidence_generated_at,
    _runtime_retention_execution_identity,
    _runtime_retention_history_policy,
    _write_text_atomic,
    execute_runtime_retention_cleanup,
)
from app.services.runtime_retention_service import RuntimeRetentionCleanupSummary


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
        operator_id=" runtime-retention-automation ",
        tenant_id=" ",
        correlation_id=" corr-1 ",
        trigger_mode=" scheduled ",
        job_id=" retention-nightly ",
    )

    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    assert evidence.trigger_mode == "scheduled"
    assert evidence.job_id == "retention-nightly"
    assert evidence.cleanup_mode == "dry_run"
    assert evidence.operator_id == "runtime-retention-automation"
    assert evidence.tenant_id is None
    assert evidence.correlation_id == "corr-1"
    assert latest["operator_id"] == "runtime-retention-automation"
    assert latest["tenant_id"] is None
    assert latest["correlation_id"] == "corr-1"
    assert latest["trigger_mode"] == "scheduled"
    assert latest["job_id"] == "retention-nightly"


def test_execute_runtime_retention_cleanup_rejects_blank_trigger_mode(tmp_path, monkeypatch):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    cleanup_called = False
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

    def _run_runtime_retention_cleanup(retention_days, dry_run):
        nonlocal cleanup_called
        cleanup_called = True
        raise AssertionError("cleanup should not run for invalid evidence identity")

    monkeypatch.setattr(
        "app.services.runtime_retention_execution_service.run_runtime_retention_cleanup",
        _run_runtime_retention_cleanup,
    )

    with pytest.raises(ValueError, match="trigger_mode must not be blank"):
        execute_runtime_retention_cleanup(
            apply=False,
            operator_id="runtime-retention-automation",
            trigger_mode=" ",
            job_id="retention-nightly",
        )

    assert not cleanup_called
    assert not output_dir.exists()


def test_execute_runtime_retention_cleanup_rejects_blank_operator_id(tmp_path, monkeypatch):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    cleanup_called = False
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

    def _run_runtime_retention_cleanup(retention_days, dry_run):
        nonlocal cleanup_called
        cleanup_called = True
        raise AssertionError("cleanup should not run for invalid evidence identity")

    monkeypatch.setattr(
        "app.services.runtime_retention_execution_service.run_runtime_retention_cleanup",
        _run_runtime_retention_cleanup,
    )

    with pytest.raises(ValueError, match="operator_id must not be blank"):
        execute_runtime_retention_cleanup(
            apply=False,
            operator_id=" ",
            trigger_mode="manual",
            job_id="retention-nightly",
        )

    assert not cleanup_called
    assert not output_dir.exists()


def test_runtime_retention_execution_identity_normalizes_operator_evidence_fields():
    identity = _runtime_retention_execution_identity(
        operator_id=" ops ",
        tenant_id=" tenant-a ",
        correlation_id=" ",
        trigger_mode=" scheduled ",
        job_id=" retention-nightly ",
    )

    assert identity.operator_id == "ops"
    assert identity.tenant_id == "tenant-a"
    assert identity.correlation_id is None
    assert identity.trigger_mode == "scheduled"
    assert identity.job_id == "retention-nightly"


def test_runtime_retention_history_policy_prefers_explicit_runtime_overrides(tmp_path):
    default_output_dir = tmp_path / "defaults"
    override_output_dir = tmp_path / "overrides"
    settings = type(
        "Settings",
        (),
        {
            "RUNTIME_RETENTION_ARTIFACT_PATH": default_output_dir,
            "RUNTIME_RETENTION_HISTORY_LIMIT": 30,
            "RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS": 90,
        },
    )()

    policy = _runtime_retention_history_policy(
        settings=settings,
        output_dir=override_output_dir,
        retention_limit=5,
        retention_max_age_days=14,
    )

    assert policy.output_dir == override_output_dir
    assert policy.retention_limit == 5
    assert policy.retention_max_age_days == 14


def test_runtime_retention_history_policy_uses_settings_defaults(tmp_path):
    default_output_dir = tmp_path / "defaults"
    settings = type(
        "Settings",
        (),
        {
            "RUNTIME_RETENTION_ARTIFACT_PATH": default_output_dir,
            "RUNTIME_RETENTION_HISTORY_LIMIT": 30,
            "RUNTIME_RETENTION_HISTORY_MAX_AGE_DAYS": 90,
        },
    )()

    policy = _runtime_retention_history_policy(
        settings=settings,
        output_dir=None,
        retention_limit=None,
        retention_max_age_days=None,
    )

    assert policy.output_dir == default_output_dir
    assert policy.retention_limit == 30
    assert policy.retention_max_age_days == 90


def test_runtime_retention_cleanup_evidence_projects_apply_summary_and_operator_identity():
    identity = _runtime_retention_execution_identity(
        operator_id="runtime-retention-operator",
        tenant_id="tenant-a",
        correlation_id="corr-123",
        trigger_mode="manual",
        job_id="runtime-retention-job-1",
    )
    summary = RuntimeRetentionCleanupSummary(
        retention_days=45,
        cutoff_utc="2026-05-14T00:00:00Z",
        dry_run=False,
        prunable_execution_count=8,
        prunable_compute_job_count=7,
        prunable_async_result_count=6,
        prunable_lineage_record_count=5,
        prunable_lineage_artifact_count=4,
    )

    evidence = _runtime_retention_cleanup_evidence(
        apply=True,
        generated_at_utc="2026-06-28T09:30:00+00:00",
        identity=identity,
        summary=summary,
    )

    assert evidence.cleanup_name == "runtime_retention_cleanup"
    assert evidence.generated_at_utc == "2026-06-28T09:30:00+00:00"
    assert evidence.evidence_file_name == "2026-06-28t09-30-00-00-00.json"
    assert evidence.operator_id == "runtime-retention-operator"
    assert evidence.tenant_id == "tenant-a"
    assert evidence.correlation_id == "corr-123"
    assert evidence.trigger_mode == "manual"
    assert evidence.job_id == "runtime-retention-job-1"
    assert evidence.cleanup_mode == "apply"
    assert evidence.status == "applied"
    assert evidence.retention_days == 45
    assert evidence.cutoff_utc == "2026-05-14T00:00:00Z"
    assert evidence.prunable_execution_count == 8
    assert evidence.prunable_compute_job_count == 7
    assert evidence.prunable_async_result_count == 6
    assert evidence.prunable_lineage_record_count == 5
    assert evidence.prunable_lineage_artifact_count == 4


def test_retained_evidence_paths_excludes_control_files_and_sorts_newest_first(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    for name in (
        "manifest.json",
        "latest.json",
        "2026-03-15t00-00-00z.json",
        "2026-03-17t00-00-00z.json",
        "2026-03-16t00-00-00z.json",
    ):
        (output_dir / name).write_text("{}", encoding="utf-8")

    retained_paths = _retained_evidence_paths(output_dir)

    assert [path.name for path in retained_paths] == [
        "2026-03-17t00-00-00z.json",
        "2026-03-16t00-00-00z.json",
        "2026-03-15t00-00-00z.json",
    ]


def test_apply_retention_limit_deletes_stale_paths_and_returns_retained_prefix(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    retained_paths = []
    for name in (
        "2026-03-17t00-00-00z.json",
        "2026-03-16t00-00-00z.json",
        "2026-03-15t00-00-00z.json",
    ):
        path = output_dir / name
        path.write_text("{}", encoding="utf-8")
        retained_paths.append(path)

    limited_paths = _apply_retention_limit(retained_paths=retained_paths, retention_limit=2)

    assert [path.name for path in limited_paths] == [
        "2026-03-17t00-00-00z.json",
        "2026-03-16t00-00-00z.json",
    ]
    assert (output_dir / "2026-03-17t00-00-00z.json").exists()
    assert (output_dir / "2026-03-16t00-00-00z.json").exists()
    assert not (output_dir / "2026-03-15t00-00-00z.json").exists()


def test_apply_retention_limit_keeps_all_paths_when_limit_is_disabled(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    retained_paths = []
    for name in ("2026-03-17t00-00-00z.json", "2026-03-16t00-00-00z.json"):
        path = output_dir / name
        path.write_text("{}", encoding="utf-8")
        retained_paths.append(path)

    limited_paths = _apply_retention_limit(retained_paths=retained_paths, retention_limit=0)

    assert limited_paths == retained_paths
    assert all(path.exists() for path in retained_paths)


def test_runtime_retention_execution_prunes_stale_history_by_limit_and_age(tmp_path, monkeypatch):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 16, tzinfo=UTC if tz is not None else None)

    monkeypatch.setattr("app.services.runtime_retention_execution_service.datetime", _FrozenDateTime)
    stale_payload = {"generated_at_utc": "2026-01-01T00:00:00Z"}
    for name in ("2026-03-15t00-00-00z.json", "2026-03-14t00-00-00z.json", "2026-03-13t00-00-00z.json"):
        payload_evidence_file_name = "../outside.json" if name == "2026-03-15t00-00-00z.json" else name
        (output_dir / name).write_text(
            json.dumps(
                {
                    "evidence_file_name": payload_evidence_file_name,
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
    assert manifest["entries"][1]["evidence_file_name"] == "2026-03-15t00-00-00z.json"
    assert not (output_dir / "2026-03-14t00-00-00z.json").exists()
    assert not (output_dir / "2026-01-01t00-00-00z.json").exists()


def test_runtime_retention_execution_skips_old_prune_when_policy_disabled(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    evidence_path = output_dir / "2026-01-01t00-00-00z.json"
    evidence_path.write_text(json.dumps({"generated_at_utc": "2026-01-01T00:00:00Z"}), encoding="utf-8")

    _prune_old_evidence(output_dir=output_dir, retention_max_age_days=0)

    assert evidence_path.exists()


def test_runtime_retention_execution_skips_invalid_old_evidence_payloads(tmp_path, caplog):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    malformed = output_dir / "bad.json"
    malformed.write_text("{not-json", encoding="utf-8")
    non_object = output_dir / "array.json"
    non_object.write_text("[]", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.services.runtime_retention_execution_service"):
        _prune_old_evidence(output_dir=output_dir, retention_max_age_days=90)

    assert malformed.exists()
    assert non_object.exists()
    assert "Runtime retention evidence ignored during age pruning" in caplog.text
    assert "bad.json" in caplog.text
    assert "array.json" in caplog.text


def test_runtime_retention_evidence_generated_at_parses_evidence_timestamp(tmp_path):
    evidence_path = tmp_path / "artifacts" / "runtime-retention-cleanup" / "evidence.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps({"generated_at_utc": "2026-03-15T00:00:00Z"}), encoding="utf-8")

    generated_at_utc = _runtime_retention_evidence_generated_at(evidence_path)

    assert generated_at_utc == datetime(2026, 3, 15, tzinfo=UTC)


def test_runtime_retention_evidence_generated_at_warns_and_skips_invalid_payload(tmp_path, caplog):
    evidence_path = tmp_path / "artifacts" / "runtime-retention-cleanup" / "evidence.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps({"missing_generated_at": "2026-03-15T00:00:00Z"}), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.services.runtime_retention_execution_service"):
        generated_at_utc = _runtime_retention_evidence_generated_at(evidence_path)

    assert generated_at_utc is None
    assert "Runtime retention evidence ignored during age pruning" in caplog.text
    assert "evidence.json" in caplog.text


def test_prune_evidence_path_if_stale_preserves_control_files_and_prunes_old_evidence(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    stale = output_dir / "2026-01-01t00-00-00z.json"
    fresh = output_dir / "2026-03-15t00-00-00z.json"
    latest = output_dir / "latest.json"
    for path, generated_at_utc in (
        (stale, "2026-01-01T00:00:00Z"),
        (fresh, "2026-03-15T00:00:00Z"),
        (latest, "2026-01-01T00:00:00Z"),
    ):
        path.write_text(json.dumps({"generated_at_utc": generated_at_utc}), encoding="utf-8")

    cutoff = datetime(2026, 2, 1, tzinfo=UTC)
    _prune_evidence_path_if_stale(path=stale, cutoff=cutoff)
    _prune_evidence_path_if_stale(path=fresh, cutoff=cutoff)
    _prune_evidence_path_if_stale(path=latest, cutoff=cutoff)

    assert not stale.exists()
    assert fresh.exists()
    assert latest.exists()


def test_runtime_retention_execution_skips_invalid_manifest_entry_payloads(tmp_path, caplog):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    malformed = output_dir / "2026-03-15t00-00-00z.json"
    malformed.write_text("{not-json", encoding="utf-8")
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

    with caplog.at_level(logging.WARNING, logger="app.services.runtime_retention_execution_service"):
        _persist_evidence_history(
            output_dir=output_dir,
            evidence=evidence,
            retention_limit=5,
            retention_max_age_days=365,
        )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["latest_file_name"] == "2026-03-16t00-00-00z.json"
    assert manifest["retained_file_names"] == ["2026-03-16t00-00-00z.json"]
    assert len(manifest["entries"]) == 1
    assert manifest["entries"][0]["evidence_file_name"] == "2026-03-16t00-00-00z.json"
    assert malformed.exists()
    assert "Runtime retention evidence ignored during manifest rebuild" in caplog.text
    assert "2026-03-15t00-00-00z.json" in caplog.text


def test_runtime_retention_execution_skips_invalid_manifest_entry_shapes(tmp_path, caplog):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    invalid_shape = output_dir / "2026-03-15t00-00-00z.json"
    invalid_shape.write_text(
        json.dumps(
            {
                "evidence_file_name": "2026-03-15t00-00-00z.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": 123,
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

    with caplog.at_level(logging.WARNING, logger="app.services.runtime_retention_execution_service"):
        _persist_evidence_history(
            output_dir=output_dir,
            evidence=evidence,
            retention_limit=5,
            retention_max_age_days=365,
        )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["latest_file_name"] == "2026-03-16t00-00-00z.json"
    assert manifest["retained_file_names"] == ["2026-03-16t00-00-00z.json"]
    assert invalid_shape.exists()
    assert "Runtime retention evidence ignored during manifest rebuild" in caplog.text
    assert "2026-03-15t00-00-00z.json" in caplog.text


def test_runtime_retention_manifest_rebuild_normalizes_required_entry_identities(tmp_path):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    legacy = output_dir / "2026-03-15t00-00-00z.json"
    legacy.write_text(
        json.dumps(
            {
                "evidence_file_name": "2026-03-15t00-00-00z.json",
                "generated_at_utc": "2026-03-15T00:00:00Z",
                "operator_id": " ops ",
                "tenant_id": None,
                "correlation_id": None,
                "trigger_mode": " manual ",
                "job_id": None,
                "cleanup_mode": " dry_run ",
                "status": " planned ",
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
        retention_limit=5,
        retention_max_age_days=365,
    )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    legacy_entry = next(
        entry for entry in manifest["entries"] if entry["evidence_file_name"] == "2026-03-15t00-00-00z.json"
    )
    assert legacy_entry["operator_id"] == "ops"
    assert legacy_entry["trigger_mode"] == "manual"
    assert legacy_entry["cleanup_mode"] == "dry_run"
    assert legacy_entry["status"] == "planned"


def test_runtime_retention_manifest_builder_skips_invalid_entries_and_selects_retained_latest(tmp_path, caplog):
    output_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    output_dir.mkdir(parents=True)
    retained = output_dir / "2026-03-17t00-00-00z.json"
    retained.write_text(
        json.dumps(
            {
                "evidence_file_name": "2026-03-17t00-00-00z.json",
                "generated_at_utc": "2026-03-17T00:00:00Z",
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
    malformed = output_dir / "2026-03-16t00-00-00z.json"
    malformed.write_text("{not-json", encoding="utf-8")
    evidence = RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-15T00:00:00Z",
        evidence_file_name="2026-03-15t00-00-00z.json",
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

    with caplog.at_level(logging.WARNING, logger="app.services.runtime_retention_execution_service"):
        manifest = _build_retention_manifest(
            evidence=evidence,
            retained_paths=[retained, malformed],
            retention_limit=2,
            retention_max_age_days=90,
        )

    assert manifest.latest_file_name == "2026-03-17t00-00-00z.json"
    assert manifest.retained_file_names == ["2026-03-17t00-00-00z.json"]
    assert [entry.evidence_file_name for entry in manifest.entries] == ["2026-03-17t00-00-00z.json"]
    assert "Runtime retention evidence ignored during manifest rebuild" in caplog.text
    assert "2026-03-16t00-00-00z.json" in caplog.text


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
