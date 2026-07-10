import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import FileResponse

from app.models.lineage_responses import LineageResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.services.execution_stage_errors import safe_unexpected_failure_message
from app.services.lineage_artifact_service import resolve_lineage_artifact_file, resolve_lineage_response

router = APIRouter(tags=["Performance"])
logger = logging.getLogger(__name__)


def _is_application_http_error(exc: Exception) -> bool:
    return hasattr(exc, "status_code") and hasattr(exc, "detail")


def _public_http_detail(*, status_code: int, detail: str):
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return {"message": detail}
    return detail


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
    try:
        return resolve_lineage_response(
            calculation_id=calculation_id,
            artifact_url_factory=lambda artifact_name: str(
                request.url_for(
                    "lineage_artifact_file",
                    calculation_id=str(calculation_id),
                    artifact_name=artifact_name,
                )
            ),
        )
    except Exception as exc:
        if not _is_application_http_error(exc):
            logger.exception(
                "Unexpected lineage artifact inventory retrieval failure.",
                extra={"calculation_id": str(calculation_id)},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=safe_unexpected_failure_message("Lineage artifact retrieval"),
            ) from exc
        raise HTTPException(
            status_code=getattr(exc, "status_code"),
            detail=_public_http_detail(status_code=getattr(exc, "status_code"), detail=getattr(exc, "detail")),
        ) from exc


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
    try:
        artifact = resolve_lineage_artifact_file(calculation_id=calculation_id, artifact_name=artifact_name)
    except Exception as exc:
        if not _is_application_http_error(exc):
            raise
        raise HTTPException(
            status_code=getattr(exc, "status_code"),
            detail=_public_http_detail(status_code=getattr(exc, "status_code"), detail=getattr(exc, "detail")),
        ) from exc
    return FileResponse(path=artifact.path, filename=artifact.filename)
