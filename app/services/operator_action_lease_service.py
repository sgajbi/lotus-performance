from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, cast

from fastapi import HTTPException, status

from app.services import operator_action_evidence_strings as _evidence_strings
from app.services.durable_store_json import read_json_file
from app.services.runtime_status_time import parse_utc_datetime

OPERATOR_ACTION_LEASE_DIRECTORY_UNREADABLE_REASON = "operator_action_lease_directory_unreadable"
OPERATOR_ACTION_LEASE_INVALID_REASON = "operator_action_lease_invalid"
OPERATOR_ACTION_RECLAIM_EVENT_INVALID_REASON = "operator_action_reclaim_event_invalid"
OPERATOR_ACTION_RECLAIM_HISTORY_INVALID_REASON = "operator_action_reclaim_history_invalid"

logger = logging.getLogger(__name__)

_is_optional_lease_string = _evidence_strings.is_optional_evidence_string
_is_required_lease_string = _evidence_strings.is_required_evidence_string
_normalize_optional_lease_string = _evidence_strings.normalize_optional_evidence_identifier
_normalize_required_lease_string = _evidence_strings.normalize_required_evidence_identifier


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
    recent_reclaimed_leases: tuple["ReclaimedOperatorActionLeaseEvent", ...]


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
    normalized_operator_id = _normalize_required_lease_string(operator_id, field_name="operator_id")
    normalized_tenant_id = _normalize_optional_lease_string(tenant_id)
    normalized_job_id = _normalize_optional_lease_string(job_id)
    return _sanitize_key(
        "runtime-retention",
        normalized_operator_id,
        normalized_tenant_id or "no-tenant",
        "apply" if apply else "dry-run",
        str(retention_days),
        normalized_job_id or "no-job",
    )


def build_recovery_drill_action_key(
    *,
    operator_id: str,
    tenant_id: str | None,
    backup_identifier: str,
) -> str:
    normalized_operator_id = _normalize_required_lease_string(operator_id, field_name="operator_id")
    normalized_tenant_id = _normalize_optional_lease_string(tenant_id)
    normalized_backup_identifier = _normalize_required_lease_string(
        backup_identifier,
        field_name="backup_identifier",
    )
    return _sanitize_key(
        "recovery-drill",
        normalized_operator_id,
        normalized_tenant_id or "no-tenant",
        normalized_backup_identifier,
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
    normalized_action_key = _normalize_required_lease_string(action_key, field_name="action_key")
    normalized_metadata = _normalize_lease_metadata(metadata)
    locks_dir = artifact_directory / ".action-locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{normalized_action_key}.lock"
    payload = json.dumps(asdict(normalized_metadata), indent=2)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        if _reclaim_stale_lock(
            lock_path=lock_path,
            stale_after_seconds=stale_after_seconds,
            action_key=normalized_action_key,
            now_utc=now_utc,
        ):
            fd = os.open(str(lock_path), flags)
        else:
            detail: dict[str, object] = {
                "code": f"{normalized_metadata.action_name}_already_running",
                "message": (
                    f"A governed {normalized_metadata.action_name} for this same risk unit is already running. "
                    "Wait for the active action to complete before retrying."
                ),
                "action_key": normalized_action_key,
            }
            active_lease = _read_active_operator_action_lease(lock_path=lock_path)
            if isinstance(active_lease, ActiveOperatorActionLease):
                detail["active_operator_id"] = active_lease.operator_id
                detail["active_tenant_id"] = active_lease.tenant_id
                detail["governed_target"] = active_lease.governed_target
                detail["active_acquired_at_utc"] = active_lease.acquired_at_utc
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
            recent_reclaimed_leases=(),
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
            reason=OPERATOR_ACTION_LEASE_DIRECTORY_UNREADABLE_REASON,
            active_leases=(),
            latest_reclaimed_lease=None,
            recent_reclaimed_leases=(),
        )
    if any(lease is _INVALID_LEASE for lease in leases):
        return OperatorActionLeaseSnapshot(
            status="unavailable",
            reason=OPERATOR_ACTION_LEASE_INVALID_REASON,
            active_leases=(),
            latest_reclaimed_lease=None,
            recent_reclaimed_leases=(),
        )
    latest_reclaimed_lease_candidate = _read_latest_reclaimed_lease(locks_dir=locks_dir, action_name=action_name)
    if latest_reclaimed_lease_candidate is _INVALID_LEASE:
        return OperatorActionLeaseSnapshot(
            status="unavailable",
            reason=OPERATOR_ACTION_RECLAIM_EVENT_INVALID_REASON,
            active_leases=(),
            latest_reclaimed_lease=None,
            recent_reclaimed_leases=(),
        )
    recent_reclaimed_leases_candidate = _read_recent_reclaimed_leases(locks_dir=locks_dir, action_name=action_name)
    if recent_reclaimed_leases_candidate is _INVALID_LEASE:
        return OperatorActionLeaseSnapshot(
            status="unavailable",
            reason=OPERATOR_ACTION_RECLAIM_HISTORY_INVALID_REASON,
            active_leases=(),
            latest_reclaimed_lease=None,
            recent_reclaimed_leases=(),
        )
    recent_reclaimed_leases = (
        recent_reclaimed_leases_candidate if isinstance(recent_reclaimed_leases_candidate, tuple) else ()
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
        recent_reclaimed_leases=recent_reclaimed_leases,
    )


def _sanitize_key(*parts: str) -> str:
    sanitized = [re.sub(r"[^0-9A-Za-z]+", "-", part).strip("-").lower() for part in parts]
    return "-".join(part for part in sanitized if part)


class _InvalidLease:
    pass


_INVALID_LEASE = _InvalidLease()
_RECLAIM_HISTORY_LIMIT = 20


def _normalize_lease_metadata(metadata: OperatorActionLeaseMetadata) -> OperatorActionLeaseMetadata:
    acquired_at_utc = _normalize_required_lease_string(metadata.acquired_at_utc, field_name="acquired_at_utc")
    _parse_utc(acquired_at_utc)
    return OperatorActionLeaseMetadata(
        action_name=_normalize_required_lease_string(metadata.action_name, field_name="action_name"),
        operator_id=_normalize_required_lease_string(metadata.operator_id, field_name="operator_id"),
        tenant_id=_normalize_optional_lease_string(metadata.tenant_id),
        governed_target=_normalize_required_lease_string(metadata.governed_target, field_name="governed_target"),
        acquired_at_utc=acquired_at_utc,
    )


def _read_active_operator_action_lease(*, lock_path: Path) -> ActiveOperatorActionLease | _InvalidLease | None:
    payload = _read_json_payload(lock_path)
    if payload is _INVALID_LEASE:
        return _INVALID_LEASE
    if not isinstance(payload, dict):
        return _INVALID_LEASE
    action_name = payload.get("action_name")
    operator_id = payload.get("operator_id")
    tenant_id = payload.get("tenant_id")
    governed_target = payload.get("governed_target")
    acquired_at_utc = payload.get("acquired_at_utc")
    if not _is_required_lease_string(action_name):
        return _INVALID_LEASE
    if not _is_required_lease_string(operator_id):
        return _INVALID_LEASE
    if not _is_optional_lease_string(tenant_id):
        return _INVALID_LEASE
    if not _is_required_lease_string(governed_target):
        return _INVALID_LEASE
    if not _is_required_lease_string(acquired_at_utc):
        return _INVALID_LEASE
    action_name_value = cast(str, action_name)
    operator_id_value = cast(str, operator_id)
    tenant_id_value = cast(str | None, tenant_id)
    governed_target_value = cast(str, governed_target)
    acquired_at_utc_value = cast(str, acquired_at_utc)
    try:
        _parse_utc(acquired_at_utc_value)
    except ValueError:
        return _INVALID_LEASE
    return ActiveOperatorActionLease(
        action_key=lock_path.stem,
        action_name=action_name_value,
        operator_id=operator_id_value,
        tenant_id=tenant_id_value,
        governed_target=governed_target_value,
        acquired_at_utc=acquired_at_utc_value,
    )


def _read_latest_reclaimed_lease(
    *,
    locks_dir: Path,
    action_name: str | None,
) -> ReclaimedOperatorActionLeaseEvent | _InvalidLease | None:
    latest_reclaim_path = locks_dir / "latest-reclaim.json"
    if not latest_reclaim_path.exists():
        return None
    payload = _read_json_payload(latest_reclaim_path)
    if payload is _INVALID_LEASE:
        return _INVALID_LEASE
    return _parse_reclaimed_event_payload(payload=payload, action_name=action_name)


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
    _write_reclaim_history(locks_dir=locks_dir, event=updated_event)


def _read_recent_reclaimed_leases(
    *,
    locks_dir: Path,
    action_name: str | None,
) -> tuple[ReclaimedOperatorActionLeaseEvent, ...] | _InvalidLease:
    reclaim_history_path = locks_dir / "reclaim-history.json"
    if not reclaim_history_path.exists():
        return ()
    payload = _read_json_payload(reclaim_history_path)
    if payload is _INVALID_LEASE:
        return _INVALID_LEASE
    if not isinstance(payload, list):
        return _INVALID_LEASE
    events: list[ReclaimedOperatorActionLeaseEvent] = []
    for item in payload:
        event = _parse_reclaimed_event_payload(payload=item, action_name=action_name)
        if event is _INVALID_LEASE:
            return _INVALID_LEASE
        if isinstance(event, ReclaimedOperatorActionLeaseEvent):
            events.append(event)
    return tuple(events)


def _write_reclaim_history(*, locks_dir: Path, event: ReclaimedOperatorActionLeaseEvent) -> None:
    reclaim_history_path = locks_dir / "reclaim-history.json"
    temp_path = locks_dir / "reclaim-history.json.tmp"
    prior_events = _read_recent_reclaimed_leases(locks_dir=locks_dir, action_name=None)
    persisted_history = [event]
    if isinstance(prior_events, tuple):
        persisted_history.extend(prior_events)
    payload = json.dumps([asdict(item) for item in persisted_history[:_RECLAIM_HISTORY_LIMIT]], indent=2)
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, reclaim_history_path)


def _read_json_payload(path: Path) -> object | _InvalidLease:
    try:
        return read_json_file(path)
    except OSError:
        logger.warning("Operator action lease evidence unreadable: %s", path, exc_info=True)
        return _INVALID_LEASE
    except json.JSONDecodeError:
        logger.warning("Operator action lease evidence invalid JSON: %s", path, exc_info=True)
        return _INVALID_LEASE


def _parse_reclaimed_event_payload(
    *,
    payload: object,
    action_name: str | None,
) -> ReclaimedOperatorActionLeaseEvent | _InvalidLease | None:
    if not isinstance(payload, dict):
        return _INVALID_LEASE
    candidate_action_name = payload.get("action_name")
    if not _is_required_lease_string(candidate_action_name):
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
    if not _is_required_lease_string(operator_id):
        return _INVALID_LEASE
    if not _is_optional_lease_string(tenant_id):
        return _INVALID_LEASE
    if not _is_required_lease_string(governed_target):
        return _INVALID_LEASE
    if not _is_required_lease_string(acquired_at_utc):
        return _INVALID_LEASE
    if not _is_required_lease_string(reclaimed_at_utc):
        return _INVALID_LEASE
    if not isinstance(stale_after_seconds, (int, float)):
        return _INVALID_LEASE
    if not isinstance(reclaim_count, int):
        return _INVALID_LEASE
    if not _is_required_lease_string(action_key):
        return _INVALID_LEASE
    candidate_action_name_value = cast(str, candidate_action_name)
    operator_id_value = cast(str, operator_id)
    tenant_id_value = cast(str | None, tenant_id)
    governed_target_value = cast(str, governed_target)
    acquired_at_utc_value = cast(str, acquired_at_utc)
    reclaimed_at_utc_value = cast(str, reclaimed_at_utc)
    action_key_value = cast(str, action_key)
    try:
        _parse_utc(acquired_at_utc_value)
        _parse_utc(reclaimed_at_utc_value)
    except ValueError:
        return _INVALID_LEASE
    return ReclaimedOperatorActionLeaseEvent(
        action_key=action_key_value,
        action_name=candidate_action_name_value,
        operator_id=operator_id_value,
        tenant_id=tenant_id_value,
        governed_target=governed_target_value,
        acquired_at_utc=acquired_at_utc_value,
        reclaimed_at_utc=reclaimed_at_utc_value,
        stale_after_seconds=float(stale_after_seconds),
        reclaim_count=reclaim_count,
    )


def _parse_utc(timestamp_utc: str) -> datetime:
    return parse_utc_datetime(timestamp_utc)


def _reclaim_stale_lock(
    *,
    lock_path: Path,
    stale_after_seconds: float,
    action_key: str,
    now_utc: datetime | None,
) -> bool:
    if stale_after_seconds <= 0:
        return False
    active_lease = _read_active_operator_action_lease(lock_path=lock_path)
    if not isinstance(active_lease, ActiveOperatorActionLease):
        return False
    current_time = now_utc or datetime.now(UTC)
    acquired_at = _parse_utc(active_lease.acquired_at_utc)
    if (current_time - acquired_at).total_seconds() <= stale_after_seconds:
        return False
    lock_path.unlink(missing_ok=True)
    try:
        _write_latest_reclaimed_lease(
            locks_dir=lock_path.parent,
            event=ReclaimedOperatorActionLeaseEvent(
                action_key=action_key,
                action_name=active_lease.action_name,
                operator_id=active_lease.operator_id,
                tenant_id=active_lease.tenant_id,
                governed_target=active_lease.governed_target,
                acquired_at_utc=active_lease.acquired_at_utc,
                reclaimed_at_utc=current_time.isoformat().replace("+00:00", "Z"),
                stale_after_seconds=stale_after_seconds,
                reclaim_count=0,
            ),
        )
    except OSError:
        logger.warning(
            "operator_action_reclaim_evidence_write_failed",
            extra={"action_key": action_key, "action_name": active_lease.action_name},
            exc_info=True,
        )
    return True
