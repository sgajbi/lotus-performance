from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.runtime_retention_history import RuntimeRetentionCleanupRunRequest
from app.services.operator_action_replay_service import ActionReplayResult
from app.services.runtime_retention_execution_service import RuntimeRetentionCleanupEvidence
from app.services.runtime_retention_history_service import RuntimeRetentionHistorySnapshot
from app.services.runtime_retention_run_service import (
    RuntimeRetentionCleanupRunResult,
    _enforce_runtime_retention_manual_run_guards,
    _runtime_retention_cleanup_response_from_evidence,
    run_runtime_retention_cleanup,
)


def _build_snapshot() -> RuntimeRetentionHistorySnapshot:
    return RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory="artifacts/runtime-retention-cleanup",
        latest_file_name="2026-03-15t00-00-00z.json",
        retained_file_names=["2026-03-15t00-00-00z.json"],
        retention_limit=30,
        retention_max_age_days=90,
        entries=[],
        total_entries=0,
        matched_entries=0,
        returned_entries=0,
        next_offset=None,
        applied_filters={"limit": 100, "trigger_mode": "manual"},
    )


def _build_evidence() -> RuntimeRetentionCleanupEvidence:
    return RuntimeRetentionCleanupEvidence(
        cleanup_name="runtime_retention_cleanup",
        generated_at_utc="2026-03-15T00:00:00Z",
        evidence_file_name="2026-03-15t00-00-00z.json",
        operator_id="ops-user",
        tenant_id=None,
        correlation_id=None,
        trigger_mode="manual",
        job_id="ticket-7",
        cleanup_mode="dry_run",
        status="planned",
        retention_days=30,
        cutoff_utc="2026-03-15T00:00:00Z",
        prunable_execution_count=1,
        prunable_compute_job_count=1,
        prunable_async_result_count=1,
        prunable_lineage_record_count=1,
        prunable_lineage_artifact_count=1,
    )


def test_runtime_retention_cleanup_response_from_evidence_projects_counts_and_identity():
    response = _runtime_retention_cleanup_response_from_evidence(_build_evidence())

    assert response.cleanup_name == "runtime_retention_cleanup"
    assert response.operator_id == "ops-user"
    assert response.job_id == "ticket-7"
    assert response.cleanup_mode == "dry_run"
    assert response.status == "planned"
    assert response.prunable_execution_count == 1
    assert response.prunable_lineage_artifact_count == 1


def test_runtime_retention_manual_run_guards_skip_preview_for_dry_run(monkeypatch):
    calls = {"preview": 0, "cooldown": 0}

    def fake_preview(*args, **kwargs):
        calls["preview"] += 1

    def fake_cooldown(*args, **kwargs):
        calls["cooldown"] += 1
        assert kwargs["apply"] is False
        assert kwargs["retention_days"] == 30

    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_apply_preview",
        fake_preview,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_manual_run_cooldown",
        fake_cooldown,
    )

    _enforce_runtime_retention_manual_run_guards(
        cleanup_request=RuntimeRetentionCleanupRunRequest(apply=False, retention_days=30, job_id="ticket-7"),
        history_snapshot=_build_snapshot(),
        operator_id="ops-user",
        tenant_id=None,
        resolved_retention_days=30,
        apply_preview_max_age_seconds=3600.0,
        cooldown_seconds=300.0,
    )

    assert calls == {"preview": 0, "cooldown": 1}


def test_runtime_retention_manual_run_guards_enforce_preview_before_cooldown_for_apply(monkeypatch):
    calls = []

    def fake_preview(*args, **kwargs):
        calls.append("preview")
        assert kwargs["preview_max_age_seconds"] == 3600.0

    def fake_cooldown(*args, **kwargs):
        calls.append("cooldown")
        assert kwargs["apply"] is True

    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_apply_preview",
        fake_preview,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_manual_run_cooldown",
        fake_cooldown,
    )

    _enforce_runtime_retention_manual_run_guards(
        cleanup_request=RuntimeRetentionCleanupRunRequest(apply=True, retention_days=None, job_id="ticket-7"),
        history_snapshot=_build_snapshot(),
        operator_id="ops-user",
        tenant_id="tenant-a",
        resolved_retention_days=45,
        apply_preview_max_age_seconds=3600.0,
        cooldown_seconds=300.0,
    )

    assert calls == ["preview", "cooldown"]


def test_runtime_retention_cleanup_run_replays_existing_evidence_payload(tmp_path, monkeypatch):
    replay = ActionReplayResult(
        payload={
            "cleanup_name": "runtime_retention_cleanup",
            "generated_at_utc": "2026-03-15T00:00:00Z",
            "evidence_file_name": "2026-03-15t00-00-00z.json",
            "operator_id": "ops-user",
            "tenant_id": None,
            "correlation_id": None,
            "trigger_mode": "manual",
            "job_id": "ticket-7",
            "cleanup_mode": "dry_run",
            "status": "planned",
            "retention_days": 30,
            "cutoff_utc": "2026-03-15T00:00:00Z",
            "prunable_execution_count": 1,
            "prunable_compute_job_count": 1,
            "prunable_async_result_count": 1,
            "prunable_lineage_record_count": 1,
            "prunable_lineage_artifact_count": 1,
        },
        evidence_file_name="2026-03-15t00-00-00z.json",
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.build_runtime_retention_history_snapshot",
        lambda **kwargs: _build_snapshot(),
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.resolve_runtime_retention_manual_replay",
        lambda *args, **kwargs: replay,
    )

    result = run_runtime_retention_cleanup(
        cleanup_request=RuntimeRetentionCleanupRunRequest(apply=False, retention_days=None, job_id="ticket-7"),
        operator_id="ops-user",
        tenant_id=None,
        correlation_id="corr-1",
        artifact_directory=tmp_path,
        action_lease_stale_seconds=120.0,
        cooldown_seconds=300.0,
        apply_preview_max_age_seconds=3600.0,
        retention_days_default=30,
        now_utc=datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC),
    )

    assert result.is_replay is True
    assert isinstance(result, RuntimeRetentionCleanupRunResult)
    assert result.response.evidence_file_name == "2026-03-15t00-00-00z.json"


def test_runtime_retention_cleanup_run_executes_snapshot_and_lease_for_dry_run(tmp_path, monkeypatch):
    lease_started = {"entered": False}
    lease_closed = {"closed": False}
    lease_payload = {}

    @contextmanager
    def fake_lease(*, artifact_directory: Path, action_key: str, metadata, stale_after_seconds, now_utc):
        lease_started["entered"] = True
        lease_payload["artifact_directory"] = artifact_directory
        lease_payload["action_key"] = action_key
        lease_payload["stale_after_seconds"] = stale_after_seconds
        lease_payload["metadata"] = metadata
        lease_payload["now_utc"] = now_utc
        try:
            yield
        finally:
            lease_closed["closed"] = True

    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.build_runtime_retention_history_snapshot",
        lambda **kwargs: _build_snapshot(),
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.resolve_runtime_retention_manual_replay",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_apply_preview",
        lambda *args, **kwargs: None,
    )
    cooldown_calls = {"count": 0}

    def fake_cooldown(*args, **kwargs):
        cooldown_calls["count"] += 1

    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_manual_run_cooldown",
        fake_cooldown,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.operator_action_lease",
        fake_lease,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.build_runtime_retention_action_key",
        lambda **kwargs: "runtime-retention-ops-user-no-tenant-dry-run-30-ticket-7",
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.execute_runtime_retention_cleanup",
        lambda **kwargs: _build_evidence(),
    )

    result = run_runtime_retention_cleanup(
        cleanup_request=RuntimeRetentionCleanupRunRequest(apply=False, retention_days=30, job_id="ticket-7"),
        operator_id="ops-user",
        tenant_id=None,
        correlation_id=None,
        artifact_directory=tmp_path,
        action_lease_stale_seconds=120.0,
        cooldown_seconds=300.0,
        apply_preview_max_age_seconds=3600.0,
        retention_days_default=30,
        now_utc=datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC),
    )

    assert result.is_replay is False
    assert result.response.cleanup_mode == "dry_run"
    assert result.response.evidence_file_name == "2026-03-15t00-00-00z.json"
    assert lease_started["entered"] is True
    assert lease_closed["closed"] is True
    assert lease_payload["action_key"] == "runtime-retention-ops-user-no-tenant-dry-run-30-ticket-7"
    assert lease_payload["stale_after_seconds"] == 120.0
    assert cooldown_calls["count"] == 1


def test_runtime_retention_cleanup_run_enforces_preview_for_apply_path(tmp_path, monkeypatch):
    preview_calls = {"count": 0}
    cooldown_calls = {"count": 0}
    metadata = {}

    def fake_preview(*args, **kwargs):
        preview_calls["count"] += 1
        metadata.update(kwargs)

    @contextmanager
    def fake_lease(**kwargs):
        raise AssertionError("lease should be entered only after preview guard checks")
        yield

    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.build_runtime_retention_history_snapshot",
        lambda **kwargs: _build_snapshot(),
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.resolve_runtime_retention_manual_replay",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_apply_preview",
        fake_preview,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.enforce_runtime_retention_manual_run_cooldown",
        lambda *args, **kwargs: cooldown_calls.update({"count": cooldown_calls["count"] + 1}),
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.build_runtime_retention_action_key", lambda **kwargs: "x"
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.operator_action_lease",
        fake_lease,
    )
    monkeypatch.setattr(
        "app.services.runtime_retention_run_service.execute_runtime_retention_cleanup",
        lambda **kwargs: pytest.fail("execution should not proceed when preview guard raises"),
    )

    with pytest.raises(AssertionError):
        run_runtime_retention_cleanup(
            cleanup_request=RuntimeRetentionCleanupRunRequest(apply=True, retention_days=30, job_id="ticket-7"),
            operator_id="ops-user",
            tenant_id=None,
            correlation_id=None,
            artifact_directory=tmp_path,
            action_lease_stale_seconds=120.0,
            cooldown_seconds=300.0,
            apply_preview_max_age_seconds=3600.0,
            retention_days_default=30,
            now_utc=datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC),
        )

    assert preview_calls["count"] == 1
    assert metadata["retention_days"] == 30
