from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.operator_action_history_filters import (
    build_applied_history_filters,
    filter_history_entries,
)
from app.services.operator_action_history_manifest import (
    validate_history_entry_strings,
    validate_history_manifest_header,
)
from app.services.operator_action_history_pagination import paginate_history_entries

RECOVERY_DRILL_ARTIFACT_DIRECTORY_MISSING_REASON = "recovery_drill_artifact_directory_missing"
RECOVERY_DRILL_MANIFEST_INVALID_REASON = "recovery_drill_manifest_invalid"
RECOVERY_DRILL_MANIFEST_MISSING_REASON = "recovery_drill_manifest_missing"
RECOVERY_DRILL_MANIFEST_UNREADABLE_REASON = "recovery_drill_manifest_unreadable"


@dataclass(frozen=True)
class RecoveryDrillHistoryEntry:
    evidence_file_name: str
    generated_at_utc: str
    operator_id: str
    backup_identifier: str
    status: str
    tenant_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class RecoveryDrillHistorySnapshot:
    status: str
    artifact_directory: str
    latest_file_name: str | None
    retained_file_names: list[str]
    retention_limit: int | None
    retention_max_age_days: int | None
    entries: list[RecoveryDrillHistoryEntry]
    total_entries: int
    matched_entries: int
    returned_entries: int
    next_offset: int | None
    applied_filters: dict[str, str | int]
    reason: str | None = None


def build_recovery_drill_history_snapshot(
    *,
    artifact_directory: Path | None = None,
    limit: int | None = None,
    offset: int = 0,
    operator_id: str | None = None,
    backup_identifier: str | None = None,
    status_filter: str | None = None,
    generated_after: str | None = None,
    generated_before: str | None = None,
) -> RecoveryDrillHistorySnapshot:
    directory = artifact_directory or get_settings().RECOVERY_DRILL_ARTIFACT_PATH
    manifest_path = directory / "manifest.json"
    applied_filters = _build_applied_filters(
        limit=limit,
        offset=offset,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status_filter,
        generated_after=generated_after,
        generated_before=generated_before,
    )

    if not directory.exists():
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RECOVERY_DRILL_ARTIFACT_DIRECTORY_MISSING_REASON,
        )

    if not manifest_path.exists():
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RECOVERY_DRILL_MANIFEST_MISSING_REASON,
        )

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RECOVERY_DRILL_MANIFEST_UNREADABLE_REASON,
        )
    except json.JSONDecodeError:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RECOVERY_DRILL_MANIFEST_INVALID_REASON,
        )
    manifest_payload = _validate_manifest_payload(payload)
    if manifest_payload is None:
        return _unavailable_snapshot(
            directory=directory,
            applied_filters=applied_filters,
            reason=RECOVERY_DRILL_MANIFEST_INVALID_REASON,
        )
    all_entries = [
        RecoveryDrillHistoryEntry(
            evidence_file_name=entry["evidence_file_name"],
            generated_at_utc=entry["generated_at_utc"],
            operator_id=entry["operator_id"],
            tenant_id=entry["tenant_id"],
            correlation_id=entry["correlation_id"],
            backup_identifier=entry["backup_identifier"],
            status=entry["status"],
        )
        for entry in manifest_payload["entries"]
    ]
    filtered_entries = _filter_entries(
        entries=all_entries,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status_filter,
        generated_after=generated_after,
        generated_before=generated_before,
    )
    page = paginate_history_entries(filtered_entries, limit=limit, offset=offset)
    return RecoveryDrillHistorySnapshot(
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
) -> RecoveryDrillHistorySnapshot:
    return RecoveryDrillHistorySnapshot(
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
    header = validate_history_manifest_header(payload)
    if header is None:
        return None

    validated_entries: list[dict[str, str | None]] = []
    for entry in header.entries:
        validated_entry = _validate_manifest_entry(entry)
        if validated_entry is None:
            return None
        validated_entries.append(validated_entry)

    return {
        "latest_file_name": header.latest_file_name,
        "retained_file_names": header.retained_file_names,
        "retention_limit": header.retention_limit,
        "retention_max_age_days": header.retention_max_age_days,
        "entries": validated_entries,
    }


def _validate_manifest_entry(entry: Any) -> dict[str, str | None] | None:
    if not isinstance(entry, dict):
        return None
    entry_strings = validate_history_entry_strings(
        entry,
        required_keys=("evidence_file_name", "generated_at_utc", "operator_id", "backup_identifier", "status"),
        optional_keys=("tenant_id", "correlation_id"),
    )
    if entry_strings is None:
        return None
    return {
        "evidence_file_name": entry_strings["evidence_file_name"],
        "generated_at_utc": entry_strings["generated_at_utc"],
        "operator_id": entry_strings["operator_id"],
        "tenant_id": entry_strings["tenant_id"],
        "correlation_id": entry_strings["correlation_id"],
        "backup_identifier": entry_strings["backup_identifier"],
        "status": entry_strings["status"],
    }


def _filter_entries(
    *,
    entries: list[RecoveryDrillHistoryEntry],
    operator_id: str | None,
    backup_identifier: str | None,
    status_filter: str | None,
    generated_after: str | None,
    generated_before: str | None,
) -> list[RecoveryDrillHistoryEntry]:
    return filter_history_entries(
        entries,
        exact_filters=(
            (operator_id, lambda entry: entry.operator_id),
            (backup_identifier, lambda entry: entry.backup_identifier),
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
    backup_identifier: str | None,
    status_filter: str | None,
    generated_after: str | None,
    generated_before: str | None,
) -> dict[str, str | int]:
    return build_applied_history_filters(
        limit=limit,
        offset=offset,
        optional_filters=(
            ("operator_id", operator_id),
            ("backup_identifier", backup_identifier),
            ("status", status_filter),
        ),
        generated_after=generated_after,
        generated_before=generated_before,
    )
