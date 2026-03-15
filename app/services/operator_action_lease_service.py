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


@dataclass(frozen=True)
class ActiveOperatorActionLease:
    action_key: str
    action_name: str
    operator_id: str
    tenant_id: str | None
    governed_target: str
    acquired_at_utc: str


@dataclass(frozen=True)
class OperatorActionLeaseSnapshot:
    status: str
    reason: str | None
    active_leases: tuple[ActiveOperatorActionLease, ...]
    latest_reclaimed_lease: "ReclaimedOperatorActionLeaseEvent | None"


@dataclass(frozen=True)
class ReclaimedOperatorActionLeaseEvent:
    action_key: str
    action_name: str
    operator_id: str
    tenant_id: str | None
    governed_target: str
    acquired_at_utc: str
    reclaimed_at_utc: str
    stale_after_seconds: float
    reclaim_count: int


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
            action_key=action_key,
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


def build_operator_action_lease_snapshot(
    *,
    artifact_directory: Path,
    action_name: str | None = None,
) -> OperatorActionLeaseSnapshot:
    locks_dir = artifact_directory / ".action-locks"
    if not locks_dir.exists():
        return OperatorActionLeaseSnapshot(
            status="available",
            reason=None,
            active_leases=(),
            latest_reclaimed_lease=None,
        )
    try:
        leases: list[ActiveOperatorActionLease | _InvalidLease] = []
        for lock_path in sorted(locks_dir.glob("*.lock")):
            lease = _read_active_operator_action_lease(lock_path=lock_path)
            if lease is None:
                continue
            if not isinstance(lease, ActiveOperatorActionLease):
                leases.append(lease)
                continue
            if action_name is None or lease.action_name == action_name:
                leases.append(lease)
    except OSError:
        return OperatorActionLeaseSnapshot(
            status="unavailable",
            reason="operator_action_lease_directory_unreadable",
            active_leases=(),
            latest_reclaimed_lease=None,
        )
    if any(lease is _INVALID_LEASE for lease in leases):
        return OperatorActionLeaseSnapshot(
            status="unavailable",
            reason="operator_action_lease_invalid",
            active_leases=(),
            latest_reclaimed_lease=None,
        )
    latest_reclaimed_lease_candidate = _read_latest_reclaimed_lease(locks_dir=locks_dir, action_name=action_name)
    if latest_reclaimed_lease_candidate is _INVALID_LEASE:
        return OperatorActionLeaseSnapshot(
            status="unavailable",
            reason="operator_action_reclaim_event_invalid",
            active_leases=(),
            latest_reclaimed_lease=None,
        )
    latest_reclaimed_lease = (
        latest_reclaimed_lease_candidate
        if isinstance(latest_reclaimed_lease_candidate, ReclaimedOperatorActionLeaseEvent)
        else None
    )
    typed_leases = tuple(
        sorted(
            (lease for lease in leases if isinstance(lease, ActiveOperatorActionLease)),
            key=lambda item: _parse_utc(item.acquired_at_utc),
        )
    )
    return OperatorActionLeaseSnapshot(
        status="available",
        reason=None,
        active_leases=typed_leases,
        latest_reclaimed_lease=latest_reclaimed_lease,
    )


def _sanitize_key(*parts: str) -> str:
    sanitized = [re.sub(r"[^0-9A-Za-z]+", "-", part).strip("-").lower() for part in parts]
    return "-".join(part for part in sanitized if part)


class _InvalidLease:
    pass


_INVALID_LEASE = _InvalidLease()


def _read_active_operator_action_lease(*, lock_path: Path) -> ActiveOperatorActionLease | _InvalidLease | None:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _INVALID_LEASE
    if not isinstance(payload, dict):
        return _INVALID_LEASE
    action_name = payload.get("action_name")
    operator_id = payload.get("operator_id")
    tenant_id = payload.get("tenant_id")
    governed_target = payload.get("governed_target")
    acquired_at_utc = payload.get("acquired_at_utc")
    if not isinstance(action_name, str):
        return _INVALID_LEASE
    if not isinstance(operator_id, str):
        return _INVALID_LEASE
    if tenant_id is not None and not isinstance(tenant_id, str):
        return _INVALID_LEASE
    if not isinstance(governed_target, str):
        return _INVALID_LEASE
    if not isinstance(acquired_at_utc, str):
        return _INVALID_LEASE
    try:
        _parse_utc(acquired_at_utc)
    except ValueError:
        return _INVALID_LEASE
    return ActiveOperatorActionLease(
        action_key=lock_path.stem,
        action_name=action_name,
        operator_id=operator_id,
        tenant_id=tenant_id,
        governed_target=governed_target,
        acquired_at_utc=acquired_at_utc,
    )


def _read_latest_reclaimed_lease(
    *,
    locks_dir: Path,
    action_name: str | None,
) -> ReclaimedOperatorActionLeaseEvent | _InvalidLease | None:
    latest_reclaim_path = locks_dir / "latest-reclaim.json"
    if not latest_reclaim_path.exists():
        return None
    try:
        payload = json.loads(latest_reclaim_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _INVALID_LEASE
    if not isinstance(payload, dict):
        return _INVALID_LEASE
    candidate_action_name = payload.get("action_name")
    if not isinstance(candidate_action_name, str):
        return _INVALID_LEASE
    if action_name is not None and candidate_action_name != action_name:
        return None
    operator_id = payload.get("operator_id")
    tenant_id = payload.get("tenant_id")
    governed_target = payload.get("governed_target")
    acquired_at_utc = payload.get("acquired_at_utc")
    reclaimed_at_utc = payload.get("reclaimed_at_utc")
    stale_after_seconds = payload.get("stale_after_seconds")
    reclaim_count = payload.get("reclaim_count", 1)
    action_key = payload.get("action_key")
    if not isinstance(operator_id, str):
        return _INVALID_LEASE
    if tenant_id is not None and not isinstance(tenant_id, str):
        return _INVALID_LEASE
    if not isinstance(governed_target, str):
        return _INVALID_LEASE
    if not isinstance(acquired_at_utc, str):
        return _INVALID_LEASE
    if not isinstance(reclaimed_at_utc, str):
        return _INVALID_LEASE
    if not isinstance(stale_after_seconds, (int, float)):
        return _INVALID_LEASE
    if not isinstance(reclaim_count, int):
        return _INVALID_LEASE
    if not isinstance(action_key, str):
        return _INVALID_LEASE
    try:
        _parse_utc(acquired_at_utc)
        _parse_utc(reclaimed_at_utc)
    except ValueError:
        return _INVALID_LEASE
    return ReclaimedOperatorActionLeaseEvent(
        action_key=action_key,
        action_name=candidate_action_name,
        operator_id=operator_id,
        tenant_id=tenant_id,
        governed_target=governed_target,
        acquired_at_utc=acquired_at_utc,
        reclaimed_at_utc=reclaimed_at_utc,
        stale_after_seconds=float(stale_after_seconds),
        reclaim_count=reclaim_count,
    )


def _write_latest_reclaimed_lease(*, locks_dir: Path, event: ReclaimedOperatorActionLeaseEvent) -> None:
    latest_reclaim_path = locks_dir / "latest-reclaim.json"
    temp_path = locks_dir / "latest-reclaim.json.tmp"
    prior_count = 0
    existing = _read_latest_reclaimed_lease(locks_dir=locks_dir, action_name=event.action_name)
    if isinstance(existing, ReclaimedOperatorActionLeaseEvent):
        prior_count = existing.reclaim_count
    updated_event = ReclaimedOperatorActionLeaseEvent(
        action_key=event.action_key,
        action_name=event.action_name,
        operator_id=event.operator_id,
        tenant_id=event.tenant_id,
        governed_target=event.governed_target,
        acquired_at_utc=event.acquired_at_utc,
        reclaimed_at_utc=event.reclaimed_at_utc,
        stale_after_seconds=event.stale_after_seconds,
        reclaim_count=prior_count + 1,
    )
    payload = json.dumps(asdict(updated_event), indent=2)
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, latest_reclaim_path)


def _parse_utc(timestamp_utc: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _reclaim_stale_lock(
    *,
    lock_path: Path,
    stale_after_seconds: float,
    action_key: str,
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
    action_name = payload.get("action_name")
    operator_id = payload.get("operator_id")
    tenant_id = payload.get("tenant_id")
    governed_target = payload.get("governed_target")
    acquired_at_utc = payload.get("acquired_at_utc")
    if not isinstance(action_name, str):
        return False
    if not isinstance(operator_id, str):
        return False
    if tenant_id is not None and not isinstance(tenant_id, str):
        return False
    if not isinstance(governed_target, str):
        return False
    if not isinstance(acquired_at_utc, str):
        return False
    current_time = now_utc or datetime.now(UTC)
    acquired_at = _parse_utc(acquired_at_utc)
    if (current_time - acquired_at).total_seconds() <= stale_after_seconds:
        return False
    lock_path.unlink(missing_ok=True)
    try:
        _write_latest_reclaimed_lease(
            locks_dir=lock_path.parent,
            event=ReclaimedOperatorActionLeaseEvent(
                action_key=action_key,
                action_name=action_name,
                operator_id=operator_id,
                tenant_id=tenant_id,
                governed_target=governed_target,
                acquired_at_utc=acquired_at_utc,
                reclaimed_at_utc=current_time.isoformat().replace("+00:00", "Z"),
                stale_after_seconds=stale_after_seconds,
                reclaim_count=0,
            ),
        )
    except OSError:
        pass
    return True
