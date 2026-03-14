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
    reason: str | None = None


def build_recovery_drill_history_snapshot(
    *, artifact_directory: Path | None = None
) -> RecoveryDrillHistorySnapshot:
    directory = artifact_directory or settings.RECOVERY_DRILL_ARTIFACT_PATH
    manifest_path = directory / "manifest.json"

    if not directory.exists():
        return RecoveryDrillHistorySnapshot(
            status="unavailable",
            artifact_directory=str(directory),
            latest_file_name=None,
            retained_file_names=[],
            retention_limit=None,
            retention_max_age_days=None,
            entries=[],
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
            reason="recovery_drill_manifest_missing",
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [
        RecoveryDrillHistoryEntry(
            evidence_file_name=entry["evidence_file_name"],
            generated_at_utc=entry["generated_at_utc"],
            operator_id=entry["operator_id"],
            backup_identifier=entry["backup_identifier"],
            status=entry["status"],
        )
        for entry in payload.get("entries", [])
    ]
    return RecoveryDrillHistorySnapshot(
        status="available",
        artifact_directory=str(directory),
        latest_file_name=payload.get("latest_file_name"),
        retained_file_names=list(payload.get("retained_file_names", [])),
        retention_limit=payload.get("retention_limit"),
        retention_max_age_days=payload.get("retention_max_age_days"),
        entries=entries,
        reason=None,
    )
