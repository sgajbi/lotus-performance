from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.durable_store_json import read_json_object_file
from app.services.operator_action_evidence_paths import resolve_evidence_file_path
from app.services.operator_action_evidence_strings import (
    is_required_evidence_string_list,
    optional_evidence_string_fields_valid,
    required_evidence_bool_fields_present,
    required_evidence_int_fields_present,
    required_evidence_string_fields_present,
)
from app.services.operator_action_identity import (
    operator_action_correlation_matches,
    operator_action_optional_identity_matches,
    operator_action_required_identity_matches,
)
from app.services.recovery_drill_history_service import RecoveryDrillHistoryEntry, RecoveryDrillHistorySnapshot
from app.services.runtime_retention_history_service import (
    RuntimeRetentionHistoryEntry,
    RuntimeRetentionHistorySnapshot,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionReplayResult:
    payload: dict[str, Any]
    evidence_file_name: str


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
        if not _runtime_retention_payload_matches_entry(payload, entry):
            logger.warning(
                "Operator action replay evidence ignored because payload does not match runtime retention history entry: %s",
                entry.evidence_file_name,
            )
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
        if not operator_action_correlation_matches(
            entry,
            operator_id=operator_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        ):
            continue
        if not operator_action_required_identity_matches(entry.backup_identifier, backup_identifier):
            continue
        payload = _load_payload(artifact_directory=artifact_directory, evidence_file_name=entry.evidence_file_name)
        if payload is None:
            return None
        if not _recovery_drill_payload_matches_entry(payload, entry):
            logger.warning(
                "Operator action replay evidence ignored because payload does not match recovery drill history entry: %s",
                entry.evidence_file_name,
            )
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
    if not operator_action_correlation_matches(
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
    if not operator_action_optional_identity_matches(entry.job_id, job_id):
        return False
    return True


def _runtime_retention_payload_matches_entry(
    payload: dict[str, Any],
    entry: RuntimeRetentionHistoryEntry,
) -> bool:
    return (
        required_evidence_string_fields_present(
            payload,
            (
                "cleanup_name",
                "generated_at_utc",
                "evidence_file_name",
                "operator_id",
                "trigger_mode",
                "cleanup_mode",
                "status",
                "cutoff_utc",
            ),
        )
        and optional_evidence_string_fields_valid(payload, ("tenant_id", "correlation_id", "job_id"))
        and required_evidence_int_fields_present(
            payload,
            (
                "retention_days",
                "prunable_execution_count",
                "prunable_compute_job_count",
                "prunable_async_result_count",
                "prunable_lineage_record_count",
                "prunable_lineage_artifact_count",
            ),
        )
        and payload["evidence_file_name"] == entry.evidence_file_name
        and payload["generated_at_utc"] == entry.generated_at_utc
        and payload["operator_id"] == entry.operator_id
        and payload.get("tenant_id") == entry.tenant_id
        and payload.get("correlation_id") == entry.correlation_id
        and payload["trigger_mode"] == entry.trigger_mode
        and payload.get("job_id") == entry.job_id
        and payload["cleanup_mode"] == entry.cleanup_mode
        and payload["status"] == entry.status
        and payload["retention_days"] == entry.retention_days
        and payload["prunable_execution_count"] == entry.prunable_execution_count
        and payload["prunable_compute_job_count"] == entry.prunable_compute_job_count
        and payload["prunable_async_result_count"] == entry.prunable_async_result_count
        and payload["prunable_lineage_record_count"] == entry.prunable_lineage_record_count
        and payload["prunable_lineage_artifact_count"] == entry.prunable_lineage_artifact_count
    )


def _recovery_drill_payload_matches_entry(
    payload: dict[str, Any],
    entry: RecoveryDrillHistoryEntry,
) -> bool:
    return (
        required_evidence_string_fields_present(
            payload,
            (
                "drill_name",
                "generated_at_utc",
                "evidence_file_name",
                "operator_id",
                "backup_identifier",
                "status",
                "database_path",
                "restored_schema_mode",
                "compute_async_result_status",
                "compute_execution_status",
                "materialized_artifact_path",
            ),
        )
        and optional_evidence_string_fields_valid(payload, ("tenant_id", "correlation_id"))
        and required_evidence_int_fields_present(payload, ("compute_job_processed_count", "processed_payload_count"))
        and is_required_evidence_string_list(payload.get("owned_tables_present"))
        and required_evidence_bool_fields_present(payload, ("materialized_artifact_exists",))
        and payload["evidence_file_name"] == entry.evidence_file_name
        and payload["generated_at_utc"] == entry.generated_at_utc
        and payload["operator_id"] == entry.operator_id
        and payload.get("tenant_id") == entry.tenant_id
        and payload.get("correlation_id") == entry.correlation_id
        and payload["backup_identifier"] == entry.backup_identifier
        and payload["status"] == entry.status
    )


def _load_payload(*, artifact_directory: Path, evidence_file_name: str) -> dict[str, Any] | None:
    path = _evidence_file_path(artifact_directory=artifact_directory, evidence_file_name=evidence_file_name)
    if path is None:
        return None
    try:
        return read_json_object_file(
            path,
            object_error_message="operator action replay evidence payload must be an object",
        )
    except OSError:
        logger.warning("Operator action replay evidence unreadable: %s", evidence_file_name, exc_info=True)
        return None
    except json.JSONDecodeError:
        logger.warning("Operator action replay evidence invalid JSON: %s", evidence_file_name, exc_info=True)
        return None
    except TypeError:
        logger.warning(
            "Operator action replay evidence ignored because payload is not an object: %s", evidence_file_name
        )
        return None


def _evidence_file_path(*, artifact_directory: Path, evidence_file_name: str) -> Path | None:
    evidence_path = resolve_evidence_file_path(
        artifact_directory=artifact_directory, evidence_file_name=evidence_file_name
    )
    if evidence_path is None:
        logger.warning("Skipping evidence file outside operator action artifact directory: %s", evidence_file_name)
        return None
    return evidence_path
