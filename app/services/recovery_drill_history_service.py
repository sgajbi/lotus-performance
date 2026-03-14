from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class RecoveryDrillHistoryEntry:
    evidence_file_name: str
    generated_at_utc: str
    operator_id: str
    backup_identifier: str
    status: str


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
    returned_entries: int
    applied_filters: dict[str, str | int]
    reason: str | None = None


def build_recovery_drill_history_snapshot(
    *,
    artifact_directory: Path | None = None,
    limit: int | None = None,
    operator_id: str | None = None,
    backup_identifier: str | None = None,
    status_filter: str | None = None,
) -> RecoveryDrillHistorySnapshot:
    directory = artifact_directory or settings.RECOVERY_DRILL_ARTIFACT_PATH
    manifest_path = directory / "manifest.json"
    applied_filters = _build_applied_filters(
        limit=limit,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status_filter,
    )

    if not directory.exists():
        return RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory=str(directory),
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=None,
            retention_max_age_days=None,
            entries=[],
            total_entries=0,
            returned_entries=0,
            applied_filters=applied_filters,
            reason="recovery_drill_artifact_directory_missing",
        )

    if not manifest_path.exists():
        return RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory=str(directory),
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=None,
            retention_max_age_days=None,
            entries=[],
            total_entries=0,
            returned_entries=0,
            applied_filters=applied_filters,
            reason="recovery_drill_manifest_missing",
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_entries = [
        RecoveryDrillHistoryEntry(
            evidence_file_name=entry["evidence_file_name"],
            generated_at_utc=entry["generated_at_utc"],
            operator_id=entry["operator_id"],
            backup_identifier=entry["backup_identifier"],
            status=entry["status"],
        )
        for entry in payload.get("entries", [])
    ]
    filtered_entries = _filter_entries(
        entries=all_entries,
        operator_id=operator_id,
        backup_identifier=backup_identifier,
        status_filter=status_filter,
    )
    if limit is not None:
        filtered_entries = filtered_entries[:limit]
    return RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(directory),
        latest_file_name=payload.get("latest_file_name"),
        retained_file_names=list(payload.get("retained_file_names", [])),
        retention_limit=payload.get("retention_limit"),
        retention_max_age_days=payload.get("retention_max_age_days"),
        entries=filtered_entries,
        total_entries=len(all_entries),
        returned_entries=len(filtered_entries),
        applied_filters=applied_filters,
        reason=None,
    )


def _filter_entries(
    *,
    entries: list[RecoveryDrillHistoryEntry],
    operator_id: str | None,
    backup_identifier: str | None,
    status_filter: str | None,
) -> list[RecoveryDrillHistoryEntry]:
    filtered = entries
    if operator_id is not None:
        filtered = [entry for entry in filtered if entry.operator_id == operator_id]
    if backup_identifier is not None:
        filtered = [entry for entry in filtered if entry.backup_identifier == backup_identifier]
    if status_filter is not None:
        filtered = [entry for entry in filtered if entry.status == status_filter]
    return filtered


def _build_applied_filters(
    *,
    limit: int | None,
    operator_id: str | None,
    backup_identifier: str | None,
    status_filter: str | None,
) -> dict[str, str | int]:
    filters: dict[str, str | int] = {}
    if limit is not None:
        filters["limit"] = limit
    if operator_id is not None:
        filters["operator_id"] = operator_id
    if backup_identifier is not None:
        filters["backup_identifier"] = backup_identifier
    if status_filter is not None:
        filters["status"] = status_filter
    return filters
