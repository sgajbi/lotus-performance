from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from fastapi import HTTPException

from app.models.returns_series import (
    CalendarPolicy,
    DataPolicy,
    InputMode,
    MetricBasis,
    ResolvedWindow,
    ReturnPoint,
    ReturnsFrequency,
    ReturnsRelativePeriod,
    ReturnsSeriesRequest,
    ReturnsWindow,
    ReturnsWindowMode,
    SeriesSelection,
    StatefulInput,
    StatelessInput,
)
from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services import returns_series_calculation_workflow_service
from app.services.execution_registry import execution_registry
from app.services.returns_series_calculation_workflow_service import (
    _execution_failure_message,
    build_returns_series_execution_window,
    calculate_returns_series_workflow,
    should_offload_resolved_returns_series,
    should_offload_returns_series,
)
from app.services.returns_series_service import (
    ResolvedStatefulReturnsSeriesRequest,
    core_points_to_dataframe,
    date_range_count,
    detect_gaps,
    filter_window,
    period_start,
    points_from_df,
    portfolio_timeseries_to_valuation_points,
    resample_returns,
    resolve_window,
    to_dataframe,
)


@pytest.fixture(autouse=True)
def _reset_execution_registry() -> None:
    execution_registry.create_schema()
    execution_registry.clear_all_records()


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (ReturnsRelativePeriod.MTD, date(2026, 2, 1)),
        (ReturnsRelativePeriod.QTD, date(2026, 1, 1)),
        (ReturnsRelativePeriod.YTD, date(2026, 1, 1)),
        (ReturnsRelativePeriod.ONE_YEAR, date(2025, 2, 28)),
        (ReturnsRelativePeriod.THREE_YEAR, date(2023, 2, 28)),
        (ReturnsRelativePeriod.FIVE_YEAR, date(2021, 2, 28)),
        (ReturnsRelativePeriod.SI, date(1900, 1, 1)),
    ],
)
def test_period_start_relative_periods(period: ReturnsRelativePeriod, expected: date):
    assert period_start(date(2026, 2, 27), period, None) == expected


def test_period_start_year_requires_year_and_accepts_valid_year():
    with pytest.raises(ValueError, match="year is required when period=YEAR"):
        period_start(date(2026, 2, 27), ReturnsRelativePeriod.YEAR, None)

    assert period_start(date(2026, 2, 27), ReturnsRelativePeriod.YEAR, 2024) == date(2024, 1, 1)


def test_period_start_rejects_unsupported_period_value():
    with pytest.raises(ValueError, match="Unsupported period"):
        period_start(date(2026, 2, 27), "UNKNOWN", None)  # type: ignore[arg-type]


def test_resolve_window_relative_success_and_missing_period_error():
    valid_request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-27",
            "window": {"mode": "RELATIVE", "period": "MTD"},
            "input_mode": "stateless",
            "stateless_input": {
                "portfolio_returns": [{"date": "2026-02-27", "return_value": "0.0010"}],
            },
        }
    )
    resolved = resolve_window(valid_request)
    assert resolved.start_date == date(2026, 2, 1)
    assert resolved.end_date == date(2026, 2, 27)
    assert resolved.resolved_period_label == "MTD"

    invalid_request = ReturnsSeriesRequest.model_construct(
        portfolio_id="P1",
        as_of_date=date(2026, 2, 27),
        window=ReturnsWindow.model_construct(mode=ReturnsWindowMode.RELATIVE, period=None, year=None),
        frequency=ReturnsFrequency.DAILY,
        metric_basis=MetricBasis.NET,
        reporting_currency=None,
        series_selection=SeriesSelection(),
        benchmark=None,
        risk_free=None,
        data_policy=DataPolicy(),
        input_mode=InputMode.STATELESS,
        stateless_input=StatelessInput.model_construct(portfolio_returns=[]),
        stateful_input=None,
    )
    with pytest.raises(HTTPException) as exc:
        resolve_window(invalid_request)
    assert exc.value.status_code == 400


def test_returns_window_normalizes_legacy_relative_period_aliases():
    window = ReturnsWindow.model_validate({"mode": "RELATIVE", "period": "THREE_YEAR"})

    assert window.period == ReturnsRelativePeriod.THREE_YEAR
    assert window.period.value == "3Y"

    since_inception = ReturnsWindow.model_validate({"mode": "RELATIVE", "period": "ITD"})
    assert since_inception.period == ReturnsRelativePeriod.SI


def test_dataframe_and_window_helpers_handle_error_paths():
    with pytest.raises(HTTPException) as exc:
        to_dataframe([], series_type="portfolio")
    assert exc.value.status_code == 422


def test_core_points_to_dataframe_skips_invalid_points_and_bad_values():
    with pytest.raises(HTTPException):
        core_points_to_dataframe(
            points=[
                {"series_date": None, "benchmark_return": "0.01"},
                {"series_date": "bad", "benchmark_return": "0.01"},
            ],
            date_key="series_date",
            value_key="benchmark_return",
            series_type="benchmark",
        )

    df = core_points_to_dataframe(
        points=[
            {"series_date": "2026-02-24", "benchmark_return": "0.01"},
            {"series_date": "2026-02-25", "benchmark_return": "0.02"},
        ],
        date_key="series_date",
        value_key="benchmark_return",
        series_type="benchmark",
    )
    assert list(df["date"].dt.date) == [date(2026, 2, 24), date(2026, 2, 25)]


def test_portfolio_timeseries_to_valuation_points_handles_cashflow_variants():
    points = portfolio_timeseries_to_valuation_points(
        observations=[
            {"valuation_date": "2026-02-24", "beginning_market_value": "100", "ending_market_value": "101"},
            {
                "valuation_date": "2026-02-25",
                "beginning_market_value": "101",
                "ending_market_value": "102",
                "cash_flows": [
                    {"amount": "1.2", "timing": "bod"},
                    {"amount": "0.3", "timing": "eod"},
                    {"amount": "-0.1", "timing": "eod", "cash_flow_type": "fee"},
                    {"amount": "999", "timing": "invalid"},
                    "not-a-dict",
                ],
            },
        ]
    )
    assert len(points) == 2
    assert points[1]["bod_cf"] == Decimal("1.2")
    assert points[1]["eod_cf"] == Decimal("0.3")
    assert points[1]["mgmt_fees"] == Decimal("-0.1")

    with pytest.raises(HTTPException):
        portfolio_timeseries_to_valuation_points(observations=[{"valuation_date": None}])

    with pytest.raises(HTTPException) as exc:
        to_dataframe(
            [
                ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.001")),
                ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.002")),
            ],
            series_type="portfolio",
        )
    assert exc.value.status_code == 400

    df = to_dataframe(
        [
            ReturnPoint(date=date(2026, 2, 25), return_value=Decimal("0.002")),
            ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.001")),
        ],
        series_type="portfolio",
    )
    assert list(df["date"].dt.date) == [date(2026, 2, 24), date(2026, 2, 25)]

    with pytest.raises(HTTPException) as exc:
        filter_window(
            df,
            resolved_window=ResolvedWindow(start_date=date(2026, 3, 1), end_date=date(2026, 3, 2)),
        )
    assert exc.value.status_code == 422


def test_resample_count_gap_and_point_helpers_cover_monthly_paths():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-30", "2026-01-31", "2026-02-28"]),
            "return_value": [Decimal("0.01"), Decimal("0.02"), Decimal("0.03")],
        }
    )
    monthly = resample_returns(df, frequency=ReturnsFrequency.MONTHLY)
    assert len(monthly) == 2

    resolved = ResolvedWindow(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))
    assert date_range_count(resolved, frequency=ReturnsFrequency.DAILY, calendar_policy=CalendarPolicy.CALENDAR) == 28
    assert date_range_count(resolved, frequency=ReturnsFrequency.WEEKLY, calendar_policy=CalendarPolicy.BUSINESS) == 4
    assert date_range_count(resolved, frequency=ReturnsFrequency.MONTHLY, calendar_policy=CalendarPolicy.BUSINESS) == 1

    tiny = pd.DataFrame({"date": pd.to_datetime(["2026-02-01"]), "return_value": [Decimal("0.01")]})
    assert detect_gaps(tiny, frequency=ReturnsFrequency.DAILY, series_type="portfolio") == []

    gappy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-01", "2026-02-10"]),
            "return_value": [Decimal("0.01"), Decimal("0.02")],
        }
    )
    gaps = detect_gaps(gappy, frequency=ReturnsFrequency.DAILY, series_type="portfolio")
    assert len(gaps) == 1
    assert gaps[0].gap_days == 8

    points = points_from_df(monthly)
    assert points[0].return_value.as_tuple().exponent == -12


@pytest.mark.asyncio
async def test_get_returns_series_guards_stateless_mode_without_input():
    request = ReturnsSeriesRequest.model_construct(
        portfolio_id="P1",
        as_of_date=date(2026, 2, 27),
        window=ReturnsWindow.model_construct(
            mode=ReturnsWindowMode.EXPLICIT,
            from_date=date(2026, 2, 24),
            to_date=date(2026, 2, 27),
        ),
        frequency=ReturnsFrequency.DAILY,
        metric_basis=MetricBasis.NET,
        reporting_currency=None,
        series_selection=SeriesSelection(),
        benchmark=None,
        risk_free=None,
        data_policy=DataPolicy(),
        input_mode=InputMode.STATELESS,
        stateless_input=None,
        stateful_input=StatefulInput.model_construct(),
    )
    with pytest.raises(HTTPException) as exc:
        await calculate_returns_series_workflow(request)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_get_returns_series_guards_stateful_mode_without_input():
    request = ReturnsSeriesRequest.model_construct(
        portfolio_id="P1",
        as_of_date=date(2026, 2, 27),
        window=ReturnsWindow.model_construct(
            mode=ReturnsWindowMode.EXPLICIT,
            from_date=date(2026, 2, 24),
            to_date=date(2026, 2, 27),
        ),
        frequency=ReturnsFrequency.DAILY,
        metric_basis=MetricBasis.NET,
        reporting_currency=None,
        series_selection=SeriesSelection(),
        benchmark=None,
        risk_free=None,
        data_policy=DataPolicy(),
        input_mode=InputMode.STATEFUL,
        stateless_input=StatelessInput.model_construct(portfolio_returns=[]),
        stateful_input=None,
    )
    with pytest.raises(HTTPException) as exc:
        await calculate_returns_series_workflow(request)
    assert exc.value.status_code == 400


def test_should_offload_returns_series_uses_runtime_settings(mocker):
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-27",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    mocker.patch(
        "app.services.returns_series_calculation_workflow_service.get_settings",
        return_value=type("Settings", (), {"RETURNS_SERIES_EXECUTOR_WINDOW_DAYS": 2})(),
    )

    assert should_offload_returns_series(request) is True


def test_should_offload_resolved_returns_series_uses_runtime_settings(mocker):
    mocker.patch(
        "app.services.returns_series_calculation_workflow_service.get_settings",
        return_value=type("Settings", (), {"RETURNS_SERIES_EXECUTOR_INPUT_COUNT": 3})(),
    )

    assert should_offload_resolved_returns_series(3) is True
    assert should_offload_resolved_returns_series(2) is False


@pytest.mark.asyncio
async def test_async_returns_series_submission_captures_observability_context(mocker):
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-27",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    mocker.patch(
        "app.services.returns_series_calculation_workflow_service.get_settings",
        return_value=type("Settings", (), {"RETURNS_SERIES_EXECUTOR_WINDOW_DAYS": 1})(),
    )
    captured: dict[str, Any] = {}

    def _register_async_submission_or_raise(**kwargs):
        captured.update(kwargs)
        return returns_series_calculation_workflow_service.accepted_returns_series_response(request.calculation_id)

    mocker.patch(
        "app.services.returns_series_calculation_workflow_service.register_async_submission_or_raise",
        side_effect=_register_async_submission_or_raise,
    )
    correlation_token = correlation_id_var.set(" corr-returns-series ")
    request_token = request_id_var.set(" req-returns-series ")
    trace_token = trace_id_var.set(" trace-returns-series ")
    try:
        response = await calculate_returns_series_workflow(request)
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert response.calculation_id == request.calculation_id
    assert captured["request_payload"]["observability_context"] == {
        "correlation_id": "corr-returns-series",
        "request_id": "req-returns-series",
        "trace_id": "trace-returns-series",
    }


def test_build_returns_series_execution_window_projects_optional_metadata():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-27",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    requested_window = build_returns_series_execution_window(
        request,
        source_request_fingerprint="source-fingerprint",
        input_count=0,
        benchmark_id=None,
        benchmark_return_source="sourced_benchmark_returns",
        benchmark_work_units=0,
    )

    assert requested_window == {
        "mode": "EXPLICIT",
        "from_date": "2026-02-24",
        "to_date": "2026-02-27",
        "period": None,
        "year": None,
        "input_mode": "stateful",
        "source_request_fingerprint": "source-fingerprint",
        "input_count": 0,
        "benchmark_return_source": "sourced_benchmark_returns",
        "benchmark_work_units": 0,
    }
    assert "benchmark_id" not in requested_window


def test_resolved_returns_series_execution_projection_uses_resolved_identity():
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-27",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    resolved = ResolvedStatefulReturnsSeriesRequest(
        request=request,
        identity_payload={"portfolio_id": "P1", "resolved": True},
        input_count=7,
        resolved_benchmark_id="BMK1",
        resolved_benchmark_return_source="linked_assignment",
        benchmark_work_units=2,
    )

    requested_window = returns_series_calculation_workflow_service._resolved_returns_series_execution_window(
        request,
        source_request_fingerprint="source-fingerprint",
        resolved=resolved,
    )
    payload = returns_series_calculation_workflow_service._resolved_returns_series_async_request_payload(resolved)

    assert requested_window == {
        "mode": "EXPLICIT",
        "from_date": "2026-02-24",
        "to_date": "2026-02-27",
        "period": None,
        "year": None,
        "input_mode": "stateful",
        "source_request_fingerprint": "source-fingerprint",
        "input_count": 7,
        "benchmark_id": "BMK1",
        "benchmark_return_source": "linked_assignment",
        "benchmark_work_units": 2,
    }
    assert payload["source_input_mode"] == "stateful"
    assert payload["resolved_benchmark_id"] == "BMK1"
    assert payload["resolved_benchmark_return_source"] == "linked_assignment"
    assert payload["resolved_request"]["portfolio_id"] == "P1"


def test_execution_failure_message_prefers_coded_detail_message():
    exc = HTTPException(status_code=422, detail={"code": "invalid_request", "message": "usable message"})

    assert _execution_failure_message(exc) == "usable message"


def test_execution_failure_message_uses_detail_or_exception_string():
    string_detail = HTTPException(status_code=422, detail="plain detail")
    plain_exception = RuntimeError("plain failure")

    assert _execution_failure_message(string_detail) == "plain detail"
    assert _execution_failure_message(plain_exception) == "plain failure"


@pytest.mark.asyncio
async def test_promoted_stateful_returns_series_helper_returns_replay_without_registering(mocker):
    request = ReturnsSeriesRequest.model_validate(
        {
            "portfolio_id": "P1",
            "as_of_date": "2026-02-27",
            "window": {"mode": "EXPLICIT", "from_date": "2026-02-24", "to_date": "2026-02-27"},
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )
    replay_response = returns_series_calculation_workflow_service.accepted_returns_series_response(
        request.calculation_id
    )
    replay_promoted = mocker.patch(
        "app.services.returns_series_calculation_workflow_service.replay_promoted_stateful_async_execution",
        return_value=replay_response,
    )
    register_sync = mocker.patch(
        "app.services.returns_series_calculation_workflow_service.register_sync_execution_or_raise"
    )

    response = await returns_series_calculation_workflow_service._calculate_promoted_stateful_returns_series(
        request=request,
        input_fingerprint="source-fingerprint",
        calculation_hash="source-hash",
    )

    assert response == replay_response
    replay_promoted.assert_called_once()
    register_sync.assert_not_called()
