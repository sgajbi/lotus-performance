from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response

from app.api.http_response_adapter import to_fastapi_response
from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import TWRInspectionAcceptedResponse, TWRInspectionResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.async_result_service import resolve_async_result
from app.services.inspection.twr_inspection_artifact_service import (
    RetainedTWRInspectionArtifact,
    TWRInspectionArtifactFileReference,
    resolve_twr_inspection_artifact,
)
from app.services.inspection.twr_inspection_workflow_service import (
    accepted_twr_inspection_response,
    submit_twr_inspection_workflow,
)

router = APIRouter(tags=["Performance"])


def _is_application_http_error(exc: Exception) -> bool:
    return hasattr(exc, "status_code") and hasattr(exc, "detail")


def _public_http_detail(*, status_code: int, detail: str):
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return {"message": detail}
    return detail


def _retained_inspection_artifact_response(artifact: RetainedTWRInspectionArtifact) -> Response:
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


@router.post(
    "/inspections/twr",
    response_model=TWRInspectionAcceptedResponse,
    summary="Submit a durable TWR supportability inspection",
    description=(
        "Submits a durable supportability inspection for an existing TWR calculation or a "
        "proposed TWR request. Use this triage endpoint when TWR numbers are not "
        "explainable from the headline result alone and support teams need source-quality, "
        "source-economics, reconciliation, and calculation-consistency findings without "
        "changing the normal TWR calculation contract."
    ),
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_twr_inspection(request: TWRInspectionRequest):
    return to_fastapi_response(submit_twr_inspection_workflow(request))


@router.get(
    "/inspections/{inspection_id}",
    response_model=TWRInspectionResponse | TWRInspectionAcceptedResponse,
    summary="Retrieve durable TWR inspection status or result",
    description=(
        "Retrieves the durable TWR inspection result when complete, or the accepted envelope "
        "while the supportability inspection is still queued or running."
    ),
    responses={
        202: {
            "model": TWRInspectionAcceptedResponse,
            "description": "The TWR supportability inspection is still pending.",
        },
        404: {
            "model": ErrorDetailResponse,
            "description": "No durable TWR inspection result exists for the supplied inspection_id.",
            "content": {
                "application/json": {"example": {"detail": "Inspection result not found for the given inspection_id."}}
            },
        },
    },
)
def get_twr_inspection(
    inspection_id: UUID, request: Request
) -> TWRInspectionResponse | TWRInspectionAcceptedResponse | JSONResponse:
    return to_fastapi_response(
        resolve_async_result(
            calculation_id=inspection_id,
            expected_analytics_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
            response_model=TWRInspectionResponse,
            accepted_response_factory=accepted_twr_inspection_response,
            not_found_detail="Inspection result not found for the given inspection_id.",
            failed_detail="Inspection execution failed.",
            request_headers=request.headers,
        )
    )


@router.get(
    "/inspections/{inspection_id}/artifacts/{artifact_name}",
    summary="Download a TWR inspection evidence artifact",
    description=(
        "Downloads one durable evidence artifact for a completed TWR supportability inspection. "
        "Use this route after `GET /performance/inspections/{inspection_id}` returns artifact links. "
        "Only artifact names recorded on the completed inspection are downloadable; missing records "
        "or unknown artifact names return 404, and artifacts declared in durable metadata but missing "
        "from storage return 503."
    ),
    responses={
        200: {
            "description": (
                "Inspection artifact content. JSON artifacts are returned as application/json; "
                "file-backed artifacts may use a file response content type."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "inspection_id": "9d000001-1111-4222-8333-abcdefabcdef",
                        "verdict": "supportable_with_warnings",
                    }
                },
                "application/octet-stream": {"example": '{"inspection_id":"9d000001-1111-4222-8333-abcdefabcdef"}'},
            },
        },
        404: {
            "model": ErrorDetailResponse,
            "description": "Inspection record or artifact name was not found for the supplied inspection_id.",
            "content": {"application/json": {"example": {"detail": "Inspection artifact not found."}}},
        },
        503: {
            "model": ErrorDetailResponse,
            "description": "The artifact is declared in durable metadata but is missing from storage.",
            "content": {"application/json": {"example": {"detail": "Inspection artifact is missing from storage."}}},
        },
    },
)
def get_twr_inspection_artifact(
    inspection_id: UUID = Path(
        description="Completed TWR inspection identifier returned by POST /performance/inspections/twr.",
        examples=["9d000001-1111-4222-8333-abcdefabcdef"],
    ),
    artifact_name: str = Path(
        description=(
            "Inspection artifact file name. Supported names include inspection_summary.json, findings.json, "
            "support_brief.md, source_quality_summary.json, reconciliation_summary.json, and "
            "source_economics_summary.json when the corresponding check family ran."
        ),
        examples=["support_brief.md"],
    ),
):
    try:
        artifact = resolve_twr_inspection_artifact(inspection_id=inspection_id, artifact_name=artifact_name)
    except Exception as exc:
        if not _is_application_http_error(exc):
            raise
        raise HTTPException(
            status_code=getattr(exc, "status_code"),
            detail=_public_http_detail(status_code=getattr(exc, "status_code"), detail=getattr(exc, "detail")),
        ) from exc
    if isinstance(artifact, RetainedTWRInspectionArtifact):
        return _retained_inspection_artifact_response(artifact)
    if isinstance(artifact, TWRInspectionArtifactFileReference):
        return FileResponse(
            path=artifact.path,
            filename=artifact.filename,
        )
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unsupported inspection artifact.")
