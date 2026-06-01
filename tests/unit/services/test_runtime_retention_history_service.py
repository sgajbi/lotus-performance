import json
import logging

import pytest

from app.services.operator_action_history_manifest import validate_history_manifest_payload
from app.services.runtime_retention_history_service import (
    RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON,
    RUNTIME_RETENTION_MANIFEST_INVALID_REASON,
    RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON,
    _build_applied_filters,
    _validate_manifest_entry,
    build_runtime_retention_history_snapshot,
)


def test_runtime_retention_history_reports_unavailable_when_manifest_missing(tmp_path):
    snapshot = build_runtime_retention_history_snapshot(artifact_directory=tmp_path / "missing")

    assert snapshot.status == "unavailable"
    assert snapshot.reason == RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON


def test_runtime_retention_history_reports_unavailable_when_manifest_invalid(tmp_path):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    snapshot = build_runtime_retention_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == RUNTIME_RETENTION_MANIFEST_INVALID_REASON


def test_runtime_retention_history_reports_unavailable_and_logs_invalid_manifest_shape(tmp_path, caplog):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    manifest = {
        "latest_file_name": "2026-03-15t00-00-00z.json",
        "retained_file_names": ["2026-03-15t00-00-00z.json"],
        "retention_limit": 30,
        "retention_max_age_days": 90,
        "entries": [{"generated_at_utc": "2026-03-15T00:00:00Z"}],
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="app.services.operator_action_history_manifest"):
        snapshot = build_runtime_retention_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == RUNTIME_RETENTION_MANIFEST_INVALID_REASON
    assert "Runtime retention history manifest payload invalid" in caplog.text
    assert "manifest.json" in caplog.text


def test_runtime_retention_history_reports_unavailable_when_manifest_unreadable(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "artifacts" / "runtime-retention-cleanup"
    artifact_dir.mkdir(parents=True)
    manifest_path = artifact_dir / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    original_read_text = type(manifest_path).read_text

    def _failing_read_text(self, encoding="utf-8"):
        if self == manifest_path:
            raise OSError("manifest unreadable")
        return original_read_text(self, encoding=encoding)

    monkeypatch.setattr(
        type(manifest_path),
        "read_text",
        _failing_read_text,
    )

    snapshot = build_runtime_retention_history_snapshot(artifact_directory=artifact_dir)

    assert snapshot.status == "unavailable"
    assert snapshot.reason == RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON


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
                "tenant_id": "tenant-a",
                "correlation_id": "corr-1",
                "trigger_mode": "scheduled",
                "job_id": "retention-nightly",
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
                "tenant_id": "tenant-a",
                "correlation_id": "corr-2",
                "trigger_mode": "manual",
                "job_id": None,
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
                "tenant_id": "tenant-b",
                "correlation_id": "corr-3",
                "trigger_mode": "scheduled",
                "job_id": "retention-nightly",
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
        trigger_mode="scheduled",
        job_id="retention-nightly",
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
        "trigger_mode": "scheduled",
        "job_id": "retention-nightly",
        "cleanup_mode": "apply",
        "status": "applied",
        "generated_after": "2026-03-14T00:00:00Z",
    }
    assert snapshot.entries[0].evidence_file_name == "2026-03-15t00-00-00z.json"
    assert snapshot.entries[0].tenant_id == "tenant-a"
    assert snapshot.entries[0].correlation_id == "corr-1"
    assert snapshot.entries[0].trigger_mode == "scheduled"
    assert snapshot.entries[0].job_id == "retention-nightly"


def test_runtime_retention_history_applies_generated_before_and_offset_filters(tmp_path):
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
                "operator_id": "ops-a",
                "trigger_mode": "manual",
                "job_id": None,
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
                "operator_id": "ops-b",
                "trigger_mode": "manual",
                "job_id": None,
                "cleanup_mode": "apply",
                "status": "applied",
                "retention_days": 45,
                "prunable_execution_count": 2,
                "prunable_compute_job_count": 2,
                "prunable_async_result_count": 2,
                "prunable_lineage_record_count": 2,
                "prunable_lineage_artifact_count": 2,
            },
            {
                "evidence_file_name": "2026-03-13t00-00-00z.json",
                "generated_at_utc": "2026-03-13T00:00:00Z",
                "operator_id": "ops-c",
                "trigger_mode": "manual",
                "job_id": None,
                "cleanup_mode": "apply",
                "status": "applied",
                "retention_days": 45,
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
        offset=1,
        generated_before="2026-03-14T00:00:00Z",
    )

    assert snapshot.status == "available"
    assert snapshot.matched_entries == 2
    assert snapshot.returned_entries == 1
    assert snapshot.next_offset is None
    assert snapshot.entries[0].evidence_file_name == "2026-03-13t00-00-00z.json"
    assert snapshot.applied_filters == {
        "limit": 1,
        "offset": 1,
        "generated_before": "2026-03-14T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ([], "non-dict"),
        ({"latest_file_name": 1, "retained_file_names": [], "entries": []}, "non-string latest file"),
        ({"latest_file_name": None, "retained_file_names": "bad", "entries": []}, "non-list retained"),
        (
            {"latest_file_name": None, "retained_file_names": ["ok"], "retention_limit": "bad", "entries": []},
            "non-int retention limit",
        ),
        (
            {"latest_file_name": None, "retained_file_names": ["ok"], "retention_max_age_days": "bad", "entries": []},
            "non-int retention max age",
        ),
        ({"latest_file_name": None, "retained_file_names": ["ok"], "entries": "bad"}, "non-list entries"),
        (
            {"latest_file_name": None, "retained_file_names": ["ok"], "entries": ["bad"]},
            "non-dict entry",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {"evidence_file_name": "a", "generated_at_utc": "b", "operator_id": "c", "cleanup_mode": "d"}
                ],
            },
            "missing required status field",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "a",
                        "generated_at_utc": "b",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "trigger_mode": 1,
                        "retention_days": 1,
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "non-string trigger_mode",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "evidence.json",
                        "generated_at_utc": "2026-03-15T00:00:00Z",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "trigger_mode": "   ",
                        "retention_days": 1,
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "blank trigger_mode",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "a",
                        "generated_at_utc": "b",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "tenant_id": 1,
                        "retention_days": 1,
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "non-string optional field",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "a",
                        "generated_at_utc": "b",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "retention_days": "bad",
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "non-int count field",
        ),
        (
            {
                "latest_file_name": "missing.json",
                "retained_file_names": ["ok"],
                "entries": [],
            },
            "latest file not retained",
        ),
        (
            {
                "latest_file_name": "../outside.json",
                "retained_file_names": ["../outside.json"],
                "entries": [],
            },
            "unsafe latest file name",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["nested/evidence.json"],
                "entries": [],
            },
            "unsafe retained file name",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "../outside.json",
                        "generated_at_utc": "b",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "retention_days": 1,
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "unsafe entry evidence file name",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "evidence.json",
                        "generated_at_utc": "not-a-timestamp",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "retention_days": 1,
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "invalid generated timestamp",
        ),
        (
            {
                "latest_file_name": None,
                "retained_file_names": ["ok"],
                "entries": [
                    {
                        "evidence_file_name": "evidence.json",
                        "generated_at_utc": "2026-03-15T00:00:00Z",
                        "operator_id": "c",
                        "cleanup_mode": "d",
                        "status": "ok",
                        "job_id": "   ",
                        "retention_days": 1,
                        "prunable_execution_count": 1,
                        "prunable_compute_job_count": 1,
                        "prunable_async_result_count": 1,
                        "prunable_lineage_record_count": 1,
                        "prunable_lineage_artifact_count": 1,
                    }
                ],
            },
            "blank job id",
        ),
    ],
)
def test_runtime_retention_history_manifest_validator_rejects_invalid_payloads(payload, reason):
    assert validate_history_manifest_payload(payload, validate_entry=_validate_manifest_entry) is None, reason


def test_runtime_retention_history_build_applied_filters_omits_empty_values():
    assert (
        _build_applied_filters(
            limit=None,
            offset=0,
            operator_id=None,
            trigger_mode=None,
            job_id=None,
            cleanup_mode=None,
            status_filter=None,
            generated_after=None,
            generated_before=None,
        )
        == {}
    )
