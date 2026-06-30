from __future__ import annotations

from uuid import UUID

from app.core.application_responses import ApplicationHttpResponse
from app.core.config import get_settings
from app.models.inspection_requests import TWRInspectionRequest
from app.models.inspection_responses import TWRInspectionAcceptedResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.async_observability_context import async_observability_request_payload
from app.services.execution_registry import execution_registry
from app.services.reproducibility_service import generate_request_fingerprint
from app.services.submission_fencing_service import register_async_submission_or_raise


def accepted_twr_inspection_response(inspection_id: UUID) -> TWRInspectionAcceptedResponse:
    return TWRInspectionAcceptedResponse(
        inspection_id=inspection_id,
        poll_path=f"/performance/executions/{inspection_id}",
        result_path=f"/performance/inspections/{inspection_id}",
    )


def twr_inspection_portfolio_id(request: TWRInspectionRequest) -> str | None:
    if request.request is not None:
        return request.request.portfolio_id
    if request.subject_calculation_id is None:
        return None
    existing = execution_registry.get_execution(request.subject_calculation_id)
    return existing.portfolio_id if existing is not None else None


def twr_inspection_requested_window(request: TWRInspectionRequest) -> dict[str, str | None]:
    return {
        "subject_type": request.subject_type.value,
        "inspection_profile": request.inspection_profile.value,
        "subject_calculation_id": (
            str(request.subject_calculation_id) if request.subject_calculation_id is not None else None
        ),
    }


def submit_twr_inspection_workflow(request: TWRInspectionRequest) -> ApplicationHttpResponse:
    input_fingerprint, calculation_hash = generate_request_fingerprint(request, get_settings().APP_VERSION)
    return register_async_submission_or_raise(
        calculation_id=request.inspection_id,
        analytics_type=ANALYTICS_WORKFLOW_TWR_INSPECTION,
        portfolio_id=twr_inspection_portfolio_id(request),
        requested_window=twr_inspection_requested_window(request),
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        request_payload=async_observability_request_payload(request.model_dump(mode="json")),
        offload_reason="inspection_runtime",
        accepted_response_factory=accepted_twr_inspection_response,
    )
