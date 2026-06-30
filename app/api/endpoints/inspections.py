from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response

from app.api.http_response_adapter import to_fastapi_response
from app.core.config import get_settings
from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import TWRInspectionAcceptedResponse, TWRInspectionResponse
from app.models.platform_surfaces import ErrorDetailResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.artifact_filename_policy import validate_artifact_filename
from app.services.async_result_service import resolve_async_result
from app.services.inspection.twr_inspection_workflow_service import (
    accepted_twr_inspection_response,
    submit_twr_inspection_workflow,
)
from app.services.lineage_metadata_store import LineagePayload, LineageRecord, LineageStatus, lineage_metadata_store

router = APIRouter(tags=["Performance"])


def _inspection_storage_path(*, inspection_id: UUID, artifact_name: str | None = None) -> str:
    base_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(inspection_id))
    if artifact_name is None:
        return base_path
    safe_artifact_name = _safe_inspection_artifact_name(artifact_name)
    if safe_artifact_name is None:
        raise ValueError(f"Unsafe TWR inspection artifact filename: {artifact_name}")
    return os.path.join(base_path, safe_artifact_name)


def _safe_inspection_artifact_name(artifact_name: str) -> str | None:
    try:
        return validate_artifact_filename(artifact_name, artifact_kind="TWR inspection artifact")
    except ValueError:
        return None


def _is_completed_twr_inspection_record(record: LineageRecord | None) -> bool:
    return (
        record is not None
        and record.calculation_type == ANALYTICS_WORKFLOW_TWR_INSPECTION
        and record.status == LineageStatus.COMPLETE
    )


def _is_available_twr_inspection_artifact(record: LineageRecord | None, artifact_name: str) -> bool:
    if record is None:
        return False
    safe_artifact_name = _safe_inspection_artifact_name(artifact_name)
    if safe_artifact_name is None:
        return False
    safe_record_artifact_names = {
        safe_name for candidate in record.artifact_names if (safe_name := _safe_inspection_artifact_name(candidate))
    }
    return _is_completed_twr_inspection_record(record) and safe_artifact_name in safe_record_artifact_names


def _retained_inspection_artifact_response(*, payload: LineagePayload | None, artifact_name: str) -> Response | None:
    safe_artifact_name = _safe_inspection_artifact_name(artifact_name)
    if safe_artifact_name is None or payload is None or safe_artifact_name not in payload.details:
        return None
    media_type = "text/markdown" if safe_artifact_name.endswith(".md") else "application/json"
    return Response(
        content=payload.details[safe_artifact_name],
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_artifact_name}"'},
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
    record = lineage_metadata_store.get_record(inspection_id)
    if not _is_available_twr_inspection_artifact(record, artifact_name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection artifact not found.")

    artifact_path = _inspection_storage_path(inspection_id=inspection_id, artifact_name=artifact_name)
    if not os.path.exists(artifact_path):
        retained_response = _retained_inspection_artifact_response(
            payload=lineage_metadata_store.get_payload(inspection_id),
            artifact_name=artifact_name,
        )
        if retained_response is not None:
            return retained_response
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection artifact is missing from storage.",
        )
    return FileResponse(path=artifact_path, filename=artifact_name)
