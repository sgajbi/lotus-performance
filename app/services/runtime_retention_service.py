from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.durable_store_time import format_timestamp
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store
from app.services.runtime_retention_legal_hold import load_runtime_retention_legal_hold_index

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeRetentionCleanupPhaseResult:
    phase: str
    status: str
    target_count: int
    deleted_count: int
    skipped_count: int = 0
    failed_count: int = 0
    failure_message: str | None = None


@dataclass(frozen=True)
class RuntimeRetentionCleanupTargetManifest:
    execution_ids: list[str]
    lineage_ids: list[str]
    lineage_artifact_paths: list[str]
    compute_job_count: int
    async_result_count: int
    protected_execution_ids: list[str] = field(default_factory=list)
    protected_compute_job_ids: list[str] = field(default_factory=list)
    protected_async_result_ids: list[str] = field(default_factory=list)
    protected_lineage_ids: list[str] = field(default_factory=list)
    protected_lineage_artifact_paths: list[str] = field(default_factory=list)
    protected_reason_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeRetentionCleanupSummary:
    retention_days: int
    cutoff_utc: str
    dry_run: bool
    prunable_execution_count: int
    prunable_compute_job_count: int
    prunable_async_result_count: int
    prunable_lineage_record_count: int
    prunable_lineage_artifact_count: int
    protected_execution_count: int = 0
    protected_compute_job_count: int = 0
    protected_async_result_count: int = 0
    protected_lineage_record_count: int = 0
    protected_lineage_artifact_count: int = 0
    protected_reason_counts: dict[str, int] = field(default_factory=dict)
    target_manifest: RuntimeRetentionCleanupTargetManifest | None = None
    phase_results: list[RuntimeRetentionCleanupPhaseResult] = field(default_factory=list)
    failure_message: str | None = None


@dataclass(frozen=True)
class RuntimeRetentionPrunableItems:
    execution_ids: list[str]
    lineage_ids: list[str]
    compute_job_ids: list[str]
    async_result_ids: list[str]
    lineage_artifact_count: int
    protected_execution_ids: list[str] = field(default_factory=list)
    protected_compute_job_ids: list[str] = field(default_factory=list)
    protected_async_result_ids: list[str] = field(default_factory=list)
    protected_lineage_ids: list[str] = field(default_factory=list)
    protected_lineage_artifact_count: int = 0
    protected_reason_counts: dict[str, int] = field(default_factory=dict)


class RuntimeRetentionCleanupFailed(RuntimeError):
    def __init__(self, summary: RuntimeRetentionCleanupSummary, message: str):
        super().__init__(message)
        self.summary = summary


class _RuntimeRetentionPhaseFailed(RuntimeError):
    def __init__(self, phase_results: list[RuntimeRetentionCleanupPhaseResult], message: str):
        super().__init__(message)
        self.phase_results = phase_results


ApplyStartCallback = Callable[[RuntimeRetentionCleanupSummary], None]


def run_runtime_retention_cleanup(
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    before_apply: ApplyStartCallback | None = None,
) -> RuntimeRetentionCleanupSummary:
    settings = get_settings()
    effective_retention_days = retention_days if retention_days is not None else settings.RUNTIME_RETENTION_DAYS
    effective_now = now or datetime.now(timezone.utc)
    cutoff = effective_now - timedelta(days=effective_retention_days)

    prunable_items = _collect_prunable_items(cutoff=cutoff)

    if not dry_run:
        planned_summary = _build_cleanup_summary(
            retention_days=effective_retention_days,
            cutoff=cutoff,
            dry_run=dry_run,
            prunable_items=prunable_items,
        )
        if before_apply is not None:
            before_apply(planned_summary)
        try:
            phase_results = _delete_prunable_items(cutoff=cutoff, prunable_items=prunable_items)
        except _RuntimeRetentionPhaseFailed as exc:
            failed_summary = _build_cleanup_summary(
                retention_days=effective_retention_days,
                cutoff=cutoff,
                dry_run=dry_run,
                prunable_items=prunable_items,
                phase_results=exc.phase_results,
                failure_message=str(exc),
                target_manifest=planned_summary.target_manifest,
            )
            raise RuntimeRetentionCleanupFailed(failed_summary, str(exc)) from exc
        return _build_cleanup_summary(
            retention_days=effective_retention_days,
            cutoff=cutoff,
            dry_run=dry_run,
            prunable_items=prunable_items,
            phase_results=phase_results,
            target_manifest=planned_summary.target_manifest,
        )

    return _build_cleanup_summary(
        retention_days=effective_retention_days,
        cutoff=cutoff,
        dry_run=dry_run,
        prunable_items=prunable_items,
    )


def _build_cleanup_summary(
    *,
    retention_days: int,
    cutoff: datetime,
    dry_run: bool,
    prunable_items: RuntimeRetentionPrunableItems,
    phase_results: list[RuntimeRetentionCleanupPhaseResult] | None = None,
    failure_message: str | None = None,
    target_manifest: RuntimeRetentionCleanupTargetManifest | None = None,
) -> RuntimeRetentionCleanupSummary:
    return RuntimeRetentionCleanupSummary(
        retention_days=retention_days,
        cutoff_utc=format_timestamp(cutoff) or "",
        dry_run=dry_run,
        prunable_execution_count=len(prunable_items.execution_ids),
        prunable_compute_job_count=len(prunable_items.compute_job_ids),
        prunable_async_result_count=len(prunable_items.async_result_ids),
        prunable_lineage_record_count=len(prunable_items.lineage_ids),
        prunable_lineage_artifact_count=prunable_items.lineage_artifact_count,
        protected_execution_count=len(prunable_items.protected_execution_ids),
        protected_compute_job_count=len(prunable_items.protected_compute_job_ids),
        protected_async_result_count=len(prunable_items.protected_async_result_ids),
        protected_lineage_record_count=len(prunable_items.protected_lineage_ids),
        protected_lineage_artifact_count=prunable_items.protected_lineage_artifact_count,
        protected_reason_counts=dict(prunable_items.protected_reason_counts),
        target_manifest=target_manifest or _build_target_manifest(prunable_items),
        phase_results=list(phase_results or []),
        failure_message=failure_message,
    )


def _build_target_manifest(prunable_items: RuntimeRetentionPrunableItems) -> RuntimeRetentionCleanupTargetManifest:
    return RuntimeRetentionCleanupTargetManifest(
        execution_ids=sorted(prunable_items.execution_ids),
        lineage_ids=sorted(prunable_items.lineage_ids),
        lineage_artifact_paths=sorted(_lineage_artifact_paths(prunable_items.lineage_ids)),
        compute_job_count=len(prunable_items.compute_job_ids),
        async_result_count=len(prunable_items.async_result_ids),
        protected_execution_ids=sorted(prunable_items.protected_execution_ids),
        protected_compute_job_ids=sorted(prunable_items.protected_compute_job_ids),
        protected_async_result_ids=sorted(prunable_items.protected_async_result_ids),
        protected_lineage_ids=sorted(prunable_items.protected_lineage_ids),
        protected_lineage_artifact_paths=sorted(_lineage_artifact_paths(prunable_items.protected_lineage_ids)),
        protected_reason_counts=dict(prunable_items.protected_reason_counts),
    )


def _collect_prunable_items(*, cutoff: datetime) -> RuntimeRetentionPrunableItems:
    legal_hold_index = load_runtime_retention_legal_hold_index()
    candidate_execution_ids = execution_registry.list_terminal_execution_ids_older_than(cutoff)
    candidate_lineage_ids = lineage_metadata_store.list_terminal_calculation_ids_older_than(cutoff)
    candidate_compute_job_ids = compute_job_store.list_terminal_job_ids_older_than(cutoff)
    candidate_async_result_ids = async_result_store.list_result_ids_older_than(cutoff)
    protected_execution_ids = legal_hold_index.protected_ids_for(candidate_execution_ids)
    protected_lineage_ids = legal_hold_index.protected_ids_for(candidate_lineage_ids)
    protected_compute_job_ids = legal_hold_index.protected_ids_for(candidate_compute_job_ids)
    protected_async_result_ids = legal_hold_index.protected_ids_for(candidate_async_result_ids)
    protected_ids = sorted(
        set(protected_execution_ids)
        | set(protected_lineage_ids)
        | set(protected_compute_job_ids)
        | set(protected_async_result_ids)
    )
    return RuntimeRetentionPrunableItems(
        execution_ids=_exclude_protected_ids(candidate_execution_ids, protected_execution_ids),
        lineage_ids=_exclude_protected_ids(candidate_lineage_ids, protected_lineage_ids),
        compute_job_ids=_exclude_protected_ids(candidate_compute_job_ids, protected_compute_job_ids),
        async_result_ids=_exclude_protected_ids(candidate_async_result_ids, protected_async_result_ids),
        lineage_artifact_count=_count_lineage_artifact_directories(
            _exclude_protected_ids(candidate_lineage_ids, protected_lineage_ids)
        ),
        protected_execution_ids=protected_execution_ids,
        protected_compute_job_ids=protected_compute_job_ids,
        protected_async_result_ids=protected_async_result_ids,
        protected_lineage_ids=protected_lineage_ids,
        protected_lineage_artifact_count=_count_lineage_artifact_directories(protected_lineage_ids),
        protected_reason_counts=legal_hold_index.reason_counts_for(protected_ids),
    )


def _delete_prunable_items(
    *, cutoff: datetime, prunable_items: RuntimeRetentionPrunableItems
) -> list[RuntimeRetentionCleanupPhaseResult]:
    phase_results: list[RuntimeRetentionCleanupPhaseResult] = []
    _append_count_phase_result(
        phase_results,
        phase="compute_jobs",
        target_count=len(prunable_items.compute_job_ids),
        delete=lambda: compute_job_store.prune_terminal_jobs_older_than(
            cutoff,
            dry_run=False,
            exclude_calculation_ids=set(prunable_items.protected_compute_job_ids),
        ),
    )
    _append_count_phase_result(
        phase_results,
        phase="async_results",
        target_count=len(prunable_items.async_result_ids),
        delete=lambda: async_result_store.prune_results_older_than(
            cutoff,
            dry_run=False,
            exclude_calculation_ids=set(prunable_items.protected_async_result_ids),
        ),
    )
    _append_artifact_phase_result(phase_results, prunable_items.lineage_ids)
    _append_count_phase_result(
        phase_results,
        phase="lineage_records",
        target_count=len(prunable_items.lineage_ids),
        delete=lambda: lineage_metadata_store.delete_calculation_ids(prunable_items.lineage_ids),
    )
    _append_count_phase_result(
        phase_results,
        phase="executions",
        target_count=len(prunable_items.execution_ids),
        delete=lambda: execution_registry.delete_executions(prunable_items.execution_ids),
    )
    return phase_results


def _exclude_protected_ids(candidate_ids: list[str], protected_ids: list[str]) -> list[str]:
    protected_id_set = set(protected_ids)
    return sorted(calculation_id for calculation_id in candidate_ids if calculation_id not in protected_id_set)


def _append_count_phase_result(
    phase_results: list[RuntimeRetentionCleanupPhaseResult],
    *,
    phase: str,
    target_count: int,
    delete: Callable[[], int],
) -> None:
    try:
        deleted_count = delete()
    except Exception as exc:
        failure_message = f"{phase} phase failed"
        phase_results.append(
            RuntimeRetentionCleanupPhaseResult(
                phase=phase,
                status="failed",
                target_count=target_count,
                deleted_count=0,
                skipped_count=0,
                failed_count=target_count,
                failure_message=failure_message,
            )
        )
        raise _RuntimeRetentionPhaseFailed(phase_results, failure_message) from exc
    phase_results.append(
        RuntimeRetentionCleanupPhaseResult(
            phase=phase,
            status="applied",
            target_count=target_count,
            deleted_count=deleted_count,
            skipped_count=max(target_count - deleted_count, 0),
        )
    )


@dataclass(frozen=True)
class _LineageArtifactDeletionResult:
    deleted_count: int
    skipped_count: int


class _LineageArtifactDeletionFailed(RuntimeError):
    def __init__(self, result: _LineageArtifactDeletionResult, message: str):
        super().__init__(message)
        self.result = result


def _append_artifact_phase_result(
    phase_results: list[RuntimeRetentionCleanupPhaseResult], lineage_ids: list[str]
) -> None:
    target_count = len(lineage_ids)
    try:
        result = _delete_lineage_artifact_directories_result(lineage_ids)
    except _LineageArtifactDeletionFailed as exc:
        phase_results.append(
            RuntimeRetentionCleanupPhaseResult(
                phase="lineage_artifacts",
                status="failed",
                target_count=target_count,
                deleted_count=exc.result.deleted_count,
                skipped_count=exc.result.skipped_count,
                failed_count=max(target_count - exc.result.deleted_count - exc.result.skipped_count, 1),
                failure_message="lineage_artifacts phase failed",
            )
        )
        raise _RuntimeRetentionPhaseFailed(phase_results, "lineage_artifacts phase failed") from exc
    phase_results.append(
        RuntimeRetentionCleanupPhaseResult(
            phase="lineage_artifacts",
            status="applied",
            target_count=target_count,
            deleted_count=result.deleted_count,
            skipped_count=result.skipped_count,
        )
    )


def _count_lineage_artifact_directories(calculation_ids: list[str]) -> int:
    return sum(
        1
        for calculation_id in calculation_ids
        if (directory := _lineage_artifact_directory(calculation_id)) is not None and directory.is_dir()
    )


def _delete_lineage_artifact_directories(calculation_ids: list[str]) -> int:
    return _delete_lineage_artifact_directories_result(calculation_ids).deleted_count


def _delete_lineage_artifact_directories_result(calculation_ids: list[str]) -> _LineageArtifactDeletionResult:
    deleted_count = 0
    skipped_count = 0
    for calculation_id in calculation_ids:
        directory = _lineage_artifact_directory(calculation_id)
        if directory is None or not directory.is_dir():
            skipped_count += 1
            continue
        try:
            shutil.rmtree(directory)
        except Exception as exc:
            raise _LineageArtifactDeletionFailed(
                _LineageArtifactDeletionResult(deleted_count=deleted_count, skipped_count=skipped_count),
                "lineage_artifacts phase failed",
            ) from exc
        deleted_count += 1
    return _LineageArtifactDeletionResult(deleted_count=deleted_count, skipped_count=skipped_count)


def _lineage_artifact_paths(calculation_ids: list[str]) -> list[str]:
    paths: list[str] = []
    for calculation_id in calculation_ids:
        directory = _lineage_artifact_directory(calculation_id)
        if directory is not None and directory.is_dir():
            paths.append(str(directory))
    return paths


def _lineage_artifact_directory(calculation_id: str) -> Path | None:
    lineage_storage_path = _lineage_storage_path()
    directory = (lineage_storage_path / calculation_id).resolve()
    if not directory.is_relative_to(lineage_storage_path):
        logger.warning("Skipping unsafe lineage artifact directory outside storage root: %s", calculation_id)
        return None
    return directory


def _lineage_storage_path() -> Path:
    return Path(get_settings().LINEAGE_STORAGE_PATH).resolve()
