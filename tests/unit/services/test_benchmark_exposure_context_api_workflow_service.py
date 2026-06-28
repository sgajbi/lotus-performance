from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_exposure_context import BenchmarkExposureContextRequest
from app.services import benchmark_exposure_context_workflow_service as workflow_service
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_BENCHMARK_EXPOSURE_CONTEXT
from app.services.execution_stage_names import EXECUTION_STAGE_EXECUTION


def _request() -> BenchmarkExposureContextRequest:
    return BenchmarkExposureContextRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "as_of_date": "2026-03-31",
            "window": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
            "frequency": "DAILY",
            "reporting_currency": "USD",
            "grouping_dimensions": ["SECTOR"],
        }
    )


@pytest.mark.asyncio
async def test_benchmark_exposure_context_workflow_registers_and_completes_execution(mocker) -> None:
    request = _request()
    stateful_input_service = object()
    expected_response = mocker.Mock(rows=[{"group_key": "SECTOR_TECH"}])

    mocker.patch("app.services.benchmark_exposure_context_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        return_value=stateful_input_service,
    )
    register_sync = mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.register_sync_execution_or_raise"
    )
    mark_running = mocker.patch.object(workflow_service.execution_registry, "mark_running")
    start_stage = mocker.patch.object(workflow_service.execution_registry, "start_stage")
    complete_stage = mocker.patch.object(workflow_service.execution_registry, "complete_stage")
    mark_complete = mocker.patch.object(workflow_service.execution_registry, "mark_complete")
    record_failure = mocker.patch("app.services.benchmark_exposure_context_workflow_service.record_execution_failure")
    builder = mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.build_benchmark_exposure_context",
        return_value=expected_response,
    )

    response = await workflow_service.calculate_benchmark_exposure_context_response(request)

    assert response is expected_response
    register_sync.assert_called_once_with(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_BENCHMARK_EXPOSURE_CONTEXT,
        portfolio_id=request.portfolio_id,
        requested_window={
            "as_of_date": "2026-03-31",
            "window_start_date": "2026-01-01",
            "window_end_date": "2026-03-31",
            "frequency": "DAILY",
            "grouping_dimensions": ["SECTOR"],
            "benchmark_id": None,
            "reporting_currency": "USD",
        },
        input_fingerprint=None,
        calculation_hash=None,
    )
    mark_running.assert_called_once_with(request.calculation_id)
    start_stage.assert_called_once_with(request.calculation_id, EXECUTION_STAGE_EXECUTION)
    builder.assert_awaited_once_with(request=request, stateful_input_service=stateful_input_service)
    complete_stage.assert_called_once_with(request.calculation_id, EXECUTION_STAGE_EXECUTION, details={"row_count": 1})
    mark_complete.assert_called_once_with(request.calculation_id)
    record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_benchmark_exposure_context_workflow_records_http_failures(mocker) -> None:
    request = _request()

    mocker.patch("app.services.benchmark_exposure_context_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        return_value=object(),
    )
    mocker.patch("app.services.benchmark_exposure_context_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    mocker.patch.object(workflow_service.execution_registry, "start_stage")
    record_failure = mocker.patch("app.services.benchmark_exposure_context_workflow_service.record_execution_failure")
    mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.build_benchmark_exposure_context",
        side_effect=HTTPException(status_code=503, detail="benchmark market-series source unavailable (503)."),
    )

    with pytest.raises(HTTPException) as exc_info:
        await workflow_service.calculate_benchmark_exposure_context_response(request)

    assert exc_info.value.status_code == 503
    record_failure.assert_called_once_with(
        calculation_id=request.calculation_id,
        message="benchmark market-series source unavailable (503).",
        execution_stage_started=True,
    )


@pytest.mark.asyncio
async def test_benchmark_exposure_context_workflow_wraps_unexpected_failures(mocker) -> None:
    request = _request()

    mocker.patch("app.services.benchmark_exposure_context_workflow_service.get_settings", return_value=object())
    mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.build_stateful_input_service",
        return_value=object(),
    )
    mocker.patch("app.services.benchmark_exposure_context_workflow_service.register_sync_execution_or_raise")
    mocker.patch.object(workflow_service.execution_registry, "mark_running")
    mocker.patch.object(workflow_service.execution_registry, "start_stage")
    record_failure = mocker.patch("app.services.benchmark_exposure_context_workflow_service.record_execution_failure")
    mocker.patch(
        "app.services.benchmark_exposure_context_workflow_service.build_benchmark_exposure_context",
        side_effect=RuntimeError("boom"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await workflow_service.calculate_benchmark_exposure_context_response(request)

    assert exc_info.value.status_code == 500
    assert "unexpected server error occurred while building benchmark exposure context: boom" in exc_info.value.detail
    record_failure.assert_called_once_with(
        calculation_id=request.calculation_id,
        message="An unexpected server error occurred while building benchmark exposure context: boom",
        execution_stage_started=True,
    )
