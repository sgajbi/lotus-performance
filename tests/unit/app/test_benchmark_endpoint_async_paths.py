from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.endpoints import benchmark as benchmark_endpoint
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services import benchmark_calculation_workflow_service
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_BENCHMARK
from app.services.benchmark_mode_service import ResolvedBenchmarkRequest
from core.errors import APIError


def _stateful_benchmark_payload() -> dict[str, object]:
    return {
        "calculation_id": str(uuid4()),
        "benchmark_id": "BMK_1",
        "benchmark_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }


def _resolved_benchmark_request() -> BenchmarkPerformanceRequest:
    return BenchmarkPerformanceRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_1",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "benchmark_currency": "USD",
            "return_source": "calculated",
            "component_observations": [
                {
                    "component_id": "IDX_1",
                    "perf_date": "2025-01-01",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_resolve_benchmark_execution_context_replaces_identity_for_persisted_request(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_PRICE",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_price_points": [
                    {"component_id": "IDX_1", "perf_date": "2024-12-31", "weight_bop": 1.0, "index_price": 100.0},
                    {"component_id": "IDX_1", "perf_date": "2025-01-01", "weight_bop": 1.0, "index_price": 101.0},
                ],
            },
        }
    )
    resolved_request = _resolved_benchmark_request()
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATELESS,
            source_details={"component_price_points": 2},
            input_count=2,
        ),
    )
    generate_fingerprint = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.generate_request_fingerprint",
        return_value=("resolved-fingerprint", "resolved-hash"),
    )

    context = await benchmark_calculation_workflow_service._resolve_benchmark_execution_context(
        request=request,
        settings=SimpleNamespace(APP_VERSION="runtime-version"),
        input_fingerprint="source-fingerprint",
        calculation_hash="source-hash",
    )

    assert context.benchmark_request == resolved_request
    assert context.request_model_for_lineage == resolved_request
    assert context.input_fingerprint == "resolved-fingerprint"
    assert context.calculation_hash == "resolved-hash"
    assert context.should_persist_request is True
    generate_fingerprint.assert_called_once_with(resolved_request, "runtime-version")


@pytest.mark.asyncio
async def test_benchmark_endpoint_replays_promoted_stateful_async_execution(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    replay_response = benchmark_calculation_workflow_service.accepted_benchmark_response(request.calculation_id)
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    replay_promoted = benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution
    register_sync = mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")

    response = await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert response == replay_response
    replay_promoted.assert_called_once()
    assert replay_promoted.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_BENCHMARK
    register_sync.assert_not_called()


@pytest.mark.asyncio
async def test_promoted_stateful_benchmark_workflow_replays_without_registering(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    replay_response = benchmark_calculation_workflow_service.accepted_benchmark_response(request.calculation_id)
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    replay_promoted = benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution
    register_sync = mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")

    response = await benchmark_calculation_workflow_service._calculate_promoted_stateful_benchmark_workflow(
        request=request,
        settings=type("Settings", (), {"APP_VERSION": "runtime-version"})(),
        source_request_fingerprint="source-fingerprint",
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
    )

    assert response == replay_response
    replay_promoted.assert_called_once()
    assert replay_promoted.call_args.kwargs["source_request_fingerprint"] == "input-fingerprint"
    register_sync.assert_not_called()


def test_finalize_promoted_stateful_benchmark_execution_projects_resolved_payload(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    resolved_request = _resolved_benchmark_request()
    accepted_response = benchmark_calculation_workflow_service.accepted_benchmark_response(request.calculation_id)
    resolved_context = benchmark_calculation_workflow_service._ResolvedBenchmarkExecutionContext(
        resolved_request=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATEFUL,
            source_details={"component_observations": 3},
            input_count=3,
        ),
        benchmark_request=resolved_request,
        request_model_for_lineage=resolved_request,
        input_fingerprint="resolved-fingerprint",
        calculation_hash="resolved-hash",
        should_persist_request=True,
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.should_offload_resolved_benchmark",
        return_value=True,
    )
    finalize_resolved = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.finalize_resolved_stateful_execution",
        return_value=accepted_response,
    )
    correlation_token = correlation_id_var.set(" corr-benchmark ")
    request_token = request_id_var.set(" req-benchmark ")
    trace_token = trace_id_var.set(" trace-benchmark ")

    try:
        response = benchmark_calculation_workflow_service._finalize_promoted_stateful_benchmark_execution(
            request=request,
            source_request_fingerprint="source-fingerprint",
            resolved_context=resolved_context,
        )
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert response == accepted_response
    assert finalize_resolved.call_args.kwargs["calculation_id"] == request.calculation_id
    assert finalize_resolved.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_BENCHMARK
    assert finalize_resolved.call_args.kwargs["requested_window"]["source_request_fingerprint"] == "source-fingerprint"
    assert finalize_resolved.call_args.kwargs["requested_window"]["input_count"] == 3
    assert finalize_resolved.call_args.kwargs["input_fingerprint"] == "resolved-fingerprint"
    assert finalize_resolved.call_args.kwargs["calculation_hash"] == "resolved-hash"
    assert finalize_resolved.call_args.kwargs["resolved_request_payload"] == {
        "resolved_request": resolved_request.model_dump(mode="json"),
        "source_input_mode": BenchmarkInputMode.STATEFUL.value,
        "observability_context": {
            "correlation_id": "corr-benchmark",
            "request_id": "req-benchmark",
            "trace_id": "trace-benchmark",
        },
    }
    assert finalize_resolved.call_args.kwargs["should_offload"] is True
    assert finalize_resolved.call_args.kwargs["offload_reason"] == "large_resolved_stateful_benchmark"
    assert finalize_resolved.call_args.kwargs["accepted_response_factory"] is (
        benchmark_calculation_workflow_service.accepted_benchmark_response
    )


@pytest.mark.asyncio
async def test_benchmark_endpoint_returns_accepted_response_when_resolved_stateful_request_is_offloaded(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    resolved_request = _resolved_benchmark_request()
    accepted_response = benchmark_calculation_workflow_service.accepted_benchmark_response(request.calculation_id)
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 2,
            },
        )(),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATEFUL,
            source_details={"component_observations": 2},
            input_count=2,
        ),
    )
    finalize_resolved = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.finalize_resolved_stateful_execution",
        return_value=accepted_response,
    )
    calculate_benchmark = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.calculate_benchmark_response"
    )

    response = await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert response == accepted_response
    finalize_resolved.assert_called_once()
    assert finalize_resolved.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_BENCHMARK
    calculate_benchmark.assert_not_called()


@pytest.mark.asyncio
async def test_benchmark_endpoint_executes_resolved_stateful_request_when_finalize_keeps_it_sync(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    resolved_request = _resolved_benchmark_request()
    expected_response = {"ok": True}
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATEFUL,
            source_details={"component_observations": 1},
            input_count=1,
        ),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.finalize_resolved_stateful_execution",
        return_value=None,
    )
    calculate_benchmark = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.calculate_benchmark_response",
        return_value=expected_response,
    )

    response = await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert response == expected_response
    calculate_benchmark.assert_called_once()


@pytest.mark.asyncio
async def test_benchmark_endpoint_reraises_stateful_http_exceptions(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        side_effect=HTTPException(status_code=422, detail="bad benchmark request"),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "bad benchmark request"
    assert failure_capture["message"] == "bad benchmark request"


@pytest.mark.asyncio
async def test_benchmark_endpoint_updates_execution_identity_for_persisted_sync_requests(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_PRICE",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "calculated",
            "stateless_input": {
                "benchmark_currency": "USD",
                "component_price_points": [
                    {"component_id": "IDX_1", "perf_date": "2024-12-31", "weight_bop": 1.0, "index_price": 100.0},
                    {"component_id": "IDX_1", "perf_date": "2025-01-01", "weight_bop": 1.0, "index_price": 101.0},
                ],
            },
        }
    )
    resolved_request = _resolved_benchmark_request()
    expected_response = {"ok": True}
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATELESS,
            source_details={"component_observations": 1},
            input_count=1,
        ),
    )
    update_execution_identity = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.execution_registry.update_execution_identity"
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.calculate_benchmark_response",
        return_value=expected_response,
    )

    response = await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert response == expected_response
    update_execution_identity.assert_called_once()


@pytest.mark.asyncio
async def test_benchmark_endpoint_offloads_large_requests(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    {"perf_date": "2025-01-02", "benchmark_return": 0.01},
                ],
            },
        }
    )
    accepted_response = benchmark_calculation_workflow_service.accepted_benchmark_response(request.calculation_id)
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 2,
            },
        )(),
    )
    register_async = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.register_async_submission_or_raise",
        return_value=accepted_response,
    )

    response = await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert response == accepted_response
    register_async.assert_called_once()
    assert register_async.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_BENCHMARK


def test_initial_benchmark_async_submission_projects_large_input_payload(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                    {"perf_date": "2025-01-02", "benchmark_return": 0.01},
                ],
            },
        }
    )
    accepted_response = benchmark_calculation_workflow_service.accepted_benchmark_response(request.calculation_id)
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.should_offload_benchmark",
        return_value=True,
    )
    register_async = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.register_async_submission_or_raise",
        return_value=accepted_response,
    )

    response = benchmark_calculation_workflow_service._initial_benchmark_async_submission(
        request,
        source_request_fingerprint="source-fingerprint",
        source_request_hash="source-hash",
    )

    assert response == accepted_response
    assert register_async.call_args.kwargs["calculation_id"] == request.calculation_id
    assert register_async.call_args.kwargs["analytics_type"] == ANALYTICS_WORKFLOW_BENCHMARK
    assert register_async.call_args.kwargs["portfolio_id"] == "BMK_VENDOR"
    assert register_async.call_args.kwargs["input_fingerprint"] == "source-fingerprint"
    assert register_async.call_args.kwargs["calculation_hash"] == "source-hash"
    assert register_async.call_args.kwargs["requested_window"]["input_count"] == 2
    assert register_async.call_args.kwargs["offload_reason"] == "large_benchmark_input_set"


@pytest.mark.asyncio
async def test_initial_sync_benchmark_workflow_preserves_source_identity_for_non_persisted_request(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [{"perf_date": "2025-01-01", "benchmark_return": 0.01}],
            },
        }
    )
    resolved_request = _resolved_benchmark_request()
    register_sync = mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATELESS,
            source_details={"benchmark_return_points": 1},
            input_count=1,
        ),
    )
    update_execution_identity = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.execution_registry.update_execution_identity"
    )
    calculate_response = mocker.patch(
        "app.services.benchmark_calculation_workflow_service.calculate_benchmark_response",
        return_value={"ok": True},
    )

    response = await benchmark_calculation_workflow_service._calculate_initial_sync_benchmark_workflow(
        request=request,
        settings=SimpleNamespace(APP_VERSION="runtime-version"),
        source_request_fingerprint="source-fingerprint",
        source_request_hash="source-hash",
    )

    assert response == {"ok": True}
    assert register_sync.call_args.kwargs["input_fingerprint"] == "source-fingerprint"
    assert register_sync.call_args.kwargs["calculation_hash"] == "source-hash"
    update_execution_identity.assert_not_called()
    assert calculate_response.call_args.kwargs["input_fingerprint"] == "source-fingerprint"
    assert calculate_response.call_args.kwargs["calculation_hash"] == "source-hash"


@pytest.mark.asyncio
async def test_benchmark_endpoint_maps_stateful_resolution_errors_to_http_500(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        side_effect=RuntimeError("benchmark resolver blew up"),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(APIError) as exc_info:
        await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert exc_info.value.status_code == 500
    assert "benchmark resolver blew up" in str(exc_info.value.detail)
    assert "benchmark resolver blew up" in str(failure_capture["message"])


@pytest.mark.asyncio
async def test_benchmark_endpoint_reraises_sync_http_exceptions(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                ],
            },
        }
    )
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        side_effect=HTTPException(status_code=422, detail="bad sync benchmark request"),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "bad sync benchmark request"
    assert failure_capture["message"] == "bad sync benchmark request"


@pytest.mark.asyncio
async def test_benchmark_endpoint_maps_sync_resolution_errors_to_http_500(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "benchmark_id": "BMK_VENDOR",
            "benchmark_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "return_source": "vendor_series",
            "stateless_input": {
                "benchmark_currency": "USD",
                "benchmark_return_points": [
                    {"perf_date": "2025-01-01", "benchmark_return": 0.01},
                ],
            },
        }
    )
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "BENCHMARK_EXECUTOR_WINDOW_DAYS": 30,
                "BENCHMARK_EXECUTOR_INPUT_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.benchmark_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.resolve_benchmark_request",
        side_effect=RuntimeError("sync benchmark resolver blew up"),
    )
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(APIError) as exc_info:
        await benchmark_calculation_workflow_service.calculate_benchmark_workflow(request)

    assert exc_info.value.status_code == 500
    assert "sync benchmark resolver blew up" in str(exc_info.value.detail)
    assert "sync benchmark resolver blew up" in str(failure_capture["message"])


@pytest.mark.asyncio
async def test_get_benchmark_result_delegates_to_async_result_service(mocker):
    calculation_id = uuid4()
    expected_response = {"status": "ok"}
    request = SimpleNamespace(headers={"x-portfolio-id": "P1"})
    resolve_async_result = mocker.patch(
        "app.api.endpoints.benchmark.resolve_async_result",
        return_value=expected_response,
    )

    response = await benchmark_endpoint.get_benchmark_result(calculation_id, request)

    assert response == expected_response
    resolve_async_result.assert_called_once()
    assert resolve_async_result.call_args.kwargs["request_headers"] is request.headers


def test_benchmark_endpoint_helpers_cover_missing_stateless_input_and_sync_async_thresholds(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    mocker.patch(
        "app.services.benchmark_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"BENCHMARK_EXECUTOR_WINDOW_DAYS": 1, "BENCHMARK_EXECUTOR_INPUT_COUNT": 2},
        )(),
    )

    assert benchmark_calculation_workflow_service.should_preemptively_offload_stateful_benchmark(request) is True
    assert benchmark_calculation_workflow_service.should_offload_benchmark(request) is True
    assert (
        benchmark_calculation_workflow_service.should_persist_resolved_benchmark_request(
            SimpleNamespace(input_mode=BenchmarkInputMode.STATELESS, stateless_input=None)
        )
        is False
    )
