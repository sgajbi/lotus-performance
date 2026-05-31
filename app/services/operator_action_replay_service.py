from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.operator_action_evidence_paths import resolve_evidence_file_path
from app.services.recovery_drill_history_service import RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionReplayResult:
    payload: dict[str, Any]
    evidence_file_name: str


class _OperatorReplayIdentity(Protocol):
    operator_id: str
    tenant_id: str | None
    correlation_id: str | None


def resolve_runtime_retention_manual_replay(
    snapshot: RuntimeRetentionHistorySnapshot,
    *,
    artifact_directory: Path,
    operator_id: str,
    tenant_id: str | None,
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
            operator_id=operator_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            apply=apply,
            retention_days=retention_days,
            job_id=job_id,
        ):
            continue
        payload = _load_payload(artifact_directory=artifact_directory, evidence_file_name=entry.evidence_file_name)
        if payload is None:
            return None
        return ActionReplayResult(payload=payload, evidence_file_name=entry.evidence_file_name)
    return None


def resolve_recovery_drill_manual_replay(
    snapshot: RecoveryDrillHistorySnapshot,
    *,
    artifact_directory: Path,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str | None,
    backup_identifier: str,
) -> ActionReplayResult | None:
    if not correlation_id:
        return None
    for entry in snapshot.entries:
        if not _operator_replay_identity_matches(
            entry,
            operator_id=operator_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        ):
            continue
        if entry.backup_identifier != backup_identifier:
            continue
        payload = _load_payload(artifact_directory=artifact_directory, evidence_file_name=entry.evidence_file_name)
        if payload is None:
            return None
        return ActionReplayResult(payload=payload, evidence_file_name=entry.evidence_file_name)
    return None


def _runtime_retention_entry_matches(
    entry: RuntimeRetentionHistoryEntry,
    *,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str,
    apply: bool,
    retention_days: int | None,
    job_id: str | None,
) -> bool:
    expected_cleanup_mode = "apply" if apply else "dry_run"
    if not _operator_replay_identity_matches(
        entry,
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
    ):
        return False
    if entry.cleanup_mode != expected_cleanup_mode:
        return False
    if retention_days is not None and entry.retention_days != retention_days:
        return False
    if entry.job_id != job_id:
        return False
    return True


def _operator_replay_identity_matches(
    entry: _OperatorReplayIdentity,
    *,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str,
) -> bool:
    return entry.operator_id == operator_id and entry.tenant_id == tenant_id and entry.correlation_id == correlation_id


def _load_payload(*, artifact_directory: Path, evidence_file_name: str) -> dict[str, Any] | None:
    path = _evidence_file_path(artifact_directory=artifact_directory, evidence_file_name=evidence_file_name)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("Operator action replay evidence unreadable: %s", evidence_file_name, exc_info=True)
        return None
    except json.JSONDecodeError:
        logger.warning("Operator action replay evidence invalid JSON: %s", evidence_file_name, exc_info=True)
        return None
    if not isinstance(payload, dict):
        logger.warning(
            "Operator action replay evidence ignored because payload is not an object: %s", evidence_file_name
        )
        return None
    return payload


def _evidence_file_path(*, artifact_directory: Path, evidence_file_name: str) -> Path | None:
    evidence_path = resolve_evidence_file_path(
        artifact_directory=artifact_directory, evidence_file_name=evidence_file_name
    )
    if evidence_path is None:
        logger.warning("Skipping evidence file outside operator action artifact directory: %s", evidence_file_name)
        return None
    return evidence_path
