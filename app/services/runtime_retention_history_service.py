from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.operator_action_evidence_paths import is_safe_evidence_file_name
from app.services.operator_action_history_pagination import paginate_history_entries

RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON = "runtime_retention_artifact_directory_missing"
RUNTIME_RETENTION_MANIFEST_INVALID_REASON = "runtime_retention_manifest_invalid"
RUNTIME_RETENTION_MANIFEST_MISSING_REASON = "runtime_retention_manifest_missing"
RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON = "runtime_retention_manifest_unreadable"


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
    manifest_path = directory / "manifest.json"
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

    if not directory.exists():
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RUNTIME_RETENTION_ARTIFACT_DIRECTORY_MISSING_REASON,
        )

    if not manifest_path.exists():
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RUNTIME_RETENTION_MANIFEST_MISSING_REASON,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RUNTIME_RETENTION_MANIFEST_UNREADABLE_REASON,
        )
    except json.JSONDecodeError:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RUNTIME_RETENTION_MANIFEST_INVALID_REASON,
        )

    manifest_payload = _validate_manifest_payload(payload)
    if manifest_payload is None:
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


def _validate_manifest_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    latest_file_name = payload.get("latest_file_name")
    retained_file_names = payload.get("retained_file_names")
    retention_limit = payload.get("retention_limit")
    retention_max_age_days = payload.get("retention_max_age_days")
    entries = payload.get("entries")

    if latest_file_name is not None and (
        not isinstance(latest_file_name, str) or not is_safe_evidence_file_name(latest_file_name)
    ):
        return None
    if not isinstance(retained_file_names, list) or any(
        not isinstance(item, str) or not is_safe_evidence_file_name(item) for item in retained_file_names
    ):
        return None
    if retention_limit is not None and not isinstance(retention_limit, int):
        return None
    if retention_max_age_days is not None and not isinstance(retention_max_age_days, int):
        return None
    if not isinstance(entries, list):
        return None

    validated_entries: list[dict[str, str | int | None]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        str_keys = ("evidence_file_name", "generated_at_utc", "operator_id", "cleanup_mode", "status")
        optional_str_keys = ("tenant_id", "correlation_id", "job_id")
        int_keys = (
            "retention_days",
            "prunable_execution_count",
            "prunable_compute_job_count",
            "prunable_async_result_count",
            "prunable_lineage_record_count",
            "prunable_lineage_artifact_count",
        )
        trigger_mode = entry.get("trigger_mode", "manual")
        if any(not isinstance(entry.get(key), str) for key in str_keys):
            return None
        if not is_safe_evidence_file_name(entry["evidence_file_name"]):
            return None
        if not isinstance(trigger_mode, str):
            return None
        if any(entry.get(key) is not None and not isinstance(entry.get(key), str) for key in optional_str_keys):
            return None
        if any(not isinstance(entry.get(key), int) for key in int_keys):
            return None
        validated_entry = {key: entry[key] for key in (*str_keys, *int_keys)}
        validated_entry["trigger_mode"] = trigger_mode
        validated_entry["tenant_id"] = entry.get("tenant_id")
        validated_entry["correlation_id"] = entry.get("correlation_id")
        validated_entry["job_id"] = entry.get("job_id")
        validated_entries.append(validated_entry)

    if latest_file_name is not None and latest_file_name not in retained_file_names:
        return None

    return {
        "latest_file_name": latest_file_name,
        "retained_file_names": list(retained_file_names),
        "retention_limit": retention_limit,
        "retention_max_age_days": retention_max_age_days,
        "entries": validated_entries,
    }


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
    filtered = entries
    if operator_id is not None:
        filtered = [entry for entry in filtered if entry.operator_id == operator_id]
    if trigger_mode is not None:
        filtered = [entry for entry in filtered if entry.trigger_mode == trigger_mode]
    if job_id is not None:
        filtered = [entry for entry in filtered if entry.job_id == job_id]
    if cleanup_mode is not None:
        filtered = [entry for entry in filtered if entry.cleanup_mode == cleanup_mode]
    if status_filter is not None:
        filtered = [entry for entry in filtered if entry.status == status_filter]
    if generated_after is not None:
        generated_after_dt = datetime.fromisoformat(generated_after.replace("Z", "+00:00"))
        filtered = [
            entry
            for entry in filtered
            if datetime.fromisoformat(entry.generated_at_utc.replace("Z", "+00:00")) >= generated_after_dt
        ]
    if generated_before is not None:
        generated_before_dt = datetime.fromisoformat(generated_before.replace("Z", "+00:00"))
        filtered = [
            entry
            for entry in filtered
            if datetime.fromisoformat(entry.generated_at_utc.replace("Z", "+00:00")) <= generated_before_dt
        ]
    return filtered


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
    filters: dict[str, str | int] = {}
    if limit is not None:
        filters["limit"] = limit
    if offset > 0:
        filters["offset"] = offset
    if operator_id is not None:
        filters["operator_id"] = operator_id
    if trigger_mode is not None:
        filters["trigger_mode"] = trigger_mode
    if job_id is not None:
        filters["job_id"] = job_id
    if cleanup_mode is not None:
        filters["cleanup_mode"] = cleanup_mode
    if status_filter is not None:
        filters["status"] = status_filter
    if generated_after is not None:
        filters["generated_after"] = generated_after
    if generated_before is not None:
        filters["generated_before"] = generated_before
    return filters
