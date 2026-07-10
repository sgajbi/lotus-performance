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
from app.services.artifact_filename_policy import validate_artifact_filename
from app.services.durable_store_json import read_json_file
from app.services.lineage_artifact_classification import lineage_artifact_metadata_by_name
from app.services.lineage_metadata_store import LineageRecord, LineageStatus, lineage_metadata_store
from core.errors import APINotFoundError, APIServiceUnavailableError


@dataclass(frozen=True)
class LineageArtifactFileReference:
    path: str
    filename: str


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
    manifest_payload = read_lineage_manifest_payload(manifest_path)
    manifest_payload = _backfill_legacy_manifest_artifact_metadata(manifest_payload)

    try:
        manifest = LineageManifest.model_validate(manifest_payload)
    except ValidationError:
        raise APIServiceUnavailableError("Lineage manifest is invalid.") from None

    if not manifest_matches_record(manifest=manifest, record=record):
        raise APIServiceUnavailableError("Lineage manifest is inconsistent with durable metadata.")

    return manifest


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
) -> LineageResponse:
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None:
        raise APINotFoundError("Lineage data not found for the given calculation_id.")

    terminal_response = lineage_terminal_response(calculation_id=calculation_id, record=record)
    if terminal_response is not None:
        return terminal_response

    manifest_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id), "manifest.json")
    if not os.path.exists(manifest_path):
        raise APINotFoundError("Lineage manifest not found.")

    manifest = load_and_validate_manifest(manifest_path=manifest_path, record=record)
    ensure_declared_lineage_artifacts_exist(calculation_id=calculation_id, artifact_names=record.artifact_names)
    return completed_lineage_response(
        calculation_id=calculation_id,
        record=record,
        manifest=manifest,
        artifact_url_factory=artifact_url_factory,
    )


def completed_lineage_response(
    *,
    calculation_id: UUID,
    record: LineageRecord,
    manifest: LineageManifest,
    artifact_url_factory: Callable[[str], str],
) -> LineageResponse:
    return LineageResponse(
        calculation_id=calculation_id,
        calculation_type=manifest.calculation_type,
        timestamp_utc=manifest.timestamp_utc,
        status=record.status,
        artifacts=lineage_artifact_links(
            artifact_names=record.artifact_names,
            artifact_metadata=manifest.artifacts,
            artifact_url_factory=artifact_url_factory,
        ),
        error_message=record.error_message,
    )


def lineage_artifact_links(
    *,
    artifact_names: list[str],
    artifact_metadata: dict[str, LineageArtifactMetadata],
    artifact_url_factory: Callable[[str], str],
) -> dict[str, ArtifactLink]:
    artifacts: dict[str, ArtifactLink] = {}
    for filename in artifact_names:
        if filename == "manifest.json":
            continue
        metadata = artifact_metadata[filename]
        artifacts[filename] = ArtifactLink(
            url=artifact_url_factory(filename),
            **metadata.model_dump(mode="json"),
        )
    return artifacts


def downloadable_lineage_record(*, calculation_id: UUID, artifact_name: str) -> LineageRecord:
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None or record.status != LineageStatus.COMPLETE or artifact_name not in record.artifact_names:
        raise APINotFoundError("Lineage artifact not found.")
    return record


def resolve_lineage_artifact_file(*, calculation_id: UUID, artifact_name: str) -> LineageArtifactFileReference:
    record = downloadable_lineage_record(calculation_id=calculation_id, artifact_name=artifact_name)

    manifest_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id), "manifest.json")
    if not os.path.exists(manifest_path):
        raise APIServiceUnavailableError("Lineage manifest not found.")
    load_and_validate_manifest(manifest_path=manifest_path, record=record)

    artifact_path = lineage_artifact_path(calculation_id=calculation_id, artifact_name=artifact_name)
    if not os.path.exists(artifact_path):
        raise APIServiceUnavailableError("Lineage artifact is missing from storage.")

    return LineageArtifactFileReference(path=artifact_path, filename=artifact_name)
