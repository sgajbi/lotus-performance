from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.models.inspection_requests import TWRInspectionRequest, TWRInspectionSubjectType
from app.services.execution_registry import ExecutionRecord, execution_registry


@dataclass(frozen=True)
class ResolvedTWRInspectionSubject:
    subject_type: TWRInspectionSubjectType
    subject_calculation_id: UUID | None
    portfolio_id: str | None
    related_execution: ExecutionRecord | None
    request_payload: dict | None


def resolve_twr_inspection_subject(request: TWRInspectionRequest) -> ResolvedTWRInspectionSubject:
    if request.subject_type == TWRInspectionSubjectType.TWR_CALCULATION:
        execution = execution_registry.get_execution(request.subject_calculation_id)
        if execution is None:
            raise KeyError(f"TWR calculation execution not found: {request.subject_calculation_id}")
        if execution.analytics_type != "TWR":
            raise ValueError(
                f"Inspection subject must reference a TWR calculation, not {execution.analytics_type}: "
                f"{request.subject_calculation_id}"
            )
        return ResolvedTWRInspectionSubject(
            subject_type=request.subject_type,
            subject_calculation_id=request.subject_calculation_id,
            portfolio_id=execution.portfolio_id,
            related_execution=execution,
            request_payload=None,
        )

    inspection_request = request.request
    if inspection_request is None:
        raise ValueError("twr_request inspection requires request payload.")
    return ResolvedTWRInspectionSubject(
        subject_type=request.subject_type,
        subject_calculation_id=None,
        portfolio_id=inspection_request.portfolio_id,
        related_execution=None,
        request_payload=inspection_request.model_dump(mode="json"),
    )
