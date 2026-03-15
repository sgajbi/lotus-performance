from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, status


@dataclass(frozen=True)
class OperatorActionLeaseMetadata:
    action_name: str
    operator_id: str
    tenant_id: str | None
    governed_target: str
    acquired_at_utc: str


def build_runtime_retention_action_key(
    *,
    operator_id: str,
    tenant_id: str | None,
    apply: bool,
    retention_days: int,
    job_id: str | None,
) -> str:
    return _sanitize_key(
        "runtime-retention",
        operator_id,
        tenant_id or "no-tenant",
        "apply" if apply else "dry-run",
        str(retention_days),
        job_id or "no-job",
    )


def build_recovery_drill_action_key(
    *,
    operator_id: str,
    tenant_id: str | None,
    backup_identifier: str,
) -> str:
    return _sanitize_key(
        "recovery-drill",
        operator_id,
        tenant_id or "no-tenant",
        backup_identifier,
    )


@contextmanager
def operator_action_lease(
    *,
    artifact_directory: Path,
    action_key: str,
    metadata: OperatorActionLeaseMetadata,
    stale_after_seconds: float,
    now_utc: datetime | None = None,
) -> Iterator[None]:
    locks_dir = artifact_directory / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{action_key}.lock"
    payload = json.dumps(asdict(metadata), indent=2)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        if _reclaim_stale_lock(
            lock_path=lock_path,
            stale_after_seconds=stale_after_seconds,
            now_utc=now_utc,
        ):
            fd = os.open(str(lock_path), flags)
        else:
            detail: dict[str, object] = {
                "code": f"{metadata.action_name}_already_running",
                "message": (
                    f"A governed {metadata.action_name} for this same risk unit is already running. "
                    "Wait for the active action to complete before retrying."
                ),
                "action_key": action_key,
            }
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
            if isinstance(existing, dict):
                active_operator_id = existing.get("operator_id")
                active_tenant_id = existing.get("tenant_id")
                governed_target = existing.get("governed_target")
                acquired_at_utc = existing.get("acquired_at_utc")
                detail["active_operator_id"] = active_operator_id if isinstance(active_operator_id, str) else None
                detail["active_tenant_id"] = active_tenant_id if isinstance(active_tenant_id, str) else None
                detail["governed_target"] = governed_target if isinstance(governed_target, str) else None
                detail["active_acquired_at_utc"] = acquired_at_utc if isinstance(acquired_at_utc, str) else None
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _sanitize_key(*parts: str) -> str:
    sanitized = [re.sub(r"[^0-9A-Za-z]+", "-", part).strip("-").lower() for part in parts]
    return "-".join(part for part in sanitized if part)


def _reclaim_stale_lock(
    *,
    lock_path: Path,
    stale_after_seconds: float,
    now_utc: datetime | None,
) -> bool:
    if stale_after_seconds <= 0:
        return False
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    acquired_at_utc = payload.get("acquired_at_utc")
    if not isinstance(acquired_at_utc, str):
        return False
    current_time = now_utc or datetime.now(UTC)
    acquired_at = datetime.fromisoformat(acquired_at_utc.replace("Z", "+00:00"))
    if acquired_at.tzinfo is None:
        acquired_at = acquired_at.replace(tzinfo=UTC)
    else:
        acquired_at = acquired_at.astimezone(UTC)
    if (current_time - acquired_at).total_seconds() <= stale_after_seconds:
        return False
    lock_path.unlink(missing_ok=True)
    return True
