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
from app.models.platform_surfaces import ErrorDetailResponse
from app.services.durable_store_json import read_json_file
from app.services.lineage_metadata_store import LineageRecord, LineageStatus, lineage_metadata_store
from app.services.lineage_service import LineageService

router = APIRouter(tags=["Performance"])


def _resolve_lineage_artifact_path(*, calculation_id: UUID, artifact_name: str) -> str:
    safe_artifact_name = LineageService._validate_artifact_filename(artifact_name)
    lineage_dir = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
    return os.path.join(lineage_dir, safe_artifact_name)


def _load_and_validate_manifest(*, manifest_path: str, record: LineageRecord) -> LineageManifest:
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

    if not _manifest_matches_record(manifest=manifest, record=record):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lineage manifest is inconsistent with durable metadata.",
        )

    return manifest


def _manifest_matches_record(*, manifest: LineageManifest, record: LineageRecord) -> bool:
    return (
        manifest.calculation_type == record.calculation_type
        and manifest.timestamp_utc == record.timestamp_utc
        and manifest.status == record.status.value
        and sorted(manifest.artifact_names) == sorted(record.artifact_names)
    )


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


def _lineage_terminal_response(*, calculation_id: UUID, record: LineageRecord) -> LineageResponse | None:
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


def _lineage_artifact_links(
    *, request: Request, calculation_id: UUID, artifact_names: list[str]
) -> dict[str, ArtifactLink]:
    artifacts: dict[str, ArtifactLink] = {}
    for filename in artifact_names:
        if filename == "manifest.json":
            continue
        file_url = request.url_for(
            "lineage_artifact_file",
            calculation_id=str(calculation_id),
            artifact_name=filename,
        )
        artifacts[filename] = ArtifactLink(url=str(file_url))
    return artifacts


def _completed_lineage_response(
    *,
    request: Request,
    calculation_id: UUID,
    record: LineageRecord,
    manifest: LineageManifest,
) -> LineageResponse:
    return LineageResponse(
        calculation_id=calculation_id,
        calculation_type=manifest.calculation_type,
        timestamp_utc=manifest.timestamp_utc,
        status=record.status,
        artifacts=_lineage_artifact_links(
            request=request,
            calculation_id=calculation_id,
            artifact_names=record.artifact_names,
        ),
        error_message=record.error_message,
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
            "model": ErrorDetailResponse,
            "description": "No lineage record exists, or a completed lineage record has no manifest.",
            "content": {
                "application/json": {"example": {"detail": "Lineage data not found for the given calculation_id."}}
            },
        },
        503: {
            "model": ErrorDetailResponse,
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

    try:
        lineage_dir = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(calculation_id))
        terminal_response = _lineage_terminal_response(calculation_id=calculation_id, record=record)
        if terminal_response is not None:
            return terminal_response

        manifest_path = os.path.join(lineage_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lineage manifest not found.")

        manifest = _load_and_validate_manifest(manifest_path=manifest_path, record=record)
        _ensure_declared_artifacts_exist(calculation_id=calculation_id, artifact_names=record.artifact_names)

        return _completed_lineage_response(
            request=request,
            calculation_id=calculation_id,
            record=record,
            manifest=manifest,
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
            "model": ErrorDetailResponse,
            "description": "The lineage record is missing, incomplete, failed, or the artifact name is not declared.",
            "content": {"application/json": {"example": {"detail": "Lineage artifact not found."}}},
        },
        503: {
            "model": ErrorDetailResponse,
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
