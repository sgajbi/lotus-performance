from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import runtime_retention_service
from app.services.async_result_store import AsyncResultModel, AsyncResultStore
from app.services.compute_job_store import ComputeJobStore
from app.services.execution_registry import ExecutionRegistry
from app.services.lineage_metadata_store import LineageMetadataStore, LineageRecordModel
from app.services.runtime_retention_service import RuntimeRetentionCleanupFailed, run_runtime_retention_cleanup


class _AggregatePruneStore:
    def __init__(self, count: int, *, ids: list[str] | None = None, fail_once: bool = False):
        self.ids = set(ids or [f"item-{index}" for index in range(count)])
        self.fail_once = fail_once

    @property
    def count(self) -> int:
        return len(self.ids)

    def list_terminal_job_ids_older_than(self, older_than) -> list[str]:
        return sorted(self.ids)

    def list_result_ids_older_than(self, older_than) -> list[str]:
        return sorted(self.ids)

    def prune_terminal_jobs_older_than(
        self, older_than, *, dry_run: bool = False, exclude_calculation_ids: set[str] | None = None
    ):
        return self._prune(dry_run=dry_run, exclude_calculation_ids=exclude_calculation_ids or set())

    def prune_results_older_than(
        self, older_than, *, dry_run: bool = False, exclude_calculation_ids: set[str] | None = None
    ):
        return self._prune(dry_run=dry_run, exclude_calculation_ids=exclude_calculation_ids or set())

    def _prune(self, *, dry_run: bool, exclude_calculation_ids: set[str]) -> int:
        eligible_ids = self.ids - exclude_calculation_ids
        if dry_run:
            return len(eligible_ids)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("phase unavailable")
        deleted_count = len(eligible_ids)
        self.ids -= eligible_ids
        return deleted_count


class _ExecutionIdStore:
    def __init__(self, ids: list[str]):
        self.ids = set(ids)

    def list_terminal_execution_ids_older_than(self, older_than) -> list[str]:
        return sorted(self.ids)

    def delete_executions(self, calculation_ids: list[str]) -> int:
        return self._delete(calculation_ids)

    def _delete(self, calculation_ids: list[str]) -> int:
        target_ids = set(calculation_ids)
        deleted_count = len(self.ids & target_ids)
        self.ids -= target_ids
        return deleted_count


class _LineageIdStore:
    def __init__(self, ids: list[str]):
        self.ids = set(ids)

    def list_terminal_calculation_ids_older_than(self, older_than) -> list[str]:
        return sorted(self.ids)

    def delete_calculation_ids(self, calculation_ids: list[str]) -> int:
        target_ids = set(calculation_ids)
        deleted_count = len(self.ids & target_ids)
        self.ids -= target_ids
        return deleted_count


def test_runtime_retention_cleanup_dry_run_and_apply(tmp_path, mocker):
    database_url = f"sqlite:///{tmp_path / 'runtime_retention.db'}"
    execution_store = ExecutionRegistry(database_url)
    compute_store = ComputeJobStore(database_url)
    async_store = AsyncResultStore(database_url)
    lineage_store = LineageMetadataStore(database_url)
    execution_store.create_schema()
    compute_store.create_schema()
    async_store.create_schema()
    lineage_store.create_schema()

    old_id = uuid4()
    recent_id = uuid4()

    for calculation_id in (old_id, recent_id):
        execution_store.create_execution(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            portfolio_id="PORT",
            execution_mode="async",
        )
        execution_store.mark_complete(calculation_id)
        compute_store.enqueue_job(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            request_payload={"calculation_id": str(calculation_id)},
        )
        compute_store.mark_complete(calculation_id, response_payload={"ok": True})
        async_store.record_success(
            calculation_id=calculation_id,
            analytics_type="ReturnsSeries",
            response_payload={"ok": True},
        )
        lineage_store.enqueue_lineage_payload(
            calculation_id=calculation_id,
            calculation_type="ReturnsSeries",
            request_json="{}",
            response_json="{}",
            details={"details.csv": "a,b\n1,2\n"},
        )
        lineage_store.mark_complete(calculation_id, artifact_names=["details.csv"])
        (tmp_path / str(calculation_id)).mkdir()

    old_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent_timestamp = datetime(2026, 3, 10, tzinfo=timezone.utc)

    with execution_store._session() as session:
        execution_store._get_execution_model(session, old_id).completed_at_utc = old_timestamp
        execution_store._get_execution_model(session, recent_id).completed_at_utc = recent_timestamp
    with compute_store._session() as session:
        compute_store._get_model(session, old_id).completed_at_utc = old_timestamp
        compute_store._get_model(session, recent_id).completed_at_utc = recent_timestamp
    with async_store._session() as session:
        old_row = session.get(AsyncResultModel, str(old_id))
        recent_row = session.get(AsyncResultModel, str(recent_id))
        assert old_row is not None
        assert recent_row is not None
        old_row.updated_at_utc = old_timestamp
        recent_row.updated_at_utc = recent_timestamp
    with lineage_store._session() as session:
        old_record = session.get(LineageRecordModel, str(old_id))
        recent_record = session.get(LineageRecordModel, str(recent_id))
        assert old_record is not None
        assert recent_record is not None
        old_record.timestamp_utc = old_timestamp
        recent_record.timestamp_utc = recent_timestamp

    mocker.patch("app.services.runtime_retention_service.execution_registry", execution_store)
    mocker.patch("app.services.runtime_retention_service.compute_job_store", compute_store)
    mocker.patch("app.services.runtime_retention_service.async_result_store", async_store)
    mocker.patch("app.services.runtime_retention_service.lineage_metadata_store", lineage_store)
    mocker.patch(
        "app.services.runtime_retention_service.load_runtime_retention_legal_hold_index",
        return_value=runtime_retention_service.load_runtime_retention_legal_hold_index(Path(tmp_path / "missing.json")),
    )
    mocker.patch(
        "app.services.runtime_retention_service.get_settings",
        return_value=type("Settings", (), {"RUNTIME_RETENTION_DAYS": 30, "LINEAGE_STORAGE_PATH": Path(tmp_path)})(),
    )

    summary = run_runtime_retention_cleanup(
        now=datetime(2026, 3, 14, tzinfo=timezone.utc),
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.prunable_execution_count == 1
    assert summary.prunable_compute_job_count == 1
    assert summary.prunable_async_result_count == 1
    assert summary.prunable_lineage_record_count == 1
    assert summary.prunable_lineage_artifact_count == 1
    assert execution_store.get_execution(old_id) is not None
    assert (tmp_path / str(old_id)).is_dir()

    applied_summary = run_runtime_retention_cleanup(
        now=datetime(2026, 3, 14, tzinfo=timezone.utc),
        dry_run=False,
    )

    assert applied_summary.dry_run is False
    assert execution_store.get_execution(old_id) is None
    assert execution_store.get_execution(recent_id) is not None
    assert compute_store.get_job(old_id) is None
    assert compute_store.get_job(recent_id) is not None
    assert async_store.get_result(old_id) is None
    assert async_store.get_result(recent_id) is not None
    assert lineage_store.get_record(old_id) is None
    assert lineage_store.get_record(recent_id) is not None
    assert not (tmp_path / str(old_id)).exists()
    assert (tmp_path / str(recent_id)).is_dir()


def test_runtime_retention_cleanup_apply_records_phase_results_and_missing_artifact_reconciliation(tmp_path, mocker):
    lineage_root = tmp_path / "lineage"
    lineage_root.mkdir()
    (lineage_root / "lineage-a").mkdir()
    execution_store = _ExecutionIdStore(["exec-a"])
    lineage_store = _LineageIdStore(["lineage-a", "lineage-missing"])
    compute_store = _AggregatePruneStore(1)
    async_store = _AggregatePruneStore(1)
    mocker.patch("app.services.runtime_retention_service.execution_registry", execution_store)
    mocker.patch("app.services.runtime_retention_service.compute_job_store", compute_store)
    mocker.patch("app.services.runtime_retention_service.async_result_store", async_store)
    mocker.patch("app.services.runtime_retention_service.lineage_metadata_store", lineage_store)
    mocker.patch(
        "app.services.runtime_retention_service.load_runtime_retention_legal_hold_index",
        return_value=runtime_retention_service.load_runtime_retention_legal_hold_index(Path(tmp_path / "missing.json")),
    )
    mocker.patch(
        "app.services.runtime_retention_service.get_settings",
        return_value=type("Settings", (), {"RUNTIME_RETENTION_DAYS": 30, "LINEAGE_STORAGE_PATH": Path(lineage_root)})(),
    )

    summary = run_runtime_retention_cleanup(
        now=datetime(2026, 3, 14, tzinfo=timezone.utc),
        dry_run=False,
    )

    phase_results = {phase.phase: phase for phase in summary.phase_results}
    assert summary.target_manifest is not None
    assert summary.target_manifest.execution_ids == ["exec-a"]
    assert summary.target_manifest.lineage_ids == ["lineage-a", "lineage-missing"]
    assert summary.target_manifest.lineage_artifact_paths == [str((lineage_root / "lineage-a").resolve())]
    assert phase_results["compute_jobs"].deleted_count == 1
    assert phase_results["async_results"].deleted_count == 1
    assert phase_results["lineage_artifacts"].target_count == 2
    assert phase_results["lineage_artifacts"].deleted_count == 1
    assert phase_results["lineage_artifacts"].skipped_count == 1
    assert phase_results["lineage_records"].deleted_count == 2
    assert phase_results["executions"].deleted_count == 1
    assert not (lineage_root / "lineage-a").exists()


def test_runtime_retention_cleanup_failure_after_compute_can_rerun_remaining_phases(tmp_path, mocker):
    lineage_root = tmp_path / "lineage"
    lineage_root.mkdir()
    (lineage_root / "lineage-a").mkdir()
    execution_store = _ExecutionIdStore(["exec-a"])
    lineage_store = _LineageIdStore(["lineage-a"])
    compute_store = _AggregatePruneStore(1)
    async_store = _AggregatePruneStore(1, fail_once=True)
    mocker.patch("app.services.runtime_retention_service.execution_registry", execution_store)
    mocker.patch("app.services.runtime_retention_service.compute_job_store", compute_store)
    mocker.patch("app.services.runtime_retention_service.async_result_store", async_store)
    mocker.patch("app.services.runtime_retention_service.lineage_metadata_store", lineage_store)
    mocker.patch(
        "app.services.runtime_retention_service.load_runtime_retention_legal_hold_index",
        return_value=runtime_retention_service.load_runtime_retention_legal_hold_index(Path(tmp_path / "missing.json")),
    )
    mocker.patch(
        "app.services.runtime_retention_service.get_settings",
        return_value=type("Settings", (), {"RUNTIME_RETENTION_DAYS": 30, "LINEAGE_STORAGE_PATH": Path(lineage_root)})(),
    )

    with pytest.raises(RuntimeRetentionCleanupFailed) as exc_info:
        run_runtime_retention_cleanup(
            now=datetime(2026, 3, 14, tzinfo=timezone.utc),
            dry_run=False,
        )

    failed_phase_results = {phase.phase: phase for phase in exc_info.value.summary.phase_results}
    assert failed_phase_results["compute_jobs"].status == "applied"
    assert failed_phase_results["compute_jobs"].deleted_count == 1
    assert failed_phase_results["async_results"].status == "failed"
    assert compute_store.count == 0
    assert async_store.count == 1
    assert lineage_store.ids == {"lineage-a"}
    assert execution_store.ids == {"exec-a"}

    resumed_summary = run_runtime_retention_cleanup(
        now=datetime(2026, 3, 14, tzinfo=timezone.utc),
        dry_run=False,
    )

    resumed_phase_results = {phase.phase: phase for phase in resumed_summary.phase_results}
    assert resumed_phase_results["compute_jobs"].target_count == 0
    assert resumed_phase_results["compute_jobs"].deleted_count == 0
    assert resumed_phase_results["async_results"].deleted_count == 1
    assert resumed_phase_results["lineage_artifacts"].deleted_count == 1
    assert resumed_phase_results["lineage_records"].deleted_count == 1
    assert resumed_phase_results["executions"].deleted_count == 1
    assert not (lineage_root / "lineage-a").exists()


def test_runtime_retention_cleanup_excludes_legal_hold_records_before_apply(tmp_path, mocker):
    lineage_root = tmp_path / "lineage"
    lineage_root.mkdir()
    (lineage_root / "protected-id").mkdir()
    (lineage_root / "delete-id").mkdir()
    execution_store = _ExecutionIdStore(["delete-id", "protected-id"])
    lineage_store = _LineageIdStore(["delete-id", "protected-id"])
    compute_store = _AggregatePruneStore(2, ids=["delete-id", "protected-id"])
    async_store = _AggregatePruneStore(2, ids=["delete-id", "protected-id"])
    hold_path = tmp_path / "legal-holds.json"
    hold_path.write_text(
        '{"holds":[{"calculation_id":"protected-id","reason_code":"client_dispute","source":"case-7"}]}',
        encoding="utf-8",
    )
    mocker.patch("app.services.runtime_retention_service.execution_registry", execution_store)
    mocker.patch("app.services.runtime_retention_service.compute_job_store", compute_store)
    mocker.patch("app.services.runtime_retention_service.async_result_store", async_store)
    mocker.patch("app.services.runtime_retention_service.lineage_metadata_store", lineage_store)
    mocker.patch(
        "app.services.runtime_retention_service.get_settings",
        return_value=type("Settings", (), {"RUNTIME_RETENTION_DAYS": 30, "LINEAGE_STORAGE_PATH": Path(lineage_root)})(),
    )
    mocker.patch(
        "app.services.runtime_retention_legal_hold.get_settings",
        return_value=type("Settings", (), {"RUNTIME_RETENTION_LEGAL_HOLD_PATH": hold_path})(),
    )

    preview = run_runtime_retention_cleanup(
        now=datetime(2026, 3, 14, tzinfo=timezone.utc),
        dry_run=True,
    )
    applied = run_runtime_retention_cleanup(
        now=datetime(2026, 3, 14, tzinfo=timezone.utc),
        dry_run=False,
    )

    assert preview.prunable_execution_count == 1
    assert preview.protected_execution_count == 1
    assert preview.protected_compute_job_count == 1
    assert preview.protected_async_result_count == 1
    assert preview.protected_lineage_record_count == 1
    assert preview.protected_lineage_artifact_count == 1
    assert preview.protected_reason_counts == {"client_dispute": 1}
    assert preview.target_manifest is not None
    assert preview.target_manifest.execution_ids == ["delete-id"]
    assert preview.target_manifest.protected_execution_ids == ["protected-id"]
    assert preview.target_manifest.protected_reason_counts == {"client_dispute": 1}
    assert applied.prunable_execution_count == 1
    assert execution_store.ids == {"protected-id"}
    assert lineage_store.ids == {"protected-id"}
    assert compute_store.ids == {"protected-id"}
    assert async_store.ids == {"protected-id"}
    assert not (lineage_root / "delete-id").exists()
    assert (lineage_root / "protected-id").is_dir()


def test_lineage_artifact_cleanup_rejects_paths_outside_storage_root(tmp_path, mocker):
    storage_root = tmp_path / "lineage"
    storage_root.mkdir()
    valid_calculation_id = "valid-calculation"
    unsafe_calculation_id = "../outside-lineage"
    valid_directory = storage_root / valid_calculation_id
    outside_directory = tmp_path / "outside-lineage"
    valid_directory.mkdir()
    outside_directory.mkdir()

    mocker.patch(
        "app.services.runtime_retention_service.get_settings",
        return_value=type("Settings", (), {"LINEAGE_STORAGE_PATH": Path(storage_root)})(),
    )

    assert (
        runtime_retention_service._count_lineage_artifact_directories([valid_calculation_id, unsafe_calculation_id])
        == 1
    )
    assert runtime_retention_service._delete_lineage_artifact_directories([unsafe_calculation_id]) == 0
    assert outside_directory.is_dir()
    assert runtime_retention_service._delete_lineage_artifact_directories([valid_calculation_id]) == 1
    assert not valid_directory.exists()
