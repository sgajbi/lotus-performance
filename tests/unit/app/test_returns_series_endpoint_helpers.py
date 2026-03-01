from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from fastapi import HTTPException

from app.api.endpoints.returns_series import (
    _core_points_to_dataframe,
    _date_range_count,
    _detect_gaps,
    _filter_window,
    _period_start,
    _points_from_df,
    _portfolio_timeseries_to_valuation_points,
    _resample_returns,
    _resolve_window,
    _to_dataframe,
    get_returns_series,
)
from app.models.returns_series import (
    CalendarPolicy,
    DataPolicy,
    InputMode,
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
    assert _period_start(date(2026, 2, 27), period, None) == expected


def test_period_start_year_requires_year_and_accepts_valid_year():
    with pytest.raises(ValueError, match="year is required when period=YEAR"):
        _period_start(date(2026, 2, 27), ReturnsRelativePeriod.YEAR, None)

    assert _period_start(date(2026, 2, 27), ReturnsRelativePeriod.YEAR, 2024) == date(2024, 1, 1)


def test_period_start_rejects_unsupported_period_value():
    with pytest.raises(ValueError, match="Unsupported period"):
        _period_start(date(2026, 2, 27), "UNKNOWN", None)  # type: ignore[arg-type]


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
    resolved = _resolve_window(valid_request)
    assert resolved.start_date == date(2026, 2, 1)
    assert resolved.end_date == date(2026, 2, 27)
    assert resolved.resolved_period_label == "MTD"

    invalid_request = ReturnsSeriesRequest.model_construct(
        portfolio_id="P1",
        as_of_date=date(2026, 2, 27),
        window=ReturnsWindow.model_construct(mode=ReturnsWindowMode.RELATIVE, period=None, year=None),
        frequency=ReturnsFrequency.DAILY,
        metric_basis="NET",
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
        _resolve_window(invalid_request)
    assert exc.value.status_code == 400


def test_dataframe_and_window_helpers_handle_error_paths():
    with pytest.raises(HTTPException) as exc:
        _to_dataframe([], series_type="portfolio")
    assert exc.value.status_code == 422


def test_core_points_to_dataframe_skips_invalid_points_and_bad_values():
    with pytest.raises(HTTPException):
        _core_points_to_dataframe(
            points=[
                {"series_date": None, "benchmark_return": "0.01"},
                {"series_date": "bad", "benchmark_return": "0.01"},
            ],
            date_key="series_date",
            value_key="benchmark_return",
            series_type="benchmark",
        )

    df = _core_points_to_dataframe(
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
    points = _portfolio_timeseries_to_valuation_points(
        observations=[
            {"valuation_date": "2026-02-24", "beginning_market_value": "100", "ending_market_value": "101"},
            {
                "valuation_date": "2026-02-25",
                "beginning_market_value": "101",
                "ending_market_value": "102",
                "cash_flows": [
                    {"amount": "1.2", "timing": "bod"},
                    {"amount": "0.3", "timing": "eod"},
                    {"amount": "999", "timing": "invalid"},
                    "not-a-dict",
                ],
            },
        ]
    )
    assert len(points) == 2
    assert points[1]["bod_cf"] == Decimal("1.2")
    assert points[1]["eod_cf"] == Decimal("0.3")

    with pytest.raises(HTTPException):
        _portfolio_timeseries_to_valuation_points(observations=[{"valuation_date": None}])

    with pytest.raises(HTTPException) as exc:
        _to_dataframe(
            [
                ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.001")),
                ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.002")),
            ],
            series_type="portfolio",
        )
    assert exc.value.status_code == 400

    df = _to_dataframe(
        [
            ReturnPoint(date=date(2026, 2, 25), return_value=Decimal("0.002")),
            ReturnPoint(date=date(2026, 2, 24), return_value=Decimal("0.001")),
        ],
        series_type="portfolio",
    )
    assert list(df["date"].dt.date) == [date(2026, 2, 24), date(2026, 2, 25)]

    with pytest.raises(HTTPException) as exc:
        _filter_window(
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
    monthly = _resample_returns(df, frequency=ReturnsFrequency.MONTHLY)
    assert len(monthly) == 2

    resolved = ResolvedWindow(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))
    assert _date_range_count(resolved, frequency=ReturnsFrequency.DAILY, calendar_policy=CalendarPolicy.CALENDAR) == 28
    assert _date_range_count(resolved, frequency=ReturnsFrequency.WEEKLY, calendar_policy=CalendarPolicy.BUSINESS) == 4
    assert _date_range_count(resolved, frequency=ReturnsFrequency.MONTHLY, calendar_policy=CalendarPolicy.BUSINESS) == 1

    tiny = pd.DataFrame({"date": pd.to_datetime(["2026-02-01"]), "return_value": [Decimal("0.01")]})
    assert _detect_gaps(tiny, frequency=ReturnsFrequency.DAILY, series_type="portfolio") == []

    gappy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-01", "2026-02-10"]),
            "return_value": [Decimal("0.01"), Decimal("0.02")],
        }
    )
    gaps = _detect_gaps(gappy, frequency=ReturnsFrequency.DAILY, series_type="portfolio")
    assert len(gaps) == 1
    assert gaps[0].gap_days == 8

    points = _points_from_df(monthly)
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
        metric_basis="NET",
        reporting_currency=None,
        series_selection=SeriesSelection(),
        benchmark=None,
        risk_free=None,
        data_policy=DataPolicy(),
        input_mode=InputMode.STATELESS,
        stateless_input=None,
        stateful_input=StatefulInput.model_construct(consumer_system="lotus-performance"),
    )
    with pytest.raises(HTTPException) as exc:
        await get_returns_series(request)
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
        metric_basis="NET",
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
        await get_returns_series(request)
    assert exc.value.status_code == 400
