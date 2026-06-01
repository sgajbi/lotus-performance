from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.operator_action_history_filters import (
    build_applied_history_filters,
    filter_history_entries,
)
from app.services.operator_action_history_manifest import (
    HistoryManifestReadReasons,
    log_invalid_history_manifest_payload,
    read_history_manifest_payload,
    validate_history_entry_strings,
    validate_history_manifest_payload,
)
from app.services.operator_action_history_pagination import paginate_history_entries
from app.services.runtime_status_time import parse_utc_datetime

RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON = "runtime_retention_artifact_directory_missing"
RUNTIME_RETENTION_MANIFEST_INVALID_REASON = "runtime_retention_manifest_invalid"
RUNTIME_RETENTION_MANIFEST_MISSING_REASON = "runtime_retention_manifest_missing"
RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON = "runtime_retention_manifest_unreadable"
RUNTIME_RETENTION_MANIFEST_READ_REASONS = HistoryManifestReadReasons(
    directory_missing=RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON,
    manifest_missing=RUNTIME_RETENTION_MANIFEST_MISSING_REASON,
    manifest_unreadable=RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON,
    manifest_invalid=RUNTIME_RETENTION_MANIFEST_INVALID_REASON,
)


@dataclass(frozen=True)
class RuntimeRetentionHistoryEntry:
    evidence_file_name: str
    generated_at_utc: str
    operator_id: str
    trigger_mode: str
    job_id: str | None
    cleanup_mode: str
    status: str
    retention_days: int
    prunable_execution_count: int
    prunable_compute_job_count: int
    prunable_async_result_count: int
    prunable_lineage_record_count: int
    prunable_lineage_artifact_count: int
    tenant_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class RuntimeRetentionHistorySnapshot:
    status: str
    artifact_directory: str
    latest_file_name: str | None
    retained_file_names: list[str]
    retention_limit: int | None
    retention_max_age_days: int | None
    entries: list[RuntimeRetentionHistoryEntry]
    total_entries: int
    matched_entries: int
    returned_entries: int
    next_offset: int | None
    applied_filters: dict[str, str | int]
    reason: str | None = None


def build_runtime_retention_history_snapshot(
    *,
    artifact_directory: Path | None = None,
    limit: int | None = None,
    offset: int = 0,
    operator_id: str | None = None,
    trigger_mode: str | None = None,
    job_id: str | None = None,
    cleanup_mode: str | None = None,
    status_filter: str | None = None,
    generated_after: str | None = None,
    generated_before: str | None = None,
) -> RuntimeRetentionHistorySnapshot:
    directory = artifact_directory or get_settings().RUNTIME_RETENTION_ARTIFACT_PATH
    applied_filters = _build_applied_filters(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode=cleanup_mode,
        status_filter=status_filter,
        generated_after=generated_after,
        generated_before=generated_before,
    )

    manifest_read = read_history_manifest_payload(directory=directory, reasons=RUNTIME_RETENTION_MANIFEST_READ_REASONS)
    if manifest_read.reason is not None:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=manifest_read.reason,
        )

    manifest_payload = validate_history_manifest_payload(
        manifest_read.payload,
        validate_entry=_validate_manifest_entry,
    )
    if manifest_payload is None:
        log_invalid_history_manifest_payload(
            manifest_path=directory / "manifest.json",
            history_name="Runtime retention",
        )
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RUNTIME_RETENTION_MANIFEST_INVALID_REASON,
        )

    all_entries = [
        RuntimeRetentionHistoryEntry(
            evidence_file_name=entry["evidence_file_name"],
            generated_at_utc=entry["generated_at_utc"],
            operator_id=entry["operator_id"],
            tenant_id=entry["tenant_id"],
            correlation_id=entry["correlation_id"],
            trigger_mode=entry["trigger_mode"],
            job_id=entry["job_id"],
            cleanup_mode=entry["cleanup_mode"],
            status=entry["status"],
            retention_days=entry["retention_days"],
            prunable_execution_count=entry["prunable_execution_count"],
            prunable_compute_job_count=entry["prunable_compute_job_count"],
            prunable_async_result_count=entry["prunable_async_result_count"],
            prunable_lineage_record_count=entry["prunable_lineage_record_count"],
            prunable_lineage_artifact_count=entry["prunable_lineage_artifact_count"],
        )
        for entry in manifest_payload["entries"]
    ]
    filtered_entries = _filter_entries(
        entries=all_entries,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode=cleanup_mode,
        status_filter=status_filter,
        generated_after=generated_after,
        generated_before=generated_before,
    )
    page = paginate_history_entries(filtered_entries, limit=limit, offset=offset)

    return RuntimeRetentionHistorySnapshot(
        status="available",
        artifact_directory=str(directory),
        latest_file_name=manifest_payload["latest_file_name"],
        retained_file_names=manifest_payload["retained_file_names"],
        retention_limit=manifest_payload["retention_limit"],
        retention_max_age_days=manifest_payload["retention_max_age_days"],
        entries=page.entries,
        total_entries=len(all_entries),
        matched_entries=len(filtered_entries),
        returned_entries=len(page.entries),
        next_offset=page.next_offset,
        applied_filters=applied_filters,
        reason=None,
    )


def _unavailable_snapshot(
    *,
    directory: Path,
    applied_filters: dict[str, str | int],
    reason: str,
) -> RuntimeRetentionHistorySnapshot:
    return RuntimeRetentionHistorySnapshot(
        status="unavailable",
        artifact_directory=str(directory),
        latest_file_name=None,
        retained_file_names=[],
        retention_limit=None,
        retention_max_age_days=None,
        entries=[],
        total_entries=0,
        matched_entries=0,
        returned_entries=0,
        next_offset=None,
        applied_filters=applied_filters,
        reason=reason,
    )


def _validate_manifest_entry(entry: Any) -> dict[str, str | int | None] | None:
    if not isinstance(entry, dict):
        return None
    str_keys = ("evidence_file_name", "generated_at_utc", "operator_id", "cleanup_mode", "status")
    int_keys = (
        "retention_days",
        "prunable_execution_count",
        "prunable_compute_job_count",
        "prunable_async_result_count",
        "prunable_lineage_record_count",
        "prunable_lineage_artifact_count",
    )
    trigger_mode = entry.get("trigger_mode", "manual")
    entry_strings = validate_history_entry_strings(
        entry,
        required_keys=str_keys,
        optional_keys=("tenant_id", "correlation_id", "job_id"),
    )
    if entry_strings is None:
        return None
    try:
        parse_utc_datetime(entry_strings["generated_at_utc"])
    except ValueError:
        return None
    if not isinstance(trigger_mode, str):
        return None
    if any(not isinstance(entry.get(key), int) for key in int_keys):
        return None

    validated_entry: dict[str, str | int | None] = {key: entry_strings[key] for key in str_keys}
    validated_entry.update({key: entry[key] for key in int_keys})
    validated_entry["trigger_mode"] = trigger_mode
    validated_entry["tenant_id"] = entry_strings["tenant_id"]
    validated_entry["correlation_id"] = entry_strings["correlation_id"]
    validated_entry["job_id"] = entry_strings["job_id"]
    return validated_entry


def _filter_entries(
    *,
    entries: list[RuntimeRetentionHistoryEntry],
    operator_id: str | None,
    trigger_mode: str | None,
    job_id: str | None,
    cleanup_mode: str | None,
    status_filter: str | None,
    generated_after: str | None,
    generated_before: str | None,
) -> list[RuntimeRetentionHistoryEntry]:
    return filter_history_entries(
        entries,
        exact_filters=(
            (operator_id, lambda entry: entry.operator_id),
            (trigger_mode, lambda entry: entry.trigger_mode),
            (job_id, lambda entry: entry.job_id),
            (cleanup_mode, lambda entry: entry.cleanup_mode),
            (status_filter, lambda entry: entry.status),
        ),
        generated_after=generated_after,
        generated_before=generated_before,
        get_generated_at_utc=lambda entry: entry.generated_at_utc,
    )


def _build_applied_filters(
    *,
    limit: int | None,
    offset: int,
    operator_id: str | None,
    trigger_mode: str | None,
    job_id: str | None,
    cleanup_mode: str | None,
    status_filter: str | None,
    generated_after: str | None,
    generated_before: str | None,
) -> dict[str, str | int]:
    return build_applied_history_filters(
        limit=limit,
        offset=offset,
        optional_filters=(
            ("operator_id", operator_id),
            ("trigger_mode", trigger_mode),
            ("job_id", job_id),
            ("cleanup_mode", cleanup_mode),
            ("status", status_filter),
        ),
        generated_after=generated_after,
        generated_before=generated_before,
    )
