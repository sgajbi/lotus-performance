# app/api/endpoints/lineage.py
import json
import os
from pathlib import Path as FilePath
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.core.config import get_settings
from app.models.lineage_responses import ArtifactLink, LineageManifest, LineageResponse
from app.services.durable_store_json import read_json_file
from app.services.lineage_metadata_store import LineageStatus, lineage_metadata_store
from app.services.lineage_service import LineageService

router = APIRouter(tags=["Performance"])


def _resolve_lineage_artifact_path(*, calculation_id: UUID, artifact_name: str) -> str:
    safe_artifact_name = LineageService._validate_artifact_filename(artifact_name)
    lineage_dir = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
    return os.path.join(lineage_dir, safe_artifact_name)


def _load_and_validate_manifest(*, manifest_path: str, record) -> LineageManifest:
    try:
        manifest_payload = read_json_file(FilePath(manifest_path))
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


@router.get(
    "/lineage/{calculation_id}",
    response_model=LineageResponse,
    summary="Retrieve lineage artifact inventory",
    description=(
        "Returns durable lineage materialization status and controlled download URLs for artifacts associated "
        "with a calculation. Complete lineage requires a manifest that matches durable metadata and every "
        "declared artifact to exist on disk before URLs are returned."
    ),
    responses={
        404: {
            "description": "No lineage record exists, or a completed lineage record has no manifest.",
            "content": {
                "application/json": {"example": {"detail": "Lineage data not found for the given calculation_id."}}
            },
        },
        503: {
            "description": "Lineage storage or manifest integrity is degraded.",
            "content": {
                "application/json": {"example": {"detail": "Lineage manifest is inconsistent with durable metadata."}}
            },
        },
    },
)
async def get_lineage_data(
    request: Request,
    calculation_id: UUID = Path(
        description="Durable calculation identifier returned by an analytics endpoint.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    ),
) -> LineageResponse:
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
    summary="Download one lineage artifact",
    description=(
        "Downloads a lineage artifact through the controlled calculation/artifact route. Only artifacts declared "
        "by durable lineage metadata are downloadable, and the manifest must still match durable metadata before "
        "the file is served."
    ),
    responses={
        200: {
            "description": "Lineage artifact file content.",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {
            "description": "The lineage record is missing, incomplete, failed, or the artifact name is not declared.",
            "content": {"application/json": {"example": {"detail": "Lineage artifact not found."}}},
        },
        503: {
            "description": "The manifest or declared artifact file is missing or inconsistent in storage.",
            "content": {"application/json": {"example": {"detail": "Lineage artifact is missing from storage."}}},
        },
    },
)
async def get_lineage_artifact(
    calculation_id: UUID = Path(
        description="Durable calculation identifier returned by an analytics endpoint.",
        examples=["2f4f3e0e-6e0e-4e0e-8e0e-2f4f3e0e6e0e"],
    ),
    artifact_name: str = Path(
        description="Artifact filename declared by the completed lineage record.",
        examples=["request.json"],
    ),
):
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
