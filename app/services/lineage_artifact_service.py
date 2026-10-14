from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Any, Callable
from uuid import UUID

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.lineage_responses import ArtifactLink, LineageArtifactMetadata, LineageManifest, LineageResponse
from app.observability import tenant_id_var
from app.services.artifact_filename_policy import validate_artifact_filename
from app.services.durable_store_json import read_json_file
from app.services.execution_registry import execution_registry
from app.services.lineage_artifact_classification import lineage_artifact_metadata_by_name
from app.services.lineage_metadata_store import LineageRecord, LineageStatus, lineage_metadata_store
from core.errors import APINotFoundError, APIServiceUnavailableError


@dataclass(frozen=True)
class LineageArtifactFileReference:
    path: str
    filename: str
    metadata: LineageArtifactMetadata


def lineage_artifact_path(*, calculation_id: UUID, artifact_name: str) -> str:
    safe_artifact_name = validate_artifact_filename(artifact_name, artifact_kind="lineage artifact")
    lineage_dir = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
    return os.path.join(lineage_dir, safe_artifact_name)


def read_lineage_manifest_payload(manifest_path: str) -> Any:
    try:
        return read_json_file(FilePath(manifest_path))
    except OSError:
        raise APIServiceUnavailableError("Lineage manifest is unreadable.") from None
    except json.JSONDecodeError:
        raise APIServiceUnavailableError("Lineage manifest is invalid.") from None


def load_and_validate_manifest(*, manifest_path: str, record: LineageRecord) -> LineageManifest:
    if record.source_custody_state is not None:
        from app.services.returns_series_source.capture import source_directory
        from app.services.returns_series_source.materialization import verify_source_manifest

        _require_retained_source_authority(record)
        try:
            directory = source_directory(get_settings().LINEAGE_STORAGE_PATH, str(record.calculation_id), create=False)
            manifest_payload = verify_source_manifest(directory, record=record)
        except (OSError, ValueError, KeyError, TypeError):
            raise APIServiceUnavailableError("Retained source integrity verification failed.") from None
    else:
        manifest_payload = read_lineage_manifest_payload(manifest_path)
    manifest_payload = _backfill_legacy_manifest_artifact_metadata(manifest_payload)

    try:
        manifest = LineageManifest.model_validate(manifest_payload)
    except ValidationError:
        raise APIServiceUnavailableError("Lineage manifest is invalid.") from None

    if not manifest_matches_record(manifest=manifest, record=record):
        raise APIServiceUnavailableError("Lineage manifest is inconsistent with durable metadata.")

    return manifest


def _require_retained_source_authority(record: LineageRecord) -> None:
    if record.source_custody_state is None:
        return
    execution = execution_registry.get_execution(record.calculation_id)
    if (
        execution is None
        or execution.tenant_id != record.source_tenant_id
        or tenant_id_var.get() != record.source_tenant_id
        or execution.analytics_type != "ReturnsSeries"
    ):
        raise APINotFoundError("Retained source authority not found.")


def _manifest_path(calculation_id: UUID, record: LineageRecord) -> str:
    name = (
        f"source-{record.source_manifest_digest}.manifest.json"
        if record.source_custody_state is not None
        else "manifest.json"
    )
    return lineage_artifact_path(calculation_id=calculation_id, artifact_name=name)


def _backfill_legacy_manifest_artifact_metadata(manifest_payload: Any) -> Any:
    if not isinstance(manifest_payload, dict) or "artifacts" in manifest_payload:
        return manifest_payload
    artifact_names = manifest_payload.get("artifact_names")
    if not isinstance(artifact_names, list) or not all(isinstance(name, str) for name in artifact_names):
        return manifest_payload
    return {
        **manifest_payload,
        "artifacts": lineage_artifact_metadata_by_name(artifact_names=artifact_names),
    }


def manifest_matches_record(*, manifest: LineageManifest, record: LineageRecord) -> bool:
    return (
        manifest.calculation_type == record.calculation_type
        and manifest.timestamp_utc == record.timestamp_utc
        and manifest.status == record.status.value
        and sorted(manifest.artifact_names) == sorted(record.artifact_names)
    )


def ensure_declared_lineage_artifacts_exist(*, calculation_id: UUID, artifact_names: list[str]) -> None:
    for artifact_name in artifact_names:
        if artifact_name == "manifest.json":
            continue
        artifact_path = lineage_artifact_path(calculation_id=calculation_id, artifact_name=artifact_name)
        if not os.path.exists(artifact_path):
            raise APIServiceUnavailableError("Lineage artifacts are incomplete in storage.")


def lineage_terminal_response(*, calculation_id: UUID, record: LineageRecord) -> LineageResponse | None:
    if record.status not in {LineageStatus.PENDING, LineageStatus.FAILED}:
        return None
    return LineageResponse(
        calculation_id=calculation_id,
        source_custody_state=record.source_custody_state,
        calculation_type=record.calculation_type,
        timestamp_utc=record.timestamp_utc,
        status=record.status,
        artifacts={},
        error_message=record.error_message if record.status == LineageStatus.FAILED else None,
    )


def resolve_lineage_response(
    *,
    calculation_id: UUID,
    artifact_url_factory: Callable[[str], str],
    include_operator_artifacts: bool = True,
) -> LineageResponse:
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None:
        raise APINotFoundError("Lineage data not found for the given calculation_id.")
    _require_retained_source_authority(record)

    terminal_response = lineage_terminal_response(calculation_id=calculation_id, record=record)
    if terminal_response is not None:
        return terminal_response

    manifest_path = _manifest_path(calculation_id, record)
    if not os.path.exists(manifest_path):
        raise APINotFoundError("Lineage manifest not found.")

    manifest = load_and_validate_manifest(manifest_path=manifest_path, record=record)
    ensure_declared_lineage_artifacts_exist(calculation_id=calculation_id, artifact_names=record.artifact_names)
    return completed_lineage_response(
        calculation_id=calculation_id,
        record=record,
        manifest=manifest,
        artifact_url_factory=artifact_url_factory,
        include_operator_artifacts=include_operator_artifacts,
    )


def completed_lineage_response(
    *,
    calculation_id: UUID,
    record: LineageRecord,
    manifest: LineageManifest,
    artifact_url_factory: Callable[[str], str],
    include_operator_artifacts: bool = True,
) -> LineageResponse:
    return LineageResponse(
        calculation_id=calculation_id,
        source_custody_state=record.source_custody_state,
        calculation_type=manifest.calculation_type,
        timestamp_utc=manifest.timestamp_utc,
        status=record.status,
        artifacts=lineage_artifact_links(
            artifact_names=record.artifact_names,
            artifact_metadata=manifest.artifacts,
            artifact_url_factory=artifact_url_factory,
            include_operator_artifacts=include_operator_artifacts,
        ),
        error_message=record.error_message,
    )


def effective_lineage_artifact_metadata(*, filename: str, metadata: LineageArtifactMetadata) -> LineageArtifactMetadata:
    """Apply filename-owned field floors without weakening stricter manifest labels."""
    canonical = lineage_artifact_metadata_by_name(artifact_names=[filename])[filename]
    if canonical.access_classification == "customer_consumable":
        return metadata
    return metadata.model_copy(
        update={
            "access_classification": "operator_only",
            "intended_audience": "operations",
            "sensitivity": (
                "raw_sensitive_payload"
                if "raw_sensitive_payload" in (canonical.sensitivity, metadata.sensitivity)
                else "derived_evidence"
            ),
            "minimization_posture": (
                "raw_payload_full_fidelity"
                if "raw_payload_full_fidelity" in (canonical.minimization_posture, metadata.minimization_posture)
                else "derived_detail_minimized"
            ),
            "retention_category": (
                "lineage_raw_payload"
                if "lineage_raw_payload" in (canonical.retention_category, metadata.retention_category)
                else "lineage_detail_evidence"
            ),
            "redaction_required_before_external_sharing": True,
        }
    )


def lineage_artifact_links(
    *,
    artifact_names: list[str],
    artifact_metadata: dict[str, LineageArtifactMetadata],
    artifact_url_factory: Callable[[str], str],
    include_operator_artifacts: bool = True,
) -> dict[str, ArtifactLink]:
    artifacts: dict[str, ArtifactLink] = {}
    for filename in artifact_names:
        if filename == "manifest.json":
            continue
        metadata = effective_lineage_artifact_metadata(filename=filename, metadata=artifact_metadata[filename])
        if not include_operator_artifacts and metadata.access_classification == "operator_only":
            continue
        artifacts[filename] = ArtifactLink(
            url=artifact_url_factory(filename),
            **metadata.model_dump(mode="json"),
        )
    return artifacts


def downloadable_lineage_record(*, calculation_id: UUID, artifact_name: str) -> LineageRecord:
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None or record.status != LineageStatus.COMPLETE or artifact_name not in record.artifact_names:
        raise APINotFoundError("Lineage artifact not found.")
    _require_retained_source_authority(record)
    return record


def resolve_lineage_artifact_file(*, calculation_id: UUID, artifact_name: str) -> LineageArtifactFileReference:
    record = downloadable_lineage_record(calculation_id=calculation_id, artifact_name=artifact_name)

    manifest_path = _manifest_path(calculation_id, record)
    if not os.path.exists(manifest_path):
        raise APIServiceUnavailableError("Lineage manifest not found.")
    manifest = load_and_validate_manifest(manifest_path=manifest_path, record=record)
    metadata = effective_lineage_artifact_metadata(filename=artifact_name, metadata=manifest.artifacts[artifact_name])

    artifact_path = lineage_artifact_path(calculation_id=calculation_id, artifact_name=artifact_name)
    if not os.path.exists(artifact_path):
        raise APIServiceUnavailableError("Lineage artifact is missing from storage.")

    return LineageArtifactFileReference(path=artifact_path, filename=artifact_name, metadata=metadata)
