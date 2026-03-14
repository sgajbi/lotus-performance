# app/api/endpoints/lineage.py
import json
import os
from typing import Dict, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.services.lineage_metadata_store import LineageStatus, lineage_metadata_store
from app.services.lineage_service import LineageService

router = APIRouter()


class ArtifactLink(BaseModel):
    url: str


class LineageResponse(BaseModel):
    calculation_id: UUID
    calculation_type: str
    timestamp_utc: str
    status: LineageStatus
    artifacts: Dict[str, ArtifactLink]
    error_message: Optional[str] = None


class LineageManifest(BaseModel):
    calculation_type: str
    timestamp_utc: str
    status: str
    artifact_names: list[str]


def _resolve_lineage_artifact_path(*, calculation_id: UUID, artifact_name: str) -> str:
    safe_artifact_name = LineageService._validate_artifact_filename(artifact_name)
    lineage_dir = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
    return os.path.join(lineage_dir, safe_artifact_name)


def _load_and_validate_manifest(*, manifest_path: str, record) -> LineageManifest:
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_payload = json.load(f)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lineage manifest is unreadable.",
        ) from None
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lineage manifest is invalid.",
        ) from None

    try:
        manifest = LineageManifest.model_validate(manifest_payload)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lineage manifest is invalid.",
        ) from None

    expected_artifact_names = sorted(record.artifact_names)
    if (
        manifest.calculation_type != record.calculation_type
        or manifest.timestamp_utc != record.timestamp_utc
        or manifest.status != record.status.value
        or sorted(manifest.artifact_names) != expected_artifact_names
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lineage manifest is inconsistent with durable metadata.",
        )

    return manifest


def _ensure_declared_artifacts_exist(*, calculation_id: UUID, artifact_names: list[str]) -> None:
    for artifact_name in artifact_names:
        if artifact_name == "manifest.json":
            continue
        artifact_path = _resolve_lineage_artifact_path(calculation_id=calculation_id, artifact_name=artifact_name)
        if not os.path.exists(artifact_path):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Lineage artifacts are incomplete in storage.",
            )


@router.get("/lineage/{calculation_id}", response_model=LineageResponse, summary="Retrieve Data Lineage Artifacts")
async def get_lineage_data(calculation_id: UUID, request: Request):
    """
    Retrieves the download URLs for all data lineage artifacts associated with a calculation_id.
    """
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lineage data not found for the given calculation_id."
        )

    artifacts = {}
    try:
        lineage_dir = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
        if record.status == LineageStatus.PENDING:
            return LineageResponse(
                calculation_id=calculation_id,
                calculation_type=record.calculation_type,
                timestamp_utc=record.timestamp_utc,
                status=record.status,
                artifacts={},
                error_message=None,
            )

        if record.status == LineageStatus.FAILED:
            return LineageResponse(
                calculation_id=calculation_id,
                calculation_type=record.calculation_type,
                timestamp_utc=record.timestamp_utc,
                status=record.status,
                artifacts={},
                error_message=record.error_message,
            )

        manifest_path = os.path.join(lineage_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lineage manifest not found.")

        manifest = _load_and_validate_manifest(manifest_path=manifest_path, record=record)
        _ensure_declared_artifacts_exist(calculation_id=calculation_id, artifact_names=record.artifact_names)

        for filename in record.artifact_names:
            if filename != "manifest.json":
                file_url = request.url_for(
                    "lineage_artifact_file",
                    calculation_id=str(calculation_id),
                    artifact_name=filename,
                )
                artifacts[filename] = ArtifactLink(url=str(file_url))

        return LineageResponse(
            calculation_id=calculation_id,
            calculation_type=manifest.calculation_type,
            timestamp_utc=manifest.timestamp_utc,
            status=record.status,
            artifacts=artifacts,
            error_message=record.error_message,
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retrieve lineage artifacts: {e}"
        )


@router.get(
    "/lineage/{calculation_id}/artifacts/{artifact_name}",
    name="lineage_artifact_file",
    include_in_schema=False,
)
async def get_lineage_artifact(calculation_id: UUID, artifact_name: str):
    record = lineage_metadata_store.get_record(calculation_id)
    if record is None or record.status != LineageStatus.COMPLETE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lineage artifact not found.")
    if artifact_name not in record.artifact_names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lineage artifact not found.")

    manifest_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id), "manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Lineage manifest not found.")
    _load_and_validate_manifest(manifest_path=manifest_path, record=record)

    artifact_path = _resolve_lineage_artifact_path(calculation_id=calculation_id, artifact_name=artifact_name)
    if not os.path.exists(artifact_path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lineage artifact is missing from storage.",
        )

    return FileResponse(path=artifact_path, filename=artifact_name)
