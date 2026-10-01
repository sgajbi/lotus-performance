"""Synchronous workflow boundary for v1 group-return evidence."""

from __future__ import annotations

from app.core.config import get_settings
from app.models.group_return_evidence import GroupReturnEvidenceRequest, GroupReturnEvidenceResponse
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_GROUP_RETURN_EVIDENCE
from app.services.execution_lifecycle_service import record_execution_failure
from app.services.execution_registry import execution_registry
from app.services.execution_stage_errors import (
    execution_stage_failure_detail,
    is_mappable_application_error,
    safe_unexpected_failure_message,
)
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION
from app.services.group_return_evidence_service import (
    GroupReturnEvidenceSourceInput,
    build_group_return_evidence_response,
)
from app.services.portfolio_source_service import build_stateful_input_service
from app.services.stateful_attribution_input_service import retrieve_stateful_attribution_source_input
from app.services.submission_fencing_service import register_sync_execution_or_raise
from core.errors import APIInternalServerError, APIUnprocessableEntityError

_UNEXPECTED_GROUP_RETURN_EVIDENCE_FAILURE_DETAIL = safe_unexpected_failure_message("Group return evidence")
_REQUIRED_SOURCE_SNAPSHOT_ENDPOINTS = {
    "portfolio_timeseries",
    "position_timeseries",
    "benchmark_composition_window",
    "index_catalog",
    "index_price_series",
}


async def calculate_group_return_evidence_response(
    request: GroupReturnEvidenceRequest,
) -> GroupReturnEvidenceResponse:
    """Retrieve one admitted-tenant source cut and publish only reconciled group economics."""
    stateful_input_service = build_stateful_input_service(settings=get_settings())
    _register_group_return_evidence_execution(request)
    execution_registry.mark_running(request.calculation_id)
    execution_stage_started = False
    try:
        execution_registry.start_stage(request.calculation_id, EXECUTION_STAGE_EXECUTION)
        execution_stage_started = True
        source_input = await retrieve_stateful_attribution_source_input(
            settings=get_settings(),
            stateful_input_service=stateful_input_service,
            calculation_id=request.calculation_id,
            portfolio_id=request.portfolio_id,
            as_of_date=request.as_of_date,
            report_start_date=request.window.start_date,
            report_end_date=request.window.end_date,
            reporting_currency=request.reporting_currency,
            consumer_system="lotus-risk",
            group_by=[request.grouping_dimension.value.lower()],
            dimensions=[],
            include_cash_flows=True,
            filters={},
            benchmark_id_override=request.benchmark_id,
        )
        snapshots = execution_registry.list_upstream_snapshots(request.calculation_id)
        _validate_required_source_snapshot_endpoints(snapshots)
        _validate_snapshot_scope(snapshots=snapshots, request=request, benchmark_id=source_input.benchmark_id)
        response = build_group_return_evidence_response(
            request=request,
            source_input=GroupReturnEvidenceSourceInput(
                portfolio_input=source_input.portfolio_input,
                position_rows=source_input.position_rows,
                position_source_rows_complete=source_input.position_source_rows_complete,
                benchmark_id=source_input.benchmark_id,
                benchmark_currency=source_input.benchmark_currency,
                benchmark_component_observations=source_input.benchmark_component_observations,
                index_records=source_input.index_records,
            ),
            source_snapshots=snapshots,
        )
        execution_registry.complete_stage(
            request.calculation_id,
            EXECUTION_STAGE_EXECUTION,
            details={"row_count": len(response.rows), "source_cut_id": response.source_lineage.source_cut_id},
        )
        execution_registry.mark_complete(request.calculation_id)
        return response
    except ValueError as exc:
        _record_group_return_evidence_failure(
            request=request,
            message=str(exc),
            execution_stage_started=execution_stage_started,
        )
        raise APIUnprocessableEntityError(str(exc)) from exc
    except Exception as exc:
        if is_mappable_application_error(exc):
            _record_group_return_evidence_failure(
                request=request,
                message=execution_stage_failure_detail(exc),
                execution_stage_started=execution_stage_started,
            )
            raise
        _record_group_return_evidence_failure(
            request=request,
            message=_UNEXPECTED_GROUP_RETURN_EVIDENCE_FAILURE_DETAIL,
            execution_stage_started=execution_stage_started,
        )
        raise APIInternalServerError(_UNEXPECTED_GROUP_RETURN_EVIDENCE_FAILURE_DETAIL) from exc


def _register_group_return_evidence_execution(request: GroupReturnEvidenceRequest) -> None:
    register_sync_execution_or_raise(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_GROUP_RETURN_EVIDENCE,
        portfolio_id=request.portfolio_id,
        requested_window={
            "as_of_date": str(request.as_of_date),
            "window_start_date": str(request.window.start_date),
            "window_end_date": str(request.window.end_date),
            "grouping_dimension": request.grouping_dimension.value,
            "benchmark_id": request.benchmark_id,
            "reporting_currency": request.reporting_currency,
            "contract_version": "v1",
        },
        input_fingerprint=None,
        calculation_hash=None,
    )


def _validate_required_source_snapshot_endpoints(snapshots: list[object]) -> None:
    endpoints = {str(getattr(snapshot, "upstream_endpoint", "")) for snapshot in snapshots}
    missing = sorted(_REQUIRED_SOURCE_SNAPSHOT_ENDPOINTS - endpoints)
    if missing:
        raise ValueError(
            "group return evidence source lineage is incomplete; missing snapshots for: " + ", ".join(missing)
        )


def _validate_snapshot_scope(
    *,
    snapshots: list[object],
    request: GroupReturnEvidenceRequest,
    benchmark_id: str,
) -> None:
    expected_as_of_dates = {
        "portfolio_timeseries": request.as_of_date.isoformat(),
        "position_timeseries": request.as_of_date.isoformat(),
        "benchmark_composition_window": request.window.end_date.isoformat(),
        "index_catalog": request.as_of_date.isoformat(),
        "index_price_series": request.as_of_date.isoformat(),
    }
    expected_source_identifiers = {
        "portfolio_timeseries": request.portfolio_id,
        "position_timeseries": request.portfolio_id,
        "benchmark_composition_window": benchmark_id,
    }
    for snapshot in snapshots:
        endpoint = str(getattr(snapshot, "upstream_endpoint", ""))
        expected_as_of_date = expected_as_of_dates.get(endpoint)
        if expected_as_of_date is not None and str(getattr(snapshot, "as_of_date", "")) != expected_as_of_date:
            raise ValueError(
                "group return evidence source lineage is stale or inconsistent for "
                f"{endpoint}: expected as_of_date {expected_as_of_date}."
            )
        expected_source_identifier = expected_source_identifiers.get(endpoint)
        if (
            expected_source_identifier is not None
            and str(getattr(snapshot, "source_identifier", "")) != expected_source_identifier
        ):
            raise ValueError(
                f"group return evidence source lineage has a foreign or conflicting source identifier for {endpoint}."
            )


def _record_group_return_evidence_failure(
    *,
    request: GroupReturnEvidenceRequest,
    message: str,
    execution_stage_started: bool,
) -> None:
    record_execution_failure(
        calculation_id=request.calculation_id,
        message=message,
        execution_stage_started=execution_stage_started,
    )
