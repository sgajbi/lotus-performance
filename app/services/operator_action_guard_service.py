from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.services.recovery_drill_history_service import RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)


@dataclass(frozen=True)
class ManualActionCooldown:
    action_name: str
    detail_code: str
    latest_generated_at_utc: str
    latest_evidence_file_name: str
    retry_after_seconds: int


def enforce_runtime_retention_manual_run_cooldown(
    snapshot: RuntimeRetentionHistorySnapshot,
    *,
    apply: bool,
    operator_id: str,
    tenant_id: str | None,
    retention_days: int,
    job_id: str | None,
    cooldown_seconds: float,
    now_utc: datetime | None = None,
) -> None:
    latest_entry = _find_latest_runtime_retention_entry(
        snapshot,
        apply=apply,
        operator_id=operator_id,
        tenant_id=tenant_id,
        retention_days=retention_days,
        job_id=job_id,
    )
    _enforce_manual_action_cooldown(
        action_name="runtime_retention_cleanup",
        detail_code="runtime_retention_manual_run_cooldown_active",
        latest_generated_at_utc=latest_entry.generated_at_utc if latest_entry is not None else None,
        latest_evidence_file_name=latest_entry.evidence_file_name if latest_entry is not None else None,
        cooldown_seconds=cooldown_seconds,
        now_utc=now_utc,
    )


def enforce_runtime_retention_apply_preview(
    snapshot: RuntimeRetentionHistorySnapshot,
    *,
    operator_id: str,
    tenant_id: str | None,
    retention_days: int,
    job_id: str | None,
    preview_max_age_seconds: float,
    now_utc: datetime | None = None,
) -> None:
    if preview_max_age_seconds <= 0:
        return

    preview_entry = _find_latest_runtime_retention_entry(
        snapshot,
        apply=False,
        operator_id=operator_id,
        tenant_id=tenant_id,
        retention_days=retention_days,
        job_id=job_id,
    )
    if preview_entry is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "runtime_retention_apply_preview_required",
                "message": (
                    "A recent matching runtime-retention dry run is required before apply can execute."
                ),
                "required_cleanup_mode": "dry_run",
                "required_retention_days": retention_days,
            },
        )

    current_time = now_utc or datetime.now(UTC)
    elapsed_seconds = (current_time - _parse_utc_timestamp(preview_entry.generated_at_utc)).total_seconds()
    if elapsed_seconds <= preview_max_age_seconds:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "runtime_retention_apply_preview_required",
            "message": (
                "A recent matching runtime-retention dry run is required before apply can execute."
            ),
            "latest_preview_generated_at_utc": preview_entry.generated_at_utc,
            "latest_preview_evidence_file_name": preview_entry.evidence_file_name,
            "preview_max_age_seconds": int(preview_max_age_seconds),
        },
    )


def enforce_recovery_drill_manual_run_cooldown(
    snapshot: RecoveryDrillHistorySnapshot,
    *,
    cooldown_seconds: float,
    now_utc: datetime | None = None,
) -> None:
    _enforce_manual_action_cooldown(
        action_name="recovery_drill",
        detail_code="recovery_drill_manual_run_cooldown_active",
        latest_generated_at_utc=_resolve_latest_generated_at_utc(snapshot.entries),
        latest_evidence_file_name=_resolve_latest_evidence_file_name(snapshot.entries),
        cooldown_seconds=cooldown_seconds,
        now_utc=now_utc,
    )


def _resolve_latest_generated_at_utc(entries: list[object]) -> str | None:
    if not entries:
        return None
    value = getattr(entries[0], "generated_at_utc", None)
    return value if isinstance(value, str) else None


def _resolve_latest_evidence_file_name(entries: list[object]) -> str | None:
    if not entries:
        return None
    value = getattr(entries[0], "evidence_file_name", None)
    return value if isinstance(value, str) else None


def _find_latest_runtime_retention_entry(
    snapshot: RuntimeRetentionHistorySnapshot,
    *,
    apply: bool,
    operator_id: str,
    tenant_id: str | None,
    retention_days: int,
    job_id: str | None,
) -> RuntimeRetentionHistoryEntry | None:
    expected_cleanup_mode = "apply" if apply else "dry_run"
    for entry in snapshot.entries:
        if entry.operator_id != operator_id:
            continue
        if entry.tenant_id != tenant_id:
            continue
        if entry.cleanup_mode != expected_cleanup_mode:
            continue
        if entry.retention_days != retention_days:
            continue
        if entry.job_id != job_id:
            continue
        return entry
    return None


def _enforce_manual_action_cooldown(
    *,
    action_name: str,
    detail_code: str,
    latest_generated_at_utc: str | None,
    latest_evidence_file_name: str | None,
    cooldown_seconds: float,
    now_utc: datetime | None,
) -> None:
    if cooldown_seconds <= 0 or latest_generated_at_utc is None or latest_evidence_file_name is None:
        return

    latest_generated_at = _parse_utc_timestamp(latest_generated_at_utc)
    current_time = now_utc or datetime.now(UTC)
    elapsed_seconds = (current_time - latest_generated_at).total_seconds()
    retry_after_seconds = math.ceil(cooldown_seconds - elapsed_seconds)
    if retry_after_seconds <= 0:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": detail_code,
            "message": (
                f"A recent manual {action_name} already completed inside the governed cooldown window. "
                "Wait for the cooldown to expire before retrying."
            ),
            "latest_generated_at_utc": latest_generated_at_utc,
            "latest_evidence_file_name": latest_evidence_file_name,
            "retry_after_seconds": retry_after_seconds,
        },
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
