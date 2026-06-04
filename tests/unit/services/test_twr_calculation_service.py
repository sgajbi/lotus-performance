from uuid import uuid4

import pytest

from app.models.twr_requests import TWRAnalyticsRequest
from app.services import twr_calculation_service
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
