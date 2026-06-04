from datetime import date
from unittest.mock import ANY
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.models.mwr_requests import CashFlow, MoneyWeightedReturnRequest
from app.services.analytics_workflow_types import ANALYTICS_WORKFLOW_MWR
from app.services.mwr_calculation_service import (
    build_mwr_response,
    calculate_mwr_response,
    calculate_mwr_result,
)
from app.services.mwr_mode_service import ResolvedMWRRequest
from engine.mwr import calculate_money_weighted_return


def test_calculate_mwr_result_matches_engine_result():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "MWR-SERVICE",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [
                {"amount": 10000.0, "date": "2025-03-15"},
                {"amount": -5000.0, "date": "2025-09-20"},
            ],
            "mwr_method": "DIETZ",
        }
    )

    service_result = calculate_mwr_result(request)
    engine_result = calculate_money_weighted_return(
        begin_mv=request.begin_mv,
        end_mv=request.end_mv,
        cash_flows=request.cash_flows,
        calculation_method=request.mwr_method,
        annualization=request.annualization,
        as_of=request.as_of,
        start_date=request.start_date,
        solver=request.solver,
    )

    assert service_result.mwr == pytest.approx(engine_result.mwr)
    assert service_result.method == engine_result.method
    assert service_result.start_date == engine_result.start_date
    assert service_result.end_date == engine_result.end_date


def test_calculate_mwr_result_passes_request_cashflows():
    request = MoneyWeightedReturnRequest.model_validate(
        {
            "portfolio_id": "MWR-SERVICE-CASHFLOWS",
            "begin_mv": 100.0,
            "end_mv": 130.0,
            "as_of": "2025-12-31",
            "cash_flows": [{"amount": 10.0, "date": "2025-06-30"}],
            "mwr_method": "MODIFIED_DIETZ",
        }
    )

    result = calculate_mwr_result(request)

    assert request.cash_flows == [CashFlow(amount=10.0, date=date(2025, 6, 30))]
    assert result.method == "MODIFIED_DIETZ"


def test_build_mwr_response_preserves_endpoint_payload_contract(mocker):
    analytics_request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "portfolio_id": "MWR-SERVICE-RESPONSE",
            "begin_mv": 100.0,
            "end_mv": 130.0,
            "as_of": "2025-12-31",
            "cash_flows": [{"amount": 10.0, "date": "2025-06-30"}],
            "mwr_method": "DIETZ",
            "currency": "USD",
            "report_ccy": "CHF",
        }
    )
    mwr_request = analytics_request.to_stateless_mwr_request()
    resolved_request = ResolvedMWRRequest(
        mwr_request=mwr_request,
        input_mode=MWRInputMode.STATELESS,
        currency_evidence=None,
    )
    mwr_result = calculate_mwr_result(mwr_request)
    supportability_metric = mocker.patch("app.services.mwr_calculation_service.record_supportability_metric")
    solver_metric = mocker.patch("app.services.mwr_calculation_service.record_mwr_solver_outcome")

    response = build_mwr_response(
        request=analytics_request,
        resolved_request=resolved_request,
        mwr_result=mwr_result,
        input_fingerprint="input-fingerprint",
        calculation_hash="calculation-hash",
        engine_version="test-version",
    )

    assert response.portfolio_id == "MWR-SERVICE-RESPONSE"
    assert response.reporting_currency == "CHF"
    assert response.cashflows_used == [CashFlow(amount=10.0, date=date(2025, 6, 30))]
    assert response.meta.engine_version == "test-version"
    assert response.meta.input_fingerprint == "input-fingerprint"
    assert response.meta.calculation_hash == "calculation-hash"
    assert response.diagnostics.effective_period_start == mwr_result.start_date
    assert response.audit.counts == {"cashflows": 1}
    assert response.calculation_supportability.resolved_period_count == 1
    supportability_metric.assert_called_once()
    solver_metric.assert_called_once()


@pytest.mark.asyncio
async def test_calculate_mwr_response_executes_stateless_request_and_records_lineage(mocker):
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORTFOLIO-UNIT",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [
                {"amount": 10000.0, "date": "2025-03-15"},
                {"amount": -5000.0, "date": "2025-09-20"},
            ],
            "mwr_method": "XIRR",
            "annualization": {"enabled": False},
        }
    )
    resolved_request = ResolvedMWRRequest(
        mwr_request=request.to_stateless_mwr_request(),
        input_mode=MWRInputMode.STATELESS,
        currency_evidence=None,
    )
    assert request.input_mode == MWRInputMode.STATELESS

    mocker.patch(
        "app.services.mwr_calculation_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "perf-version"},
        )(),
    )

    async def resolve_request(*_, **__) -> ResolvedMWRRequest:
        return resolved_request

    async_resolve = mocker.patch(
        "app.services.mwr_calculation_service.resolve_mwr_request",
        side_effect=resolve_request,
    )
    mocker.patch(
        "app.services.mwr_calculation_service.generate_request_fingerprint",
        return_value=("fingerprint-raw", "hash-raw"),
    )
    register_sync = mocker.patch("app.services.mwr_calculation_service.register_sync_execution_or_raise")
    mocker.patch("app.services.mwr_calculation_service.execution_registry.mark_running")
    mark_stage = mocker.patch("app.services.mwr_calculation_service.execution_registry.start_stage")
    mocker.patch("app.services.mwr_calculation_service.execution_registry.update_execution_identity")
    complete_lineage = mocker.patch(
        "app.services.mwr_calculation_service.complete_execution_with_lineage",
        side_effect=lambda **kwargs: None,
    )

    response = await calculate_mwr_response(request)

    async_resolve.assert_awaited_once_with(request, settings=ANY)
    register_sync.assert_called_once_with(
        calculation_id=request.calculation_id,
        analytics_type=ANALYTICS_WORKFLOW_MWR,
        portfolio_id=request.portfolio_id,
        requested_window={
            "as_of": "2025-12-31",
            "start_date": None,
        },
        input_fingerprint="fingerprint-raw",
        calculation_hash="hash-raw",
    )
    mark_stage.assert_called_once_with(request.calculation_id, "execution")
    complete_lineage.assert_called_once()
    call_kwargs = complete_lineage.call_args.kwargs
    assert call_kwargs["calculation_type"] == ANALYTICS_WORKFLOW_MWR
    assert call_kwargs["request_model"] == request
    assert call_kwargs["execution_details"] == {"cashflows": 2}
    assert response.meta.input_fingerprint == "fingerprint-raw"
    assert response.meta.calculation_hash == "hash-raw"


@pytest.mark.asyncio
async def test_calculate_mwr_response_updates_identity_for_stateful_resolved_request(mocker):
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORTFOLIO-STATEFUL",
            "as_of": "2025-12-31",
            "stateful_input": {
                "window_start_date": "2025-01-01",
            },
            "mwr_method": "DIETZ",
            "input_mode": "stateful",
        }
    )
    resolved_request = ResolvedMWRRequest(
        mwr_request=request.to_stateless_mwr_request(
            begin_mv=1000.0,
            end_mv=1300.0,
            cash_flows=[
                CashFlow(amount=100.0, date=date(2025, 4, 1)),
            ],
        ),
        input_mode=MWRInputMode.STATEFUL,
        currency_evidence=None,
    )
    mocker.patch(
        "app.services.mwr_calculation_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "stateful-version"},
        )(),
    )

    async def resolve_request(*_, **__) -> ResolvedMWRRequest:
        return resolved_request

    mocker.patch(
        "app.services.mwr_calculation_service.resolve_mwr_request",
        side_effect=resolve_request,
    )
    mocker.patch(
        "app.services.mwr_calculation_service.register_sync_execution_or_raise",
        side_effect=lambda **kwargs: None,
    )
    fingerprint_sequence = iter([("request-fp", "request-hash"), ("stateful-fp", "stateful-hash")])
    mocker.patch(
        "app.services.mwr_calculation_service.generate_request_fingerprint",
        side_effect=lambda *_: next(fingerprint_sequence),
    )
    mocker.patch("app.services.mwr_calculation_service.execution_registry.mark_running")
    mocked_update_identity = mocker.patch(
        "app.services.mwr_calculation_service.execution_registry.update_execution_identity"
    )
    mocked_start_stage = mocker.patch("app.services.mwr_calculation_service.execution_registry.start_stage")
    mocker.patch(
        "app.services.mwr_calculation_service.complete_execution_with_lineage",
        side_effect=lambda **_: None,
    )

    await calculate_mwr_response(request)

    assert mocked_update_identity.call_count == 1
    assert mocked_update_identity.call_args.kwargs["input_fingerprint"] == "stateful-fp"
    assert mocked_update_identity.call_args.kwargs["calculation_hash"] == "stateful-hash"
    mocked_start_stage.assert_called_once_with(request.calculation_id, "execution")


@pytest.mark.asyncio
async def test_calculate_mwr_response_preserves_http_exceptions(mocker):
    async def _raise_http_exception(*_: object, **__: object) -> ResolvedMWRRequest:
        raise HTTPException(status_code=422, detail="bad mwr payload")

    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORTFOLIO-UNIT",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [
                {"amount": 10000.0, "date": "2025-03-15"},
            ],
            "mwr_method": "XIRR",
        }
    )
    mocker.patch(
        "app.services.mwr_calculation_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "perf-version"},
        )(),
    )
    mocker.patch(
        "app.services.mwr_calculation_service.resolve_mwr_request",
        side_effect=_raise_http_exception,
    )
    mocker.patch(
        "app.services.mwr_calculation_service.register_sync_execution_or_raise",
        side_effect=lambda **_: None,
    )
    mocker.patch("app.services.mwr_calculation_service.execution_registry.mark_running")
    capture: dict[str, str] = {}
    mocker.patch(
        "app.services.mwr_calculation_service.record_execution_failure",
        side_effect=lambda **kwargs: capture.update({"message": str(kwargs["message"])}),
    )

    with pytest.raises(HTTPException) as exc:
        await calculate_mwr_response(request)

    assert exc.value.status_code == 422
    assert capture["message"] == "HTTPException raised during MWR execution."


@pytest.mark.asyncio
async def test_calculate_mwr_response_maps_unexpected_errors_to_http_500(mocker):
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "PORTFOLIO-UNIT",
            "begin_mv": 100000.0,
            "end_mv": 115000.0,
            "as_of": "2025-12-31",
            "cash_flows": [
                {"amount": 10000.0, "date": "2025-03-15"},
            ],
            "mwr_method": "XIRR",
        }
    )
    resolved_request = ResolvedMWRRequest(
        mwr_request=request.to_stateless_mwr_request(),
        input_mode=MWRInputMode.STATELESS,
        currency_evidence=None,
    )

    async def resolve_request(*_, **__) -> ResolvedMWRRequest:
        return resolved_request

    mocker.patch(
        "app.services.mwr_calculation_service.get_settings",
        return_value=type(
            "Settings",
            (),
            {"APP_VERSION": "perf-version"},
        )(),
    )
    mocker.patch(
        "app.services.mwr_calculation_service.resolve_mwr_request",
        side_effect=resolve_request,
    )
    mocker.patch(
        "app.services.mwr_calculation_service.calculate_mwr_result",
        side_effect=RuntimeError("engine failure"),
    )
    mocker.patch(
        "app.services.mwr_calculation_service.register_sync_execution_or_raise",
        side_effect=lambda **_: None,
    )
    mocker.patch("app.services.mwr_calculation_service.execution_registry.mark_running")
    mocker.patch("app.services.mwr_calculation_service.execution_registry.start_stage")
    capture: dict[str, str] = {}
    mocker.patch(
        "app.services.mwr_calculation_service.record_execution_failure",
        side_effect=lambda **kwargs: capture.update({"message": str(kwargs["message"])}),
    )

    with pytest.raises(HTTPException) as exc:
        await calculate_mwr_response(request)

    assert exc.value.status_code == 500
    assert "An unexpected error occurred during MWR calculation" in str(exc.value.detail)
    assert capture["message"].startswith("An unexpected error occurred during MWR calculation")
