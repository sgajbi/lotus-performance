from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.endpoints import contribution as contribution_endpoint
from app.models.contribution_analytics_requests import ContributionAnalyticsRequest, ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.services import contribution_calculation_workflow_service
from app.services.contribution_mode_service import ResolvedContributionRequest


def _stateful_contribution_payload() -> dict[str, object]:
    return {
        "calculation_id": str(uuid4()),
        "portfolio_id": "P1",
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
        "input_mode": "stateful",
        "stateful_input": {},
    }


def _stateless_contribution_request() -> ContributionRequest:
    return ContributionRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "portfolio_data": {
                "metric_basis": "NET",
                "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
            },
            "positions_data": [{"position_id": "A", "valuation_points": []}],
        }
    )


@pytest.mark.asyncio
async def test_contribution_endpoint_replays_promoted_stateful_async_execution(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    replay_response = contribution_calculation_workflow_service.accepted_contribution_response(request.calculation_id)
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    register_sync = mocker.patch(
        "app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise"
    )

    response = await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert response == replay_response
    register_sync.assert_not_called()


@pytest.mark.asyncio
async def test_promoted_stateful_contribution_helper_returns_replay_without_registering(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    replay_response = contribution_calculation_workflow_service.accepted_contribution_response(request.calculation_id)
    replay_promoted = mocker.patch(
        "app.services.contribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    register_sync = mocker.patch(
        "app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise"
    )

    response = await contribution_calculation_workflow_service._calculate_promoted_stateful_contribution(
        request=request,
        active_settings=SimpleNamespace(APP_VERSION="runtime-version"),
        input_fingerprint="source-fingerprint",
        calculation_hash="source-hash",
    )

    assert response == replay_response
    replay_promoted.assert_called_once()
    register_sync.assert_not_called()


@pytest.mark.asyncio
async def test_contribution_endpoint_returns_accepted_response_when_resolved_stateful_request_is_offloaded(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    resolved_request = _stateless_contribution_request()
    accepted_response = contribution_calculation_workflow_service.accepted_contribution_response(request.calculation_id)
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 2,
            },
        )(),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        return_value=ResolvedContributionRequest(
            contribution_request=resolved_request,
            input_mode=ContributionInputMode.STATEFUL,
            position_count=2,
        ),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.finalize_resolved_stateful_execution",
        return_value=accepted_response,
    )
    calculate_contribution = mocker.patch(
        "app.services.contribution_calculation_workflow_service.calculate_contribution"
    )

    response = await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert response == accepted_response
    calculate_contribution.assert_not_called()


@pytest.mark.asyncio
async def test_contribution_endpoint_executes_resolved_stateful_request_when_finalize_keeps_it_sync(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    resolved_request = _stateless_contribution_request()
    expected_response = {"ok": True}
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        return_value=ResolvedContributionRequest(
            contribution_request=resolved_request,
            input_mode=ContributionInputMode.STATEFUL,
            position_count=1,
        ),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.finalize_resolved_stateful_execution",
        return_value=None,
    )
    calculate_contribution = mocker.patch(
        "app.services.contribution_calculation_workflow_service.calculate_contribution",
        return_value=expected_response,
    )

    response = await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert response == expected_response
    calculate_contribution.assert_called_once()


@pytest.mark.asyncio
async def test_contribution_endpoint_reraises_stateful_http_exceptions(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        side_effect=HTTPException(status_code=422, detail="bad stateful request"),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "bad stateful request"
    assert failure_capture["message"] == "bad stateful request"


@pytest.mark.asyncio
async def test_contribution_endpoint_maps_stateful_resolution_errors_to_http_500(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=None,
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        side_effect=RuntimeError("resolver blew up"),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert exc_info.value.status_code == 500
    assert "resolver blew up" in str(exc_info.value.detail)
    assert "resolver blew up" in str(failure_capture["message"])


@pytest.mark.asyncio
async def test_contribution_endpoint_offloads_large_sync_requests(mocker):
    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
                "positions_data": [
                    {"position_id": "A", "valuation_points": []},
                    {"position_id": "B", "valuation_points": []},
                ],
            },
        }
    )
    accepted_response = contribution_calculation_workflow_service.accepted_contribution_response(request.calculation_id)
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 2,
            },
        )(),
    )
    register_async = mocker.patch(
        "app.services.contribution_calculation_workflow_service.register_async_submission_or_raise",
        return_value=accepted_response,
    )

    response = await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert response == accepted_response
    register_async.assert_called_once()


@pytest.mark.asyncio
async def test_contribution_endpoint_maps_sync_resolution_errors_to_http_500(mocker):
    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
                "positions_data": [{"position_id": "A", "valuation_points": []}],
            },
        }
    )
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        side_effect=RuntimeError("sync resolver blew up"),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert exc_info.value.status_code == 500
    assert "sync resolver blew up" in str(exc_info.value.detail)
    assert "sync resolver blew up" in str(failure_capture["message"])


@pytest.mark.asyncio
async def test_contribution_endpoint_executes_sync_resolved_request_when_not_offloaded(mocker):
    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
                "positions_data": [{"position_id": "A", "valuation_points": []}],
            },
        }
    )
    expected_response = {"sync": True}
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        return_value=ResolvedContributionRequest(
            contribution_request=_stateless_contribution_request(),
            input_mode=ContributionInputMode.STATELESS,
            position_count=1,
        ),
    )
    calculate_contribution = mocker.patch(
        "app.services.contribution_calculation_workflow_service.calculate_contribution",
        return_value=expected_response,
    )

    response = await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert response == expected_response
    calculate_contribution.assert_called_once()


@pytest.mark.asyncio
async def test_contribution_endpoint_reraises_sync_http_exceptions(mocker):
    request = ContributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "P1",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-02",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_data": {
                    "metric_basis": "NET",
                    "valuation_points": [{"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010}],
                },
                "positions_data": [{"position_id": "A", "valuation_points": []}],
            },
        }
    )
    failure_capture: dict[str, object] = {}
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {
                "APP_VERSION": "runtime-version",
                "CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 30,
                "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 50,
            },
        )(),
    )
    mocker.patch("app.services.contribution_calculation_workflow_service.register_sync_execution_or_raise")
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.resolve_contribution_request",
        side_effect=HTTPException(status_code=422, detail="bad sync request"),
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.record_execution_failure",
        side_effect=lambda **kwargs: failure_capture.update(kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        await contribution_calculation_workflow_service.calculate_contribution_workflow(request)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "bad sync request"
    assert failure_capture["message"] == "bad sync request"


@pytest.mark.asyncio
async def test_get_contribution_result_delegates_to_async_result_service(mocker):
    calculation_id = uuid4()
    expected_response = {"status": "ok"}
    resolve_async_result = mocker.patch(
        "app.api.endpoints.contribution.resolve_async_result",
        return_value=expected_response,
    )

    response = await contribution_endpoint.get_contribution_result(calculation_id)

    assert response == expected_response
    resolve_async_result.assert_called_once()


def test_contribution_endpoint_numeric_and_stateful_window_helpers_cover_stateful_shape(mocker):
    request = ContributionAnalyticsRequest.model_validate(_stateful_contribution_payload())
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type("Settings", (), {"CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 1})(),
    )

    assert contribution_endpoint._as_numeric("4.5") == 4.5
    assert contribution_calculation_workflow_service.should_offload_contribution(request) is True
    assert contribution_calculation_workflow_service.build_contribution_execution_window(
        request,
        source_request_fingerprint="fp",
    ) == {
        "report_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "requested_periods": ["ITD"],
        "position_count": 0,
        "hierarchical": False,
        "input_mode": "stateful",
        "source_request_fingerprint": "fp",
    }

    stateless_request = SimpleNamespace(
        input_mode=ContributionInputMode.STATELESS,
        stateless_input=None,
        positions_data=[SimpleNamespace(), SimpleNamespace()],
    )
    mocker.patch(
        "app.services.contribution_calculation_workflow_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"CONTRIBUTION_EXECUTOR_WINDOW_DAYS": 1, "CONTRIBUTION_EXECUTOR_POSITION_COUNT": 2},
        )(),
    )
    assert contribution_calculation_workflow_service.should_offload_contribution(stateless_request) is True
    legacy_request = _stateless_contribution_request()
    assert (
        contribution_calculation_workflow_service.build_contribution_execution_window(legacy_request)["position_count"]
        == 1
    )
