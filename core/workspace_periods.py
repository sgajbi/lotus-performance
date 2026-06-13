from __future__ import annotations

from datetime import date
from enum import Enum

import pandas as pd
from pydantic import BaseModel

from core.errors import APIBadRequestError


class WorkspacePeriodType(str, Enum):
    ONE_DAY = "1D"
    TWO_DAYS = "2D"
    FIVE_DAYS = "5D"
    TEN_DAYS = "10D"
    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    YTD = "YTD"
    ONE_YEAR = "1Y"
    TWO_YEARS = "2Y"
    FIVE_YEARS = "5Y"
    TEN_YEARS = "10Y"
    SINCE_INCEPTION = "SI"
    EXPLICIT = "EXPLICIT"


class ResolvedWorkspacePeriod(BaseModel):
    name: str
    start_date: date
    end_date: date


_BUSINESS_DAY_LOOKBACKS: dict[WorkspacePeriodType, int] = {
    WorkspacePeriodType.ONE_DAY: 1,
    WorkspacePeriodType.TWO_DAYS: 2,
    WorkspacePeriodType.FIVE_DAYS: 5,
    WorkspacePeriodType.TEN_DAYS: 10,
}

_MONTH_LOOKBACKS: dict[WorkspacePeriodType, int] = {
    WorkspacePeriodType.ONE_MONTH: 1,
    WorkspacePeriodType.THREE_MONTHS: 3,
    WorkspacePeriodType.SIX_MONTHS: 6,
}

_YEAR_LOOKBACKS: dict[WorkspacePeriodType, int] = {
    WorkspacePeriodType.ONE_YEAR: 1,
    WorkspacePeriodType.TWO_YEARS: 2,
    WorkspacePeriodType.FIVE_YEARS: 5,
    WorkspacePeriodType.TEN_YEARS: 10,
}


def _workspace_period_start_date(
    period: WorkspacePeriodType,
    *,
    as_of_ts: pd.Timestamp,
    performance_start_date: date,
    explicit_start_date: date | None,
) -> date:
    if period == WorkspacePeriodType.EXPLICIT:
        if explicit_start_date is None:
            raise APIBadRequestError(
                "EXPLICIT workspace period requests require report_start_date so the window can be resolved."
            )
        return explicit_start_date
    if period == WorkspacePeriodType.SINCE_INCEPTION:
        return performance_start_date
    if period == WorkspacePeriodType.YTD:
        return as_of_ts.to_period("Y").start_time.date()
    lookback_start_date = _fixed_lookback_workspace_period_start(period, as_of_ts)
    if lookback_start_date is not None:
        return lookback_start_date
    raise APIBadRequestError(f"Unsupported workspace period type '{period.value}'.")


def _fixed_lookback_workspace_period_start(
    period: WorkspacePeriodType,
    as_of_ts: pd.Timestamp,
) -> date | None:
    if period in _BUSINESS_DAY_LOOKBACKS:
        business_days = _BUSINESS_DAY_LOOKBACKS[period] - 1
        return (as_of_ts - pd.offsets.BDay(business_days)).date()
    if period in _MONTH_LOOKBACKS:
        months = _MONTH_LOOKBACKS[period]
        return (as_of_ts - pd.DateOffset(months=months) + pd.Timedelta(days=1)).date()
    if period in _YEAR_LOOKBACKS:
        years = _YEAR_LOOKBACKS[period]
        return (as_of_ts - pd.DateOffset(years=years) + pd.Timedelta(days=1)).date()
    return None


def resolve_workspace_periods(
    periods: list[WorkspacePeriodType],
    *,
    as_of: date,
    performance_start_date: date,
    explicit_start_date: date | None = None,
) -> list[ResolvedWorkspacePeriod]:
    resolved_periods: list[ResolvedWorkspacePeriod] = []
    as_of_ts = pd.Timestamp(as_of)

    for period in periods:
        start_date = _workspace_period_start_date(
            period,
            as_of_ts=as_of_ts,
            performance_start_date=performance_start_date,
            explicit_start_date=explicit_start_date,
        )
        resolved_periods.append(
            ResolvedWorkspacePeriod(
                name=period.value,
                start_date=max(start_date, performance_start_date),
                end_date=as_of,
            )
        )
    return resolved_periods
