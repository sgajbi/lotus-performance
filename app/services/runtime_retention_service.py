from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.services.async_result_store import async_result_store
from app.services.compute_job_store import compute_job_store
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import lineage_metadata_store

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class RuntimeRetentionPrunableItems:
    execution_ids: list[str]
    lineage_ids: list[str]
    compute_job_count: int
    async_result_count: int
    lineage_artifact_count: int


def run_runtime_retention_cleanup(
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> RuntimeRetentionCleanupSummary:
    settings = get_settings()
    effective_retention_days = retention_days if retention_days is not None else settings.RUNTIME_RETENTION_DAYS
    effective_now = now or datetime.now(timezone.utc)
    cutoff = effective_now - timedelta(days=effective_retention_days)

    prunable_items = _collect_prunable_items(cutoff=cutoff)

    if not dry_run:
        _delete_prunable_items(cutoff=cutoff, prunable_items=prunable_items)

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
) -> RuntimeRetentionCleanupSummary:
    return RuntimeRetentionCleanupSummary(
        retention_days=retention_days,
        cutoff_utc=cutoff.isoformat().replace("+00:00", "Z"),
        dry_run=dry_run,
        prunable_execution_count=len(prunable_items.execution_ids),
        prunable_compute_job_count=prunable_items.compute_job_count,
        prunable_async_result_count=prunable_items.async_result_count,
        prunable_lineage_record_count=len(prunable_items.lineage_ids),
        prunable_lineage_artifact_count=prunable_items.lineage_artifact_count,
    )


def _collect_prunable_items(*, cutoff: datetime) -> RuntimeRetentionPrunableItems:
    prunable_execution_ids = execution_registry.list_terminal_execution_ids_older_than(cutoff)
    prunable_lineage_ids = lineage_metadata_store.list_terminal_calculation_ids_older_than(cutoff)
    return RuntimeRetentionPrunableItems(
        execution_ids=prunable_execution_ids,
        lineage_ids=prunable_lineage_ids,
        compute_job_count=compute_job_store.prune_terminal_jobs_older_than(cutoff, dry_run=True),
        async_result_count=async_result_store.prune_results_older_than(cutoff, dry_run=True),
        lineage_artifact_count=_count_lineage_artifact_directories(prunable_lineage_ids),
    )


def _delete_prunable_items(*, cutoff: datetime, prunable_items: RuntimeRetentionPrunableItems) -> None:
    compute_job_store.prune_terminal_jobs_older_than(cutoff, dry_run=False)
    async_result_store.prune_results_older_than(cutoff, dry_run=False)
    _delete_lineage_artifact_directories(prunable_items.lineage_ids)
    lineage_metadata_store.delete_calculation_ids(prunable_items.lineage_ids)
    execution_registry.delete_executions(prunable_items.execution_ids)


def _count_lineage_artifact_directories(calculation_ids: list[str]) -> int:
    return sum(
        1
        for calculation_id in calculation_ids
        if (directory := _lineage_artifact_directory(calculation_id)) is not None and directory.is_dir()
    )


def _delete_lineage_artifact_directories(calculation_ids: list[str]) -> int:
    deleted_count = 0
    for calculation_id in calculation_ids:
        directory = _lineage_artifact_directory(calculation_id)
        if directory is not None and directory.is_dir():
            shutil.rmtree(directory)
            deleted_count += 1
    return deleted_count


def _lineage_artifact_directory(calculation_id: str) -> Path | None:
    lineage_storage_path = _lineage_storage_path()
    directory = (lineage_storage_path / calculation_id).resolve()
    if not directory.is_relative_to(lineage_storage_path):
        logger.warning("Skipping unsafe lineage artifact directory outside storage root: %s", calculation_id)
        return None
    return directory


def _lineage_storage_path() -> Path:
    return Path(get_settings().LINEAGE_STORAGE_PATH).resolve()
