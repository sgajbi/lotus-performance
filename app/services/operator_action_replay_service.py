from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.recovery_drill_history_service import RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)


@dataclass(frozen=True)
class ActionReplayResult:
    payload: dict[str, Any]
    evidence_file_name: str


def resolve_runtime_retention_manual_replay(
    snapshot: RuntimeRetentionHistorySnapshot,
    *,
    artifact_directory: Path,
    correlation_id: str | None,
    apply: bool,
    retention_days: int | None,
    job_id: str | None,
) -> ActionReplayResult | None:
    if not correlation_id:
        return None
    for entry in snapshot.entries:
        if not _runtime_retention_entry_matches(
            entry,
            correlation_id=correlation_id,
            apply=apply,
            retention_days=retention_days,
            job_id=job_id,
        ):
            continue
        payload = _load_payload(artifact_directory / entry.evidence_file_name)
        if payload is None:
            return None
        return ActionReplayResult(payload=payload, evidence_file_name=entry.evidence_file_name)
    return None


def resolve_recovery_drill_manual_replay(
    snapshot: RecoveryDrillHistorySnapshot,
    *,
    artifact_directory: Path,
    correlation_id: str | None,
    backup_identifier: str,
) -> ActionReplayResult | None:
    if not correlation_id:
        return None
    for entry in snapshot.entries:
        if entry.correlation_id != correlation_id or entry.backup_identifier != backup_identifier:
            continue
        payload = _load_payload(artifact_directory / entry.evidence_file_name)
        if payload is None:
            return None
        return ActionReplayResult(payload=payload, evidence_file_name=entry.evidence_file_name)
    return None


def _runtime_retention_entry_matches(
    entry: RuntimeRetentionHistoryEntry,
    *,
    correlation_id: str,
    apply: bool,
    retention_days: int | None,
    job_id: str | None,
) -> bool:
    expected_cleanup_mode = "apply" if apply else "dry_run"
    if entry.correlation_id != correlation_id:
        return False
    if entry.cleanup_mode != expected_cleanup_mode:
        return False
    if retention_days is not None and entry.retention_days != retention_days:
        return False
    if entry.job_id != job_id:
        return False
    return True


def _load_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
