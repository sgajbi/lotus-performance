from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.core.config import get_settings
from app.services.operator_action_evidence_strings import required_evidence_int_fields_present
from app.services.operator_action_history_filters import (
    build_applied_history_filters,
    filter_history_entries,
)
from app.services.operator_action_history_manifest import (
    HistoryManifestReadReasons,
    resolve_history_manifest_payload,
    validate_history_entry_generated_at_utc,
    validate_history_entry_strings,
)
from app.services.operator_action_history_pagination import paginate_history_entries
from app.services.operator_action_history_snapshot import (
    build_available_history_snapshot,
    build_unavailable_history_snapshot,
)

RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON = "runtime_retention_artifact_directory_missing"
RUNTIME_RETENTION_MANIFEST_INVALID_REASON = "runtime_retention_manifest_invalid"
RUNTIME_RETENTION_MANIFEST_MISSING_REASON = "runtime_retention_manifest_missing"
RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON = "runtime_retention_manifest_unreadable"
_RUNTIME_RETENTION_ENTRY_STR_KEYS = (
    "evidence_file_name",
    "generated_at_utc",
    "operator_id",
    "cleanup_mode",
    "status",
)
_RUNTIME_RETENTION_ENTRY_OPTIONAL_STR_KEYS = ("tenant_id", "correlation_id", "job_id")
_RUNTIME_RETENTION_ENTRY_INT_KEYS = (
    "retention_days",
    "prunable_execution_count",
    "prunable_compute_job_count",
    "prunable_async_result_count",
    "prunable_lineage_record_count",
    "prunable_lineage_artifact_count",
)
_RUNTIME_RETENTION_ENTRY_OPTIONAL_INT_KEYS = (
    "protected_execution_count",
    "protected_compute_job_count",
    "protected_async_result_count",
    "protected_lineage_record_count",
    "protected_lineage_artifact_count",
)
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
    protected_execution_count: int = 0
    protected_compute_job_count: int = 0
    protected_async_result_count: int = 0
    protected_lineage_record_count: int = 0
    protected_lineage_artifact_count: int = 0
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


@dataclass(frozen=True)
class _RuntimeRetentionHistoryQuery:
    limit: int | None
    offset: int
    operator_id: str | None
    trigger_mode: str | None
    job_id: str | None
    cleanup_mode: str | None
    status_filter: str | None
    generated_after: str | None
    generated_before: str | None
    applied_filters: dict[str, str | int]


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
    query = _runtime_retention_history_query(
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

    manifest_resolution = resolve_history_manifest_payload(
        directory=directory,
        reasons=RUNTIME_RETENTION_MANIFEST_READ_REASONS,
        validate_entry=_validate_manifest_entry,
        history_name="Runtime retention",
    )
    if manifest_resolution.reason is not None:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=query.applied_filters,
            reason=manifest_resolution.reason,
        )

    manifest_payload = cast(dict[str, Any], manifest_resolution.manifest_payload)
    return _available_runtime_retention_history_snapshot_from_manifest(
        directory=directory,
        manifest_payload=manifest_payload,
        query=query,
    )


def _runtime_retention_history_query(
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
) -> _RuntimeRetentionHistoryQuery:
    applied_filters = build_applied_history_filters(
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
    return _RuntimeRetentionHistoryQuery(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        trigger_mode=trigger_mode,
        job_id=job_id,
        cleanup_mode=cleanup_mode,
        status_filter=status_filter,
        generated_after=generated_after,
        generated_before=generated_before,
        applied_filters=applied_filters,
    )


def _available_runtime_retention_history_snapshot_from_manifest(
    *,
    directory: Path,
    manifest_payload: dict[str, Any],
    query: _RuntimeRetentionHistoryQuery,
) -> RuntimeRetentionHistorySnapshot:
    all_entries = _runtime_retention_history_entries_from_manifest(manifest_payload)
    filtered_entries = filter_history_entries(
        entries=all_entries,
        exact_filters=(
            (query.operator_id, lambda entry: entry.operator_id),
            (query.trigger_mode, lambda entry: entry.trigger_mode),
            (query.job_id, lambda entry: entry.job_id),
            (query.cleanup_mode, lambda entry: entry.cleanup_mode),
            (query.status_filter, lambda entry: entry.status),
        ),
        generated_after=query.generated_after,
        generated_before=query.generated_before,
        get_generated_at_utc=lambda entry: entry.generated_at_utc,
    )
    page = paginate_history_entries(filtered_entries, limit=query.limit, offset=query.offset)

    return build_available_history_snapshot(
        RuntimeRetentionHistorySnapshot,
        directory=directory,
        manifest_payload=manifest_payload,
        entries=page.entries,
        total_entries=len(all_entries),
        matched_entries=len(filtered_entries),
        returned_entries=len(page.entries),
        next_offset=page.next_offset,
        applied_filters=query.applied_filters,
    )


def _runtime_retention_history_entries_from_manifest(
    manifest_payload: dict[str, Any],
) -> list[RuntimeRetentionHistoryEntry]:
    return [
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
            protected_execution_count=entry.get("protected_execution_count", 0),
            protected_compute_job_count=entry.get("protected_compute_job_count", 0),
            protected_async_result_count=entry.get("protected_async_result_count", 0),
            protected_lineage_record_count=entry.get("protected_lineage_record_count", 0),
            protected_lineage_artifact_count=entry.get("protected_lineage_artifact_count", 0),
        )
        for entry in manifest_payload["entries"]
    ]


def _unavailable_snapshot(
    *,
    directory: Path,
    applied_filters: dict[str, str | int],
    reason: str,
) -> RuntimeRetentionHistorySnapshot:
    return build_unavailable_history_snapshot(
        RuntimeRetentionHistorySnapshot,
        directory=directory,
        applied_filters=applied_filters,
        reason=reason,
    )


def _runtime_retention_entry_strings(entry: dict[str, Any]) -> tuple[dict[str, str | None], str] | None:
    entry_strings = validate_history_entry_strings(
        entry,
        required_keys=_RUNTIME_RETENTION_ENTRY_STR_KEYS,
        optional_keys=_RUNTIME_RETENTION_ENTRY_OPTIONAL_STR_KEYS,
    )
    if entry_strings is None:
        return None
    if validate_history_entry_generated_at_utc(entry_strings) is None:
        return None
    trigger_mode = entry.get("trigger_mode", "manual")
    if not isinstance(trigger_mode, str):
        return None
    trigger_mode = trigger_mode.strip()
    if not trigger_mode:
        return None
    return entry_strings, trigger_mode


def _validate_manifest_entry(entry: Any) -> dict[str, str | int | None] | None:
    if not isinstance(entry, dict):
        return None
    entry_fields = _runtime_retention_entry_strings(entry)
    if entry_fields is None:
        return None
    entry_strings, trigger_mode = entry_fields
    if not required_evidence_int_fields_present(entry, _RUNTIME_RETENTION_ENTRY_INT_KEYS):
        return None
    for key in _RUNTIME_RETENTION_ENTRY_OPTIONAL_INT_KEYS:
        if key in entry and not isinstance(entry[key], int):
            return None

    return _runtime_retention_manifest_entry_payload(
        entry=entry,
        entry_strings=entry_strings,
        trigger_mode=trigger_mode,
    )


def _runtime_retention_manifest_entry_payload(
    *,
    entry: dict[str, Any],
    entry_strings: dict[str, str | None],
    trigger_mode: str,
) -> dict[str, str | int | None]:
    validated_entry: dict[str, str | int | None] = {
        key: entry_strings[key] for key in _RUNTIME_RETENTION_ENTRY_STR_KEYS
    }
    validated_entry.update({key: entry[key] for key in _RUNTIME_RETENTION_ENTRY_INT_KEYS})
    validated_entry.update({key: int(entry.get(key, 0)) for key in _RUNTIME_RETENTION_ENTRY_OPTIONAL_INT_KEYS})
    validated_entry["trigger_mode"] = trigger_mode
    validated_entry["tenant_id"] = entry_strings["tenant_id"]
    validated_entry["correlation_id"] = entry_strings["correlation_id"]
    validated_entry["job_id"] = entry_strings["job_id"]
    return validated_entry
