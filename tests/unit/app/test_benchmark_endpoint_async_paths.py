from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.endpoints import benchmark as benchmark_endpoint
from app.models.benchmark_analytics_requests import BenchmarkAnalyticsRequest, BenchmarkInputMode
from app.models.benchmark_requests import BenchmarkPerformanceRequest
from app.services.benchmark_mode_service import ResolvedBenchmarkRequest


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
async def test_benchmark_endpoint_replays_promoted_stateful_async_execution(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    replay_response = benchmark_endpoint._accepted_response(request.calculation_id)
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
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
        "app.api.endpoints.benchmark.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    register_sync = mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")

    response = await benchmark_endpoint.calculate_benchmark_endpoint(request)

    assert response == replay_response
    register_sync.assert_not_called()


@pytest.mark.asyncio
async def test_benchmark_endpoint_returns_accepted_response_when_resolved_stateful_request_is_offloaded(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    resolved_request = _resolved_benchmark_request()
    accepted_response = benchmark_endpoint._accepted_response(request.calculation_id)
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
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
        "app.api.endpoints.benchmark.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATEFUL,
            source_details={"component_observations": 2},
            input_count=2,
        ),
    )
    mocker.patch(
        "app.api.endpoints.benchmark.finalize_resolved_stateful_execution",
        return_value=accepted_response,
    )
    calculate_benchmark = mocker.patch("app.api.endpoints.benchmark.calculate_benchmark_response")

    response = await benchmark_endpoint.calculate_benchmark_endpoint(request)

    assert response == accepted_response
    calculate_benchmark.assert_not_called()


@pytest.mark.asyncio
async def test_benchmark_endpoint_executes_resolved_stateful_request_when_finalize_keeps_it_sync(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    resolved_request = _resolved_benchmark_request()
    expected_response = {"ok": True}
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
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
        "app.api.endpoints.benchmark.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATEFUL,
            source_details={"component_observations": 1},
            input_count=1,
        ),
    )
    mocker.patch(
        "app.api.endpoints.benchmark.finalize_resolved_stateful_execution",
        return_value=None,
    )
    calculate_benchmark = mocker.patch(
        "app.api.endpoints.benchmark.calculate_benchmark_response",
        return_value=expected_response,
    )

    response = await benchmark_endpoint.calculate_benchmark_endpoint(request)

    assert response == expected_response
    calculate_benchmark.assert_called_once()


@pytest.mark.asyncio
async def test_benchmark_endpoint_reraises_stateful_http_exceptions(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
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
        "app.api.endpoints.benchmark.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        side_effect=HTTPException(status_code=422, detail="bad benchmark request"),
    )
    mocker.patch(
        "app.api.endpoints.benchmark.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmark_endpoint.calculate_benchmark_endpoint(request)

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
        "app.api.endpoints.benchmark.get_settings",
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
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        return_value=ResolvedBenchmarkRequest(
            benchmark_request=resolved_request,
            input_mode=BenchmarkInputMode.STATELESS,
            source_details={"component_observations": 1},
            input_count=1,
        ),
    )
    update_execution_identity = mocker.patch("app.api.endpoints.benchmark.execution_registry.update_execution_identity")
    mocker.patch(
        "app.api.endpoints.benchmark.calculate_benchmark_response",
        return_value=expected_response,
    )

    response = await benchmark_endpoint.calculate_benchmark_endpoint(request)

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
    accepted_response = benchmark_endpoint._accepted_response(request.calculation_id)
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
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
        "app.api.endpoints.benchmark.register_async_submission_or_raise",
        return_value=accepted_response,
    )

    response = await benchmark_endpoint.calculate_benchmark_endpoint(request)

    assert response == accepted_response
    register_async.assert_called_once()


@pytest.mark.asyncio
async def test_benchmark_endpoint_maps_stateful_resolution_errors_to_http_500(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
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
        "app.api.endpoints.benchmark.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        side_effect=RuntimeError("benchmark resolver blew up"),
    )
    mocker.patch(
        "app.api.endpoints.benchmark.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmark_endpoint.calculate_benchmark_endpoint(request)

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
        "app.api.endpoints.benchmark.get_settings",
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
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        side_effect=HTTPException(status_code=422, detail="bad sync benchmark request"),
    )
    mocker.patch(
        "app.api.endpoints.benchmark.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmark_endpoint.calculate_benchmark_endpoint(request)

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
        "app.api.endpoints.benchmark.get_settings",
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
    mocker.patch("app.api.endpoints.benchmark.register_sync_execution_or_raise")
    mocker.patch(
        "app.api.endpoints.benchmark.resolve_benchmark_request",
        side_effect=RuntimeError("sync benchmark resolver blew up"),
    )
    mocker.patch(
        "app.api.endpoints.benchmark.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await benchmark_endpoint.calculate_benchmark_endpoint(request)

    assert exc_info.value.status_code == 500
    assert "sync benchmark resolver blew up" in str(exc_info.value.detail)
    assert "sync benchmark resolver blew up" in str(failure_capture["message"])


@pytest.mark.asyncio
async def test_get_benchmark_result_delegates_to_async_result_service(mocker):
    calculation_id = uuid4()
    expected_response = {"status": "ok"}
    resolve_async_result = mocker.patch(
        "app.api.endpoints.benchmark.resolve_async_result",
        return_value=expected_response,
    )

    response = await benchmark_endpoint.get_benchmark_result(calculation_id)

    assert response == expected_response
    resolve_async_result.assert_called_once()


def test_benchmark_endpoint_helpers_cover_missing_stateless_input_and_sync_async_thresholds(mocker):
    request = BenchmarkAnalyticsRequest.model_validate(_stateful_benchmark_payload())
    mocker.patch(
        "app.api.endpoints.benchmark.get_settings",
        return_value=type(
            "Settings",
            (),
            {"BENCHMARK_EXECUTOR_WINDOW_DAYS": 1, "BENCHMARK_EXECUTOR_INPUT_COUNT": 2},
        )(),
    )

    assert benchmark_endpoint._should_preemptively_offload_stateful_benchmark(request) is True
    assert benchmark_endpoint._should_offload_benchmark(request) is True
    assert benchmark_endpoint._should_persist_resolved_benchmark_request(
        SimpleNamespace(input_mode=BenchmarkInputMode.STATELESS, stateless_input=None)
    ) is False
