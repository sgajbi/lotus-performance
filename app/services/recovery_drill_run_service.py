from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.models.recovery_drill_history import RecoveryDrillRunResponse, build_recovery_drill_run_response
from app.services.operator_action_guard_service import enforce_recovery_drill_manual_run_cooldown
from app.services.operator_action_lease_service import (
    OperatorActionLeaseMetadata,
    build_recovery_drill_action_key,
    operator_action_lease,
)
from app.services.operator_action_replay_service import resolve_recovery_drill_manual_replay
from app.services.operator_request_context import OperatorRequestContext
from app.services.operator_run_response_projection import build_operator_run_response_from_evidence
from app.services.recovery_drill_history_service import build_recovery_drill_history_snapshot
from scripts.durable_recovery_drill import RecoveryDrillEvidence
from scripts.durable_recovery_drill import run_recovery_drill as execute_recovery_drill

RecoveryDrillExecutor = Callable[..., RecoveryDrillEvidence]


@dataclass(frozen=True)
class RecoveryDrillRunResult:
    """Service result for recovery-drill execution and replay projection."""

    response: RecoveryDrillRunResponse
    idempotent_replay: bool


def run_governed_recovery_drill(
    *,
    operator_context: OperatorRequestContext,
    backup_identifier: str,
    settings: Settings | None = None,
    drill_executor: RecoveryDrillExecutor | None = None,
    acquired_at_utc: datetime | None = None,
) -> RecoveryDrillRunResult:
    """Run or replay a governed recovery drill under cooldown and lease controls."""

    active_settings = settings or get_settings()
    history_snapshot = build_recovery_drill_history_snapshot(limit=10)
    replay = resolve_recovery_drill_manual_replay(
        history_snapshot,
        artifact_directory=active_settings.RECOVERY_DRILL_ARTIFACT_PATH,
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        correlation_id=operator_context.correlation_id,
        backup_identifier=backup_identifier,
    )
    if replay is not None:
        return RecoveryDrillRunResult(
            response=build_recovery_drill_run_response(**replay.payload),
            idempotent_replay=True,
        )

    enforce_recovery_drill_manual_run_cooldown(
        history_snapshot,
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        backup_identifier=backup_identifier,
        cooldown_seconds=active_settings.RECOVERY_DRILL_MANUAL_RUN_COOLDOWN_SECONDS,
    )
    evidence = _run_recovery_drill_under_operator_lease(
        artifact_directory=active_settings.RECOVERY_DRILL_ARTIFACT_PATH,
        operator_context=operator_context,
        backup_identifier=backup_identifier,
        stale_after_seconds=active_settings.RECOVERY_DRILL_ACTION_LEASE_STALE_SECONDS,
        drill_executor=drill_executor or execute_recovery_drill,
        acquired_at_utc=acquired_at_utc or datetime.now(UTC),
    )
    return RecoveryDrillRunResult(
        response=_recovery_drill_response_from_evidence(evidence),
        idempotent_replay=False,
    )


def _run_recovery_drill_under_operator_lease(
    *,
    artifact_directory: Path,
    operator_context: OperatorRequestContext,
    backup_identifier: str,
    stale_after_seconds: float,
    drill_executor: RecoveryDrillExecutor,
    acquired_at_utc: datetime,
) -> RecoveryDrillEvidence:
    action_key = build_recovery_drill_action_key(
        operator_id=operator_context.operator_id,
        tenant_id=operator_context.tenant_id,
        backup_identifier=backup_identifier,
    )
    with operator_action_lease(
        artifact_directory=artifact_directory,
        action_key=action_key,
        metadata=OperatorActionLeaseMetadata(
            action_name="recovery_drill",
            operator_id=operator_context.operator_id,
            tenant_id=operator_context.tenant_id,
            governed_target=backup_identifier,
            acquired_at_utc=acquired_at_utc.isoformat(),
        ),
        stale_after_seconds=stale_after_seconds,
    ):
        return drill_executor(
            output_dir=artifact_directory,
            operator_id=operator_context.operator_id,
            tenant_id=operator_context.tenant_id,
            correlation_id=operator_context.correlation_id,
            backup_identifier=backup_identifier,
        )


def _recovery_drill_response_from_evidence(evidence: RecoveryDrillEvidence) -> RecoveryDrillRunResponse:
    return build_operator_run_response_from_evidence(
        build_recovery_drill_run_response,
        evidence,
    )
