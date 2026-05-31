from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.operator_action_evidence_paths import is_safe_evidence_file_name
from app.services.operator_action_history_filters import (
    build_applied_history_filters,
    generated_at_within_bounds,
    parse_generated_at_bounds,
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

    validated_entries: list[dict[str, str | None]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        required = (
            entry.get("evidence_file_name"),
            entry.get("generated_at_utc"),
            entry.get("operator_id"),
            entry.get("backup_identifier"),
            entry.get("status"),
        )
        if any(not isinstance(value, str) for value in required):
            return None
        if not is_safe_evidence_file_name(entry["evidence_file_name"]):
            return None
        if entry.get("tenant_id") is not None and not isinstance(entry.get("tenant_id"), str):
            return None
        if entry.get("correlation_id") is not None and not isinstance(entry.get("correlation_id"), str):
            return None
        validated_entries.append(
            {
                "evidence_file_name": entry["evidence_file_name"],
                "generated_at_utc": entry["generated_at_utc"],
                "operator_id": entry["operator_id"],
                "tenant_id": entry.get("tenant_id"),
                "correlation_id": entry.get("correlation_id"),
                "backup_identifier": entry["backup_identifier"],
                "status": entry["status"],
            }
        )

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
    entries: list[RecoveryDrillHistoryEntry],
    operator_id: str | None,
    backup_identifier: str | None,
    status_filter: str | None,
    generated_after: str | None,
    generated_before: str | None,
) -> list[RecoveryDrillHistoryEntry]:
    filtered = entries
    if operator_id is not None:
        filtered = [entry for entry in filtered if entry.operator_id == operator_id]
    if backup_identifier is not None:
        filtered = [entry for entry in filtered if entry.backup_identifier == backup_identifier]
    if status_filter is not None:
        filtered = [entry for entry in filtered if entry.status == status_filter]
    generated_at_bounds = parse_generated_at_bounds(
        generated_after=generated_after,
        generated_before=generated_before,
    )
    if generated_at_bounds.has_bounds:
        filtered = [
            entry
            for entry in filtered
            if generated_at_within_bounds(entry.generated_at_utc, bounds=generated_at_bounds)
        ]
    return filtered


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
