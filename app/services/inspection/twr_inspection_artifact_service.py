from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.artifact_filename_policy import validate_artifact_filename
from app.services.lineage_metadata_store import LineagePayload, LineageRecord, LineageStatus, lineage_metadata_store
from core.errors import APINotFoundError, APIServiceUnavailableError


@dataclass(frozen=True)
class TWRInspectionArtifactFileReference:
    path: str
    filename: str


@dataclass(frozen=True)
class RetainedTWRInspectionArtifact:
    content: str
    media_type: str
    filename: str


TWRInspectionArtifactReference = TWRInspectionArtifactFileReference | RetainedTWRInspectionArtifact


def inspection_storage_path(*, inspection_id: UUID, artifact_name: str | None = None) -> str:
    base_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(inspection_id))
    if artifact_name is None:
        return base_path
    safe_artifact_name = safe_inspection_artifact_name(artifact_name)
    if safe_artifact_name is None:
        raise ValueError(f"Unsafe TWR inspection artifact filename: {artifact_name}")
    return os.path.join(base_path, safe_artifact_name)


def safe_inspection_artifact_name(artifact_name: str) -> str | None:
    try:
        return validate_artifact_filename(artifact_name, artifact_kind="TWR inspection artifact")
    except ValueError:
        return None


def is_completed_twr_inspection_record(record: LineageRecord | None) -> bool:
    return (
        record is not None
        and record.calculation_type == ANALYTICS_WORKFLOW_TWR_INSPECTION
        and record.status == LineageStatus.COMPLETE
    )


def is_available_twr_inspection_artifact(record: LineageRecord | None, artifact_name: str) -> bool:
    if record is None:
        return False
    safe_artifact_name = safe_inspection_artifact_name(artifact_name)
    if safe_artifact_name is None:
        return False
    safe_record_artifact_names = {
        safe_name for candidate in record.artifact_names if (safe_name := safe_inspection_artifact_name(candidate))
    }
    return is_completed_twr_inspection_record(record) and safe_artifact_name in safe_record_artifact_names


def retained_inspection_artifact(
    *,
    payload: LineagePayload | None,
    artifact_name: str,
) -> RetainedTWRInspectionArtifact | None:
    safe_artifact_name = safe_inspection_artifact_name(artifact_name)
    if safe_artifact_name is None or payload is None or safe_artifact_name not in payload.details:
        return None
    media_type = "text/markdown" if safe_artifact_name.endswith(".md") else "application/json"
    return RetainedTWRInspectionArtifact(
        content=payload.details[safe_artifact_name],
        media_type=media_type,
        filename=safe_artifact_name,
    )


def resolve_twr_inspection_artifact(
    *,
    inspection_id: UUID,
    artifact_name: str,
) -> TWRInspectionArtifactReference:
    record = lineage_metadata_store.get_record(inspection_id)
    if not is_available_twr_inspection_artifact(record, artifact_name):
        raise APINotFoundError("Inspection artifact not found.")

    artifact_path = inspection_storage_path(inspection_id=inspection_id, artifact_name=artifact_name)
    if os.path.exists(artifact_path):
        return TWRInspectionArtifactFileReference(path=artifact_path, filename=artifact_name)

    retained_artifact = retained_inspection_artifact(
        payload=lineage_metadata_store.get_payload(inspection_id),
        artifact_name=artifact_name,
    )
    if retained_artifact is not None:
        return retained_artifact

    raise APIServiceUnavailableError("Inspection artifact is missing from storage.")
