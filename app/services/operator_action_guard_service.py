from __future__ import annotations

import math
from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.services.durable_store_time import elapsed_seconds_since
from app.services.operator_action_identity import (
    operator_action_actor_matches,
    operator_action_optional_identity_matches,
    operator_action_required_identity_matches,
)
from app.services.recovery_drill_history_service import (
    RecoveryDrillHistoryEntry,
    RecoveryDrillHistorySnapshot,
)
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)
from app.services.runtime_status_time import parse_utc_datetime


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
                "message": ("A recent matching runtime-retention dry run is required before apply can execute."),
                "required_cleanup_mode": "dry_run",
                "required_retention_days": retention_days,
            },
        )

    current_time = now_utc or datetime.now(UTC)
    elapsed_seconds = elapsed_seconds_since(current_time, parse_utc_datetime(preview_entry.generated_at_utc))
    if elapsed_seconds <= preview_max_age_seconds:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "runtime_retention_apply_preview_required",
            "message": ("A recent matching runtime-retention dry run is required before apply can execute."),
            "latest_preview_generated_at_utc": preview_entry.generated_at_utc,
            "latest_preview_evidence_file_name": preview_entry.evidence_file_name,
            "preview_max_age_seconds": int(preview_max_age_seconds),
        },
    )


def enforce_recovery_drill_manual_run_cooldown(
    snapshot: RecoveryDrillHistorySnapshot,
    *,
    operator_id: str,
    tenant_id: str | None,
    backup_identifier: str,
    cooldown_seconds: float,
    now_utc: datetime | None = None,
) -> None:
    latest_entry = _find_latest_recovery_drill_entry(
        snapshot,
        operator_id=operator_id,
        tenant_id=tenant_id,
        backup_identifier=backup_identifier,
    )
    _enforce_manual_action_cooldown(
        action_name="recovery_drill",
        detail_code="recovery_drill_manual_run_cooldown_active",
        latest_generated_at_utc=latest_entry.generated_at_utc if latest_entry is not None else None,
        latest_evidence_file_name=latest_entry.evidence_file_name if latest_entry is not None else None,
        cooldown_seconds=cooldown_seconds,
        now_utc=now_utc,
    )


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
        if not operator_action_actor_matches(entry, operator_id=operator_id, tenant_id=tenant_id):
            continue
        if entry.cleanup_mode != expected_cleanup_mode:
            continue
        if entry.retention_days != retention_days:
            continue
        if not operator_action_optional_identity_matches(entry.job_id, job_id):
            continue
        return entry
    return None


def _find_latest_recovery_drill_entry(
    snapshot: RecoveryDrillHistorySnapshot,
    *,
    operator_id: str,
    tenant_id: str | None,
    backup_identifier: str,
) -> RecoveryDrillHistoryEntry | None:
    for entry in snapshot.entries:
        if not operator_action_actor_matches(entry, operator_id=operator_id, tenant_id=tenant_id):
            continue
        if not operator_action_required_identity_matches(entry.backup_identifier, backup_identifier):
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

    current_time = now_utc or datetime.now(UTC)
    elapsed_seconds = elapsed_seconds_since(current_time, parse_utc_datetime(latest_generated_at_utc))
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
