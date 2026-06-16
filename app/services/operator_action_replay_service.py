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

_RUNTIME_RETENTION_REQUIRED_STRING_FIELDS = (
    "cleanup_name",
    "generated_at_utc",
    "evidence_file_name",
    "operator_id",
    "trigger_mode",
    "cleanup_mode",
    "status",
    "cutoff_utc",
)
_RUNTIME_RETENTION_OPTIONAL_STRING_FIELDS = ("tenant_id", "correlation_id", "job_id")
_RUNTIME_RETENTION_REQUIRED_IDENTITY_FIELDS = (
    "evidence_file_name",
    "generated_at_utc",
    "operator_id",
    "trigger_mode",
    "cleanup_mode",
    "status",
)
_RUNTIME_RETENTION_OPTIONAL_IDENTITY_FIELDS = ("tenant_id", "correlation_id", "job_id")
_RUNTIME_RETENTION_REQUIRED_INT_FIELDS = (
    "retention_days",
    "prunable_execution_count",
    "prunable_compute_job_count",
    "prunable_async_result_count",
    "prunable_lineage_record_count",
    "prunable_lineage_artifact_count",
)
_RECOVERY_DRILL_REQUIRED_STRING_FIELDS = (
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
)
_RECOVERY_DRILL_OPTIONAL_STRING_FIELDS = ("tenant_id", "correlation_id")
_RECOVERY_DRILL_REQUIRED_INT_FIELDS = ("compute_job_processed_count", "processed_payload_count")
_RECOVERY_DRILL_REQUIRED_BOOL_FIELDS = ("materialized_artifact_exists",)
_RECOVERY_DRILL_REQUIRED_IDENTITY_FIELDS = (
    "evidence_file_name",
    "generated_at_utc",
    "operator_id",
    "backup_identifier",
    "status",
)
_RECOVERY_DRILL_OPTIONAL_IDENTITY_FIELDS = ("tenant_id", "correlation_id")


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
        return _runtime_retention_replay_from_entry(entry, artifact_directory=artifact_directory)
    return None


def _runtime_retention_replay_from_entry(
    entry: RuntimeRetentionHistoryEntry,
    *,
    artifact_directory: Path,
) -> ActionReplayResult | None:
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
        if not _recovery_drill_entry_matches(
            entry,
            operator_id=operator_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            backup_identifier=backup_identifier,
        ):
            continue
        return _recovery_drill_replay_from_entry(entry, artifact_directory=artifact_directory)
    return None


def _recovery_drill_replay_from_entry(
    entry: RecoveryDrillHistoryEntry,
    *,
    artifact_directory: Path,
) -> ActionReplayResult | None:
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


def _recovery_drill_entry_matches(
    entry: RecoveryDrillHistoryEntry,
    *,
    operator_id: str,
    tenant_id: str | None,
    correlation_id: str,
    backup_identifier: str,
) -> bool:
    return operator_action_correlation_matches(
        entry,
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
    ) and operator_action_required_identity_matches(entry.backup_identifier, backup_identifier)


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
    if not operator_action_correlation_matches(
        entry,
        operator_id=operator_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
    ):
        return False
    return _runtime_retention_request_filters_match(
        entry,
        apply=apply,
        retention_days=retention_days,
        job_id=job_id,
    )


def _runtime_retention_request_filters_match(
    entry: RuntimeRetentionHistoryEntry,
    *,
    apply: bool,
    retention_days: int | None,
    job_id: str | None,
) -> bool:
    expected_cleanup_mode = "apply" if apply else "dry_run"
    if entry.cleanup_mode != expected_cleanup_mode:
        return False
    if retention_days is not None and entry.retention_days != retention_days:
        return False
    return operator_action_optional_identity_matches(entry.job_id, job_id)


def _runtime_retention_payload_matches_entry(
    payload: dict[str, Any],
    entry: RuntimeRetentionHistoryEntry,
) -> bool:
    return (
        _runtime_retention_payload_has_required_shape(payload)
        and _runtime_retention_payload_identity_matches(payload, entry)
        and _runtime_retention_payload_counts_match(payload, entry)
    )


def _runtime_retention_payload_has_required_shape(payload: dict[str, Any]) -> bool:
    return (
        required_evidence_string_fields_present(payload, _RUNTIME_RETENTION_REQUIRED_STRING_FIELDS)
        and optional_evidence_string_fields_valid(payload, _RUNTIME_RETENTION_OPTIONAL_STRING_FIELDS)
        and required_evidence_int_fields_present(payload, _RUNTIME_RETENTION_REQUIRED_INT_FIELDS)
    )


def _runtime_retention_payload_identity_matches(
    payload: dict[str, Any],
    entry: RuntimeRetentionHistoryEntry,
) -> bool:
    return _payload_entry_required_fields_match(
        payload,
        entry,
        field_names=_RUNTIME_RETENTION_REQUIRED_IDENTITY_FIELDS,
    ) and _payload_entry_optional_fields_match(
        payload,
        entry,
        field_names=_RUNTIME_RETENTION_OPTIONAL_IDENTITY_FIELDS,
    )


def _payload_entry_required_fields_match(
    payload: dict[str, Any],
    entry: object,
    *,
    field_names: tuple[str, ...],
) -> bool:
    return all(payload[field_name] == getattr(entry, field_name) for field_name in field_names)


def _payload_entry_optional_fields_match(
    payload: dict[str, Any],
    entry: object,
    *,
    field_names: tuple[str, ...],
) -> bool:
    return all(payload.get(field_name) == getattr(entry, field_name) for field_name in field_names)


def _runtime_retention_payload_counts_match(
    payload: dict[str, Any],
    entry: RuntimeRetentionHistoryEntry,
) -> bool:
    return (
        payload["retention_days"] == entry.retention_days
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
    return _recovery_drill_payload_has_required_shape(payload) and _recovery_drill_payload_identity_matches(
        payload, entry
    )


def _recovery_drill_payload_has_required_shape(payload: dict[str, Any]) -> bool:
    return (
        required_evidence_string_fields_present(payload, _RECOVERY_DRILL_REQUIRED_STRING_FIELDS)
        and optional_evidence_string_fields_valid(payload, _RECOVERY_DRILL_OPTIONAL_STRING_FIELDS)
        and required_evidence_int_fields_present(payload, _RECOVERY_DRILL_REQUIRED_INT_FIELDS)
        and is_required_evidence_string_list(payload.get("owned_tables_present"))
        and required_evidence_bool_fields_present(payload, _RECOVERY_DRILL_REQUIRED_BOOL_FIELDS)
    )


def _recovery_drill_payload_identity_matches(
    payload: dict[str, Any],
    entry: RecoveryDrillHistoryEntry,
) -> bool:
    return _payload_entry_required_fields_match(
        payload,
        entry,
        field_names=_RECOVERY_DRILL_REQUIRED_IDENTITY_FIELDS,
    ) and _payload_entry_optional_fields_match(
        payload,
        entry,
        field_names=_RECOVERY_DRILL_OPTIONAL_IDENTITY_FIELDS,
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
