from uuid import uuid4

import pytest

from app.models.benchmark_analytics_requests import BenchmarkInputMode, BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.models.requests import PerformanceRequest
from app.models.twr_requests import TWRAnalyticsRequest, TWRInputMode
from app.services import twr_calculation_service
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_TWR
from app.services.twr_mode_service import ResolvedTWRRequest


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


def _performance_request(calculation_id) -> PerformanceRequest:
    return PerformanceRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
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


def _benchmark_request(calculation_id) -> BenchmarkPerformanceRequest:
    return BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(calculation_id),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "return_source": "vendor_series",
            "benchmark_currency": "USD",
            "benchmark_return_points": [
                {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                {"perf_date": "2025-01-02", "benchmark_return": 0.02},
            ],
        }
    )


def test_twr_resolved_identity_helpers_select_artifact_and_benchmark_return_source():
    request = TWRAnalyticsRequest.model_validate(_stateful_twr_payload())
    performance_request = _performance_request(request.calculation_id)
    benchmark_request = _benchmark_request(request.calculation_id)
    resolved_identity = twr_calculation_service.build_resolved_twr_identity_payload(
        performance_request=performance_request,
        benchmark_request=benchmark_request,
    )
    stateful_resolved = ResolvedTWRRequest(
        performance_request=performance_request,
        input_mode=request.input_mode,
        benchmark_request=benchmark_request,
        benchmark_input_mode=BenchmarkInputMode.STATEFUL,
        resolved_benchmark_id="BMK_1",
    )
    stateless_resolved = ResolvedTWRRequest(
        performance_request=performance_request,
        input_mode=TWRInputMode.STATELESS,
    )

    assert twr_calculation_service.twr_resolved_identity_required(stateful_resolved) is True
    assert twr_calculation_service.twr_resolved_identity_required(stateless_resolved) is False
    assert (
        twr_calculation_service.twr_request_artifact_model(
            request=request,
            resolved_request=stateful_resolved,
            resolved_twr_identity_payload=resolved_identity,
        )
        == resolved_identity
    )
    assert (
        twr_calculation_service.twr_request_artifact_model(
            request=request,
            resolved_request=stateless_resolved,
            resolved_twr_identity_payload=resolved_identity,
        )
        == request
    )
    assert twr_calculation_service.twr_resolved_benchmark_return_source(request) == BenchmarkReturnSource.CALCULATED


def test_finalize_twr_resolved_execution_identity_preserves_stateful_payload(mocker):
    request = TWRAnalyticsRequest.model_validate(_stateful_twr_payload())
    performance_request = _performance_request(request.calculation_id)
    resolved_identity = twr_calculation_service.build_resolved_twr_identity_payload(
        performance_request=performance_request,
        benchmark_request=None,
    )
    resolved_request = ResolvedTWRRequest(
        performance_request=performance_request,
        input_mode=request.input_mode,
        resolved_benchmark_id=None,
    )
    accepted_response = twr_calculation_service.accepted_twr_response(request.calculation_id)
    mocker.patch("app.services.twr_calculation_service.should_offload_resolved_twr", return_value=True)
    finalize_resolved = mocker.patch(
        "app.services.twr_calculation_service.finalize_resolved_stateful_execution",
        return_value=accepted_response,
    )

    input_fingerprint, calculation_hash, response = twr_calculation_service.finalize_twr_resolved_execution_identity(
        request=request,
        resolved_request=resolved_request,
        resolved_twr_identity_payload=resolved_identity,
        source_request_fingerprint="source-fingerprint",
        resolved_input_count=2,
        benchmark_work_units=0,
        engine_version="runtime-version",
    )

    assert input_fingerprint
    assert calculation_hash
    assert response == accepted_response
    finalize_resolved.assert_called_once()
    assert finalize_resolved.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_TWR
    assert finalize_resolved.call_args.kwargs["offload_reason"] == "large_resolved_stateful_twr"
    assert finalize_resolved.call_args.kwargs["resolved_request_payload"]["portfolio_id"] == "P1"
    assert finalize_resolved.call_args.kwargs["resolved_request_payload"]["benchmark_return_source"] == "calculated"


@pytest.mark.asyncio
async def test_calculate_twr_workflow_replays_promoted_stateful_async_execution(mocker):
    request = TWRAnalyticsRequest.model_validate(_stateful_twr_payload())
    replay_response = twr_calculation_service.accepted_twr_response(request.calculation_id)
    mocker.patch(
        "app.services.twr_calculation_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "runtime-version", "TWR_EXECUTOR_WINDOW_DAYS": 30, "TWR_EXECUTOR_INPUT_COUNT": 50},
        )(),
    )
    mocker.patch(
        "app.services.twr_calculation_service.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    replay_promoted = twr_calculation_service.replay_promoted_stateful_async_execution
    register_sync = mocker.patch("app.services.twr_calculation_service.register_sync_execution_or_raise")

    response = await twr_calculation_service.calculate_twr_workflow(request)

    assert response == replay_response
    replay_promoted.assert_called_once()
    assert replay_promoted.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_TWR
    register_sync.assert_not_called()


@pytest.mark.asyncio
async def test_calculate_twr_workflow_offloads_large_requests_before_resolution(mocker):
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
    accepted_response = twr_calculation_service.accepted_twr_response(request.calculation_id)
    mocker.patch(
        "app.services.twr_calculation_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "runtime-version", "TWR_EXECUTOR_WINDOW_DAYS": 30, "TWR_EXECUTOR_INPUT_COUNT": 2},
        )(),
    )
    register_async = mocker.patch(
        "app.services.twr_calculation_service.register_async_submission_or_raise",
        return_value=accepted_response,
    )
    resolve_request = mocker.patch("app.services.twr_calculation_service.resolve_twr_request")

    response = await twr_calculation_service.calculate_twr_workflow(request)

    assert response == accepted_response
    register_async.assert_called_once()
    assert register_async.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_TWR
    resolve_request.assert_not_called()
