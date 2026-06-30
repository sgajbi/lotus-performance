from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.endpoints import performance as performance_endpoint
from app.models.attribution_analytics_requests import AttributionInputMode
from app.models.attribution_requests import AttributionRequest
from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest
from app.models.twr_requests import TWRAnalyticsRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services import attribution_calculation_workflow_service
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
from app.services.attribution_mode_service import ResolvedAttributionRequest
from app.services.twr_calculation_service import twr_requested_benchmark_work_units


def _stateful_twr_payload() -> dict[str, object]:
    return {
        "calculation_id": str(uuid4()),
        "portfolio_id": "P1",
        "performance_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "metric_basis": "NET",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }


@pytest.mark.asyncio
async def test_twr_endpoint_delegates_to_twr_workflow(mocker):
    request = TWRAnalyticsRequest.model_validate(_stateful_twr_payload())
    expected_response = object()
    calculate_twr = mocker.patch(
        "app.api.endpoints.performance.calculate_twr_workflow",
        return_value=expected_response,
    )

    response = await performance_endpoint.calculate_twr_endpoint(request)

    calculate_twr.assert_called_once_with(request)
    assert response is expected_response


def test_twr_workspace_helper_paths_cover_optional_benchmark_shapes():
    twr_request = TWRAnalyticsRequest.model_validate(
        {
            "portfolio_id": "P1",
            "performance_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "metric_basis": "NET",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_price_points": [
                        {"component_id": "IDX_1", "perf_date": "2025-01-01", "weight_bop": 1.0, "index_price": 100.0}
                    ],
                },
            },
            "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1001.0}],
        }
    )
    workspace_request = WorkspaceSummaryRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_end_date": "2025-01-02",
            "periods": [{"period": "SI", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_price_points": [
                        {"component_id": "IDX_1", "perf_date": "2025-01-01", "weight_bop": 1.0, "index_price": 100.0}
                    ],
                },
            },
        }
    )
    twr_request.benchmark.stateless_input = None
    workspace_request.benchmark.stateless_input.component_price_points = []

    assert twr_requested_benchmark_work_units(twr_request) == 0
    assert performance_endpoint._workspace_requested_benchmark_work_units(workspace_request) == 0
    assert performance_endpoint._workspace_longest_requested_window_days(workspace_request) == 10_000


def test_workspace_benchmark_work_units_count_calculated_observations():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "portfolio_id": "P1",
            "performance_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "periods": [{"period": "SI", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000.0, "end_mv": 1001.0}]
            },
            "benchmark": {
                "benchmark_id": "BMK_1",
                "input_mode": "stateless",
                "return_source": "calculated",
                "stateless_input": {
                    "benchmark_currency": "USD",
                    "component_observations": [
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2025-01-01",
                            "weight_bop": 1.0,
                            "component_return": 0.01,
                        },
                        {
                            "component_id": "IDX_1",
                            "perf_date": "2025-01-02",
                            "weight_bop": 1.0,
                            "component_return": 0.02,
                        },
                    ],
                },
            },
        }
    )

    assert performance_endpoint._workspace_requested_benchmark_work_units(request) == 2


def test_workspace_submission_helpers_project_window_and_offload_reason():
    request = WorkspaceSummaryRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_end_date": "2025-01-02",
            "periods": [{"period": "SI", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    assert performance_endpoint._workspace_requested_window(request) == {
        "report_end_date": "2025-01-02",
        "requested_periods": ["SI"],
        "input_mode": "stateful",
        "include_benchmark": False,
        "input_count": 0,
        "longest_window_days": 10_000,
    }
    assert performance_endpoint._workspace_offload_reason(request) == "long_window_stateful_workspace_summary"


def test_workspace_summary_async_submission_captures_observability_context(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_end_date": "2025-01-02",
            "periods": [{"period": "SI", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    accepted_response = performance_endpoint._accepted_workspace_summary_response(request.calculation_id)
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS": 30,
                "WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    register_async = mocker.patch(
        "app.api.endpoints.performance.register_async_submission_or_raise",
        return_value=accepted_response,
    )
    correlation_token = correlation_id_var.set("corr-workspace")
    request_token = request_id_var.set("req-workspace")
    trace_token = trace_id_var.set("trace-workspace")

    try:
        response = performance_endpoint.calculate_workspace_summary_endpoint(request)
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert response == accepted_response
    assert register_async.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
    assert register_async.call_args.kwargs["request_payload"]["observability_context"] == {
        "correlation_id": "corr-workspace",
        "request_id": "req-workspace",
        "trace_id": "trace-workspace",
    }


@pytest.mark.asyncio
async def test_workspace_summary_endpoint_records_http_exception_detail(mocker):
    request = WorkspaceSummaryRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_end_date": "2025-01-02",
            "performance_start_date": "2025-01-01",
            "periods": [{"period": "1M", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "valuation_points": [{"perf_date": "2025-01-02", "begin_mv": 1000.0, "end_mv": 1001.0}]
            },
        }
    )
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "WORKSPACE_SUMMARY_EXECUTOR_WINDOW_DAYS": 30,
                "WORKSPACE_SUMMARY_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    register_sync = mocker.patch("app.api.endpoints.performance.register_sync_execution_or_raise")
    mocker.patch("app.api.endpoints.performance.execution_registry.mark_running")
    mocker.patch(
        "app.api.endpoints.performance.calculate_workspace_summary",
        side_effect=HTTPException(status_code=422, detail="bad workspace"),
    )
    mocker.patch(
        "app.api.endpoints.performance.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        performance_endpoint.calculate_workspace_summary_endpoint(request)

    assert exc_info.value.status_code == 422
    assert register_sync.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_WORKSPACE_SUMMARY
    assert failure_capture["message"] == "bad workspace"


@pytest.mark.asyncio
async def test_mwr_endpoint_delegates_to_mwr_service(mocker):
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "MWR_UNIT",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [
                {"amount": 10000.0, "date": "2025-03-15"},
                {"amount": -5000.0, "date": "2025-09-20"},
            ],
            "mwr_method": "XIRR",
            "annualization": {"enabled": True, "basis": "ACT/365"},
        }
    )
    expected_response = object()
    calculate_mwr = mocker.patch(
        "app.api.endpoints.performance.calculate_mwr_response",
        return_value=expected_response,
    )

    response = await performance_endpoint.calculate_mwr_endpoint(request)

    calculate_mwr.assert_called_once_with(request)
    assert response is expected_response


@pytest.mark.asyncio
async def test_attribution_endpoint_maps_unexpected_resolution_errors_to_http_500(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "ATTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "ATTRIBUTION_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.attribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.resolve_attribution_request",
        side_effect=RuntimeError("attribution blew up"),
    )
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await attribution_calculation_workflow_service.calculate_attribution_workflow(request)

    assert exc_info.value.status_code == 500
    assert "attribution blew up" in str(exc_info.value.detail)
    assert "attribution blew up" in str(failure_capture["message"])


def test_attribution_input_count_prefers_nested_stateless_payload():
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateless",
            "stateless_input": {
                "instruments_data": [{"instrument_id": "A", "meta": {}, "valuation_points": []}],
                "portfolio_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
                "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
            },
        }
    )

    assert attribution_calculation_workflow_service.attribution_input_count(request) == 3


def test_attribution_input_count_supports_legacy_stateless_fields_and_stateful_zero():
    legacy_request = AttributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "instruments_data": [{"instrument_id": "A", "meta": {}, "valuation_points": []}],
            "portfolio_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    stateful_request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    assert attribution_calculation_workflow_service.attribution_input_count(legacy_request) == 3
    assert attribution_calculation_workflow_service.attribution_input_count(stateful_request) == 0


def test_attribution_execution_window_optional_metadata_filters_absent_values():
    assert attribution_calculation_workflow_service._attribution_execution_window_optional_metadata() == {}
    assert attribution_calculation_workflow_service._attribution_execution_window_optional_metadata(
        source_request_fingerprint="src-fingerprint",
        benchmark_id="BMK_1",
        benchmark_return_source="calculated",
    ) == {
        "source_request_fingerprint": "src-fingerprint",
        "benchmark_id": "BMK_1",
        "benchmark_return_source": "calculated",
    }


def test_build_attribution_execution_window_merges_optional_metadata():
    request = AttributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )

    window = attribution_calculation_workflow_service.build_attribution_execution_window(
        request,
        input_count=1,
        source_request_fingerprint="src-fingerprint",
        benchmark_id="BMK_1",
        benchmark_return_source="calculated",
    )

    assert window == {
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "requested_periods": ["ITD"],
        "input_count": 1,
        "mode": "by_group",
        "group_by": ["sector"],
        "input_mode": "stateless",
        "source_request_fingerprint": "src-fingerprint",
        "benchmark_id": "BMK_1",
        "benchmark_return_source": "calculated",
    }


def test_finalize_resolved_stateful_attribution_execution_preserves_resolved_identity(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    attribution_request = AttributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    resolved = ResolvedAttributionRequest(
        attribution_request=attribution_request,
        input_mode=AttributionInputMode.STATEFUL,
        input_count=7,
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="calculated",
    )
    settings = type("Settings", (), {"APP_VERSION": "runtime-version"})()
    accepted = attribution_calculation_workflow_service.accepted_attribution_response(request.calculation_id)
    finalize_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.generate_request_fingerprint",
        return_value=("resolved-fingerprint", "resolved-hash"),
    )
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.should_offload_resolved_attribution",
        return_value=True,
    )
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.finalize_resolved_stateful_execution",
        side_effect=lambda **kwargs: finalize_capture.update(kwargs) or accepted,
    )

    input_fingerprint, calculation_hash, accepted_response = (
        attribution_calculation_workflow_service._finalize_resolved_stateful_attribution_execution(
            request,
            resolved,
            active_settings=settings,
            source_request_fingerprint="source-fingerprint",
        )
    )

    assert input_fingerprint == "resolved-fingerprint"
    assert calculation_hash == "resolved-hash"
    assert accepted_response is accepted
    assert finalize_capture["calculation_id"] == request.calculation_id
    assert finalize_capture["input_fingerprint"] == "resolved-fingerprint"
    assert finalize_capture["calculation_hash"] == "resolved-hash"
    assert finalize_capture["should_offload"] is True
    assert finalize_capture["offload_reason"] == "large_resolved_stateful_attribution"
    requested_window = finalize_capture["requested_window"]
    assert isinstance(requested_window, dict)
    assert requested_window["source_request_fingerprint"] == "source-fingerprint"
    assert requested_window["benchmark_id"] == "BMK_1"
    assert requested_window["benchmark_return_source"] == "calculated"
    resolved_payload = finalize_capture["resolved_request_payload"]
    assert isinstance(resolved_payload, dict)
    assert resolved_payload["source_input_mode"] == "stateful"
    assert resolved_payload["resolved_benchmark_id"] == "BMK_1"


def test_calculate_resolved_attribution_response_returns_stateful_accepted_response(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    attribution_request = AttributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    resolved = ResolvedAttributionRequest(
        attribution_request=attribution_request,
        input_mode=AttributionInputMode.STATEFUL,
        input_count=7,
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="calculated",
    )
    accepted = attribution_calculation_workflow_service.accepted_attribution_response(request.calculation_id)
    finalize = mocker.patch(
        "app.services.attribution_calculation_workflow_service._finalize_resolved_stateful_attribution_execution",
        return_value=("resolved-fingerprint", "resolved-hash", accepted),
    )
    calculate = mocker.patch("app.services.attribution_calculation_workflow_service.calculate_attribution")

    response = attribution_calculation_workflow_service._calculate_resolved_attribution_response(
        request,
        resolved,
        active_settings=type("Settings", (), {"APP_VERSION": "runtime-version"})(),
        source_request_fingerprint="source-fingerprint",
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
    )

    assert response is accepted
    assert finalize.call_args.kwargs["source_request_fingerprint"] == "source-fingerprint"
    calculate.assert_not_called()


def test_initial_attribution_async_submission_projects_stateful_offload_reason(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-07-31",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    accepted = attribution_calculation_workflow_service.accepted_attribution_response(request.calculation_id)
    submission_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.should_offload_attribution",
        return_value=True,
    )
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.register_async_submission_or_raise",
        side_effect=lambda **kwargs: submission_capture.update(kwargs) or accepted,
    )

    response = attribution_calculation_workflow_service._initial_attribution_async_submission(
        request,
        requested_window={"input_count": 0},
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
    )

    assert response is accepted
    assert submission_capture["calculation_id"] == request.calculation_id
    assert submission_capture["analytics_type"] == "Attribution"
    assert submission_capture["portfolio_id"] == "P1"
    assert submission_capture["requested_window"] == {"input_count": 0}
    assert submission_capture["input_fingerprint"] == "input-fingerprint"
    assert submission_capture["calculation_hash"] == "calculation-hash"
    assert submission_capture["offload_reason"] == "long_window_stateful_attribution"


def test_stateful_attribution_replay_or_sync_window_returns_promoted_replay(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    accepted = attribution_calculation_workflow_service.accepted_attribution_response(request.calculation_id)
    replay = mocker.patch(
        "app.services.attribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=accepted,
    )
    requested_window = {"input_count": 0}

    replay_response, sync_window = attribution_calculation_workflow_service._stateful_attribution_replay_or_sync_window(
        request,
        source_request_fingerprint="source-fingerprint",
        requested_window=requested_window,
    )

    assert replay_response is accepted
    assert sync_window is requested_window
    assert replay.call_args.kwargs["source_request_fingerprint"] == "source-fingerprint"


def test_stateful_attribution_replay_or_sync_window_adds_source_fingerprint_without_replay(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )

    replay_response, sync_window = attribution_calculation_workflow_service._stateful_attribution_replay_or_sync_window(
        request,
        source_request_fingerprint="source-fingerprint",
        requested_window={"input_count": 0},
    )

    assert replay_response is None
    assert sync_window["input_count"] == 0
    assert sync_window["source_request_fingerprint"] == "source-fingerprint"


def test_register_attribution_sync_execution_projects_fencing_payload(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    register_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.attribution_calculation_workflow_service.register_sync_execution_or_raise",
        side_effect=lambda **kwargs: register_capture.update(kwargs),
    )

    attribution_calculation_workflow_service._register_attribution_sync_execution(
        request,
        requested_window={"input_count": 1},
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
    )

    assert register_capture == {
        "calculation_id": request.calculation_id,
        "analytics_type": "Attribution",
        "portfolio_id": "P1",
        "requested_window": {"input_count": 1},
        "input_fingerprint": "input-fingerprint",
        "calculation_hash": "calculation-hash",
    }


@pytest.mark.asyncio
async def test_resolve_and_calculate_attribution_response_delegates_to_resolved_calculation(mocker):
    request = performance_endpoint.AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    attribution_request = AttributionRequest.model_validate(
        {
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "mode": "by_group",
            "group_by": ["sector"],
            "benchmark_groups_data": [{"key": {"sector": "Tech"}, "observations": []}],
        }
    )
    resolved = ResolvedAttributionRequest(
        attribution_request=attribution_request,
        input_mode=AttributionInputMode.STATELESS,
        input_count=1,
        resolved_benchmark_id="BMK_1",
        resolved_benchmark_return_source="calculated",
    )
    settings = type("Settings", (), {"APP_VERSION": "runtime-version"})()
    expected_response = object()
    resolve = mocker.patch(
        "app.services.attribution_calculation_workflow_service.resolve_attribution_request",
        return_value=resolved,
    )
    calculate = mocker.patch(
        "app.services.attribution_calculation_workflow_service._calculate_resolved_attribution_response",
        return_value=expected_response,
    )

    response = await attribution_calculation_workflow_service._resolve_and_calculate_attribution_response(
        request,
        active_settings=settings,
        source_request_fingerprint="source-fingerprint",
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
    )

    assert response is expected_response
    resolve.assert_awaited_once_with(request, settings=settings)
    assert calculate.call_args.args == (request, resolved)
    assert calculate.call_args.kwargs["source_request_fingerprint"] == "source-fingerprint"
    assert calculate.call_args.kwargs["input_fingerprint"] == "input-fingerprint"
    assert calculate.call_args.kwargs["calculation_hash"] == "calculation-hash"
