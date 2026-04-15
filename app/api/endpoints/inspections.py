from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, Response

from app.core.config import get_settings
from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import TWRInspectionAcceptedResponse, TWRInspectionResponse
from app.services.async_result_service import resolve_async_result
from app.services.execution_registry import execution_registry
from app.services.lineage_metadata_store import LineageStatus, lineage_metadata_store
from app.services.submission_fencing_service import register_async_submission_or_raise
from core.repro import generate_canonical_hash

router = APIRouter(tags=["Performance"])


def _accepted_response(inspection_id: UUID) -> TWRInspectionAcceptedResponse:
    return TWRInspectionAcceptedResponse(
        inspection_id=inspection_id,
        poll_path=f"/performance/executions/{inspection_id}",
        result_path=f"/performance/inspections/{inspection_id}",
    )


def _inspection_storage_path(*, inspection_id: UUID, artifact_name: str | None = None) -> str:
    base_path = os.path.join(get_settings().LINEAGE_STORAGE_PATH, str(inspection_id))
    if artifact_name is None:
        return base_path
    return os.path.join(base_path, artifact_name)


@router.post(
    "/inspections/twr",
    response_model=TWRInspectionAcceptedResponse,
    summary="Submit a durable TWR supportability inspection",
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_twr_inspection(request: TWRInspectionRequest):
    input_fingerprint, calculation_hash = generate_canonical_hash(request, get_settings().APP_VERSION)
    portfolio_id = request.request.portfolio_id if request.request is not None else None
    if portfolio_id is None and request.subject_calculation_id is not None:
        existing = execution_registry.get_execution(request.subject_calculation_id)
        portfolio_id = existing.portfolio_id if existing is not None else None
    requested_window = {
        "subject_type": request.subject_type.value,
        "inspection_profile": request.inspection_profile.value,
        "subject_calculation_id": (
            str(request.subject_calculation_id) if request.subject_calculation_id is not None else None
        ),
    }
    return register_async_submission_or_raise(
        calculation_id=request.inspection_id,
        analytics_type="TWR_INSPECTION",
        portfolio_id=portfolio_id,
        requested_window=requested_window,
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        request_payload=request.model_dump(mode="json"),
        offload_reason="inspection_runtime",
        accepted_response_factory=_accepted_response,
    )


@router.get(
    "/inspections/{inspection_id}",
    response_model=TWRInspectionResponse | TWRInspectionAcceptedResponse,
    summary="Retrieve durable TWR inspection status or result",
)
def get_twr_inspection(inspection_id: UUID):
    return resolve_async_result(
        calculation_id=inspection_id,
        response_model=TWRInspectionResponse,
        accepted_response_factory=_accepted_response,
        not_found_detail="Inspection result not found for the given inspection_id.",
        failed_detail="Inspection execution failed.",
    )


@router.get(
    "/inspections/{inspection_id}/artifacts/{artifact_name}",
    include_in_schema=False,
)
def get_twr_inspection_artifact(inspection_id: UUID, artifact_name: str):
    record = lineage_metadata_store.get_record(inspection_id)
    if record is None or record.calculation_type != "TWR_INSPECTION" or record.status != LineageStatus.COMPLETE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection artifact not found.")
    if artifact_name not in record.artifact_names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection artifact not found.")

    artifact_path = _inspection_storage_path(inspection_id=inspection_id, artifact_name=artifact_name)
    if not os.path.exists(artifact_path):
        payload = lineage_metadata_store.get_payload(inspection_id)
        if payload is not None and artifact_name in payload.details:
            return Response(
                content=payload.details[artifact_name],
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{artifact_name}"'},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection artifact is missing from storage.",
        )
    return FileResponse(path=artifact_path, filename=artifact_name)
