from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.endpoints import performance as performance_endpoint
from app.models.twr_requests import TWRAnalyticsRequest
from app.models.workspace_summary_requests import WorkspaceSummaryRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR


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
async def test_twr_endpoint_replays_promoted_stateful_async_execution(mocker):
    request = TWRAnalyticsRequest.model_validate(_stateful_twr_payload())
    replay_response = performance_endpoint._accepted_twr_response(request.calculation_id)
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "runtime-version", "TWR_EXECUTOR_WINDOW_DAYS": 30, "TWR_EXECUTOR_INPUT_COUNT": 50},
        )(),
    )
    mocker.patch(
        "app.api.endpoints.performance.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    replay_promoted = performance_endpoint.replay_promoted_stateful_async_execution
    register_sync = mocker.patch("app.api.endpoints.performance.register_sync_execution_or_raise")

    response = await performance_endpoint.calculate_twr_endpoint(request)

    assert response == replay_response
    replay_promoted.assert_called_once()
    assert replay_promoted.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_TWR
    register_sync.assert_not_called()


@pytest.mark.asyncio
async def test_twr_endpoint_offloads_large_requests_before_resolution(mocker):
    request = TWRAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "performance_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "metric_basis": "NET",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "valuation_points": [
                {"perf_date": "2025-01-01", "begin_mv": 1000.0, "end_mv": 1001.0},
                {"perf_date": "2025-01-02", "begin_mv": 1001.0, "end_mv": 1002.0},
            ],
        }
    )
    accepted_response = performance_endpoint._accepted_twr_response(request.calculation_id)
    mocker.patch(
        "app.api.endpoints.performance.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "runtime-version", "TWR_EXECUTOR_WINDOW_DAYS": 30, "TWR_EXECUTOR_INPUT_COUNT": 2},
        )(),
    )
    register_async = mocker.patch(
        "app.api.endpoints.performance.register_async_submission_or_raise",
        return_value=accepted_response,
    )
    resolve_request = mocker.patch("app.api.endpoints.performance.resolve_twr_request")

    response = await performance_endpoint.calculate_twr_endpoint(request)

    assert response == accepted_response
    register_async.assert_called_once()
    assert register_async.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_TWR
    resolve_request.assert_not_called()


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

    assert performance_endpoint._twr_requested_benchmark_work_units(twr_request) == 0
    assert performance_endpoint._workspace_requested_benchmark_work_units(workspace_request) == 0
    assert performance_endpoint._workspace_longest_requested_window_days(workspace_request) == 10_000


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
    mocker.patch("app.api.endpoints.performance.register_sync_execution_or_raise")
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
    assert failure_capture["message"] == "bad workspace"


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
        "app.api.endpoints.performance.get_settings",
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
    mocker.patch("app.api.endpoints.performance.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.performance.resolve_attribution_request",
        side_effect=RuntimeError("attribution blew up"),
    )
    mocker.patch(
        "app.api.endpoints.performance.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await performance_endpoint.calculate_attribution_endpoint(request)

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

    assert performance_endpoint._attribution_input_count(request) == 3
