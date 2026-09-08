from types import SimpleNamespace
from uuid import uuid4

from app.models.inspection_requests import TWRInspectionRequest
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR_INSPECTION
from app.services.inspection import twr_inspection_workflow_service


def test_twr_inspection_submission_metadata_uses_subject_execution_owner(mocker):
    subject_calculation_id = uuid4()
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(subject_calculation_id),
            "inspection_profile": "deep_reconciliation",
        }
    )
    mocker.patch(
        "app.services.inspection.twr_inspection_workflow_service.resolve_twr_calculation_execution_for_current_tenant",
        return_value=SimpleNamespace(portfolio_id="PORTFOLIO_001"),
    )

    assert twr_inspection_workflow_service.twr_inspection_portfolio_id(request) == "PORTFOLIO_001"
    assert twr_inspection_workflow_service.twr_inspection_requested_window(request) == {
        "subject_type": "twr_calculation",
        "inspection_profile": "deep_reconciliation",
        "subject_calculation_id": str(subject_calculation_id),
    }


def test_twr_inspection_submission_metadata_uses_embedded_request_owner():
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_request",
            "inspection_profile": "support_triage",
            "request": _twr_request_payload(portfolio_id="PB_SG_GLOBAL_BAL_001"),
        }
    )

    assert twr_inspection_workflow_service.twr_inspection_portfolio_id(request) == "PB_SG_GLOBAL_BAL_001"
    assert twr_inspection_workflow_service.twr_inspection_requested_window(request) == {
        "subject_type": "twr_request",
        "inspection_profile": "support_triage",
        "subject_calculation_id": None,
    }


def test_submit_twr_inspection_workflow_registers_async_submission_with_observability_context(mocker):
    request = TWRInspectionRequest.model_validate(
        {
            "inspection_id": str(uuid4()),
            "subject_type": "twr_request",
            "inspection_profile": "canonical_validation",
            "request": _twr_request_payload(portfolio_id="PB_SG_GLOBAL_BAL_001"),
        }
    )
    accepted_response = twr_inspection_workflow_service.accepted_twr_inspection_response(request.inspection_id)
    mocker.patch(
        "app.services.inspection.twr_inspection_workflow_service.calculation_engine_version",
        return_value="runtime-engine-version",
    )
    register_async = mocker.patch(
        "app.services.inspection.twr_inspection_workflow_service.register_async_submission_or_raise",
        return_value=accepted_response,
    )
    correlation_token = correlation_id_var.set("corr-inspection")
    request_token = request_id_var.set("req-inspection")
    trace_token = trace_id_var.set("trace-inspection")

    try:
        response = twr_inspection_workflow_service.submit_twr_inspection_workflow(request)
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert response == accepted_response
    assert register_async.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_TWR_INSPECTION
    assert register_async.call_args.kwargs["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert register_async.call_args.kwargs["requested_window"] == {
        "subject_type": "twr_request",
        "inspection_profile": "canonical_validation",
        "subject_calculation_id": None,
    }
    assert register_async.call_args.kwargs["offload_reason"] == "inspection_runtime"
    assert register_async.call_args.kwargs["requires_tenant_authority"] is False
    assert register_async.call_args.kwargs["request_payload"]["observability_context"] == {
        "correlation_id": "corr-inspection",
        "request_id": "req-inspection",
        "trace_id": "trace-inspection",
    }


def test_stateful_embedded_twr_inspection_requires_tenant_authority(mocker):
    request_payload = _twr_request_payload(portfolio_id="PB_SG_GLOBAL_BAL_001")
    request_payload["input_mode"] = "stateful"
    request_payload.pop("valuation_points")
    request_payload["stateful_input"] = {}
    request = TWRInspectionRequest.model_validate(
        {
            "inspection_id": str(uuid4()),
            "subject_type": "twr_request",
            "inspection_profile": "canonical_validation",
            "request": request_payload,
        }
    )
    register_async = mocker.patch(
        "app.services.inspection.twr_inspection_workflow_service.register_async_submission_or_raise",
        return_value=twr_inspection_workflow_service.accepted_twr_inspection_response(request.inspection_id),
    )

    twr_inspection_workflow_service.submit_twr_inspection_workflow(request)

    assert register_async.call_args.kwargs["requires_tenant_authority"] is True


def test_unresolved_calculation_subject_requires_tenant_authority(mocker):
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(uuid4()),
            "inspection_profile": "support_triage",
        }
    )
    mocker.patch(
        "app.services.inspection.twr_inspection_workflow_service.resolve_twr_calculation_execution_for_current_tenant",
        return_value=None,
    )

    assert twr_inspection_workflow_service.twr_inspection_requires_tenant_authority(request) is True


def test_tenantless_calculation_subject_preserves_portfolio_metadata(mocker):
    request = TWRInspectionRequest.model_validate(
        {
            "subject_type": "twr_calculation",
            "subject_calculation_id": str(uuid4()),
            "inspection_profile": "support_triage",
        }
    )
    tenantless_execution = SimpleNamespace(portfolio_id="PORTFOLIO_STATELESS")
    mocker.patch(
        "app.services.inspection.twr_inspection_workflow_service.resolve_twr_calculation_execution_for_current_tenant",
        return_value=tenantless_execution,
    )

    assert twr_inspection_workflow_service.twr_inspection_portfolio_id(request) == "PORTFOLIO_STATELESS"
    assert twr_inspection_workflow_service.twr_inspection_requires_tenant_authority(request) is False


def _twr_request_payload(*, portfolio_id: str) -> dict[str, object]:
    return {
        "portfolio_id": portfolio_id,
        "performance_start_date": "2026-01-01",
        "metric_basis": "NET",
        "report_end_date": "2026-01-02",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [{"perf_date": "2026-01-02", "begin_mv": 1000.0, "end_mv": 1001.0}],
    }
