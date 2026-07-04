# core/periods.py
from datetime import date

import pandas as pd
from pydantic import BaseModel

from common.enums import PeriodType, canonical_performance_period_code
from core.envelope import Periods
from core.errors import APIBadRequestError


class ResolvedPeriod(BaseModel):
    """A data carrier for a resolved time period."""

    name: str
    start_date: date
    end_date: date


def resolve_period(period_model: Periods, as_of: date) -> tuple[date, date]:
    """
    Resolves a Periods model into a concrete (start_date, end_date) tuple.
    This is now an internal helper for the new `resolve_periods` function.
    """
    period_type = period_model.type
    as_of_ts = pd.Timestamp(as_of)

    if period_type == "EXPLICIT":
        return _resolve_explicit_period(period_model)

    if period_type in {"SI", "ITD"}:
        # Cannot be resolved without a true inception date, signal this.
        # The caller (engine) will substitute the portfolio's actual start date.
        return date.min, as_of

    end_date = as_of
    start_date = _resolve_calendar_period_start(period_type, as_of_ts)
    if start_date is None:
        start_date = _resolve_trailing_or_rolling_period_start(period_model, as_of_ts)

    return start_date, end_date


def _resolve_explicit_period(period_model: Periods) -> tuple[date, date]:
    if not period_model.explicit:
        raise APIBadRequestError("Explicit period definition is missing.")
    return period_model.explicit.start, period_model.explicit.end


def _resolve_calendar_period_start(period_type: str, as_of_ts: pd.Timestamp) -> date | None:
    calendar_period_codes = {
        "YTD": "Y",
        "QTD": "Q",
        "MTD": "M",
    }
    if period_type in calendar_period_codes:
        return as_of_ts.to_period(calendar_period_codes[period_type]).start_time.date()
    if period_type == "WTD":
        return (as_of_ts - pd.to_timedelta(as_of_ts.dayofweek, unit="d")).date()
    return None


def _resolve_trailing_or_rolling_period_start(period_model: Periods, as_of_ts: pd.Timestamp) -> date:
    period_type = period_model.type
    if period_type in {"1Y", "3Y", "5Y"}:
        return _trailing_year_period_start(period_type, as_of_ts)
    if period_type == "ROLLING":
        return _resolve_rolling_period_start(period_model, as_of_ts)
    raise NotImplementedError(f"Period type '{period_type}' is not implemented.")


def _trailing_year_period_start(period_type: str, as_of_ts: pd.Timestamp) -> date:
    years = int(period_type[:-1])
    return (as_of_ts - pd.DateOffset(years=years) + pd.Timedelta(days=1)).date()


def _resolve_rolling_period_start(period_model: Periods, as_of_ts: pd.Timestamp) -> date:
    if not period_model.rolling:
        raise APIBadRequestError("Rolling period definition is missing.")
    if period_model.rolling.months:
        return (as_of_ts - pd.DateOffset(months=period_model.rolling.months) + pd.Timedelta(days=1)).date()
    if period_model.rolling.days:
        return (as_of_ts - pd.Timedelta(days=period_model.rolling.days - 1)).date()
    raise APIBadRequestError("Invalid rolling period definition.")


def resolve_periods(
    periods: list[PeriodType],
    as_of: date,
    performance_start_date: date,
    *,
    explicit_start_date: date | None = None,
) -> list[ResolvedPeriod]:
    """
    Resolves a list of PeriodType enums into a list of concrete period objects.
    """
    resolved_list = []
    for period_enum in periods:
        if period_enum == PeriodType.EXPLICIT:
            if explicit_start_date is None:
                raise APIBadRequestError(
                    "EXPLICIT period requests require report_start_date so the window can be resolved."
                )
            resolved_list.append(
                ResolvedPeriod(
                    name=period_enum.value,
                    start_date=explicit_start_date,
                    end_date=as_of,
                )
            )
            continue

        # We wrap the enum in the legacy Periods model to reuse the existing logic.
        # This can be refactored later if the Periods model is fully removed.
        period_name = str(canonical_performance_period_code(period_enum))
        period_model = Periods(type=period_name)
        start_date, end_date = resolve_period(period_model, as_of)

        # The resolver uses date.min for SI; we substitute the true inception here.
        if period_name == PeriodType.SI.value:
            start_date = performance_start_date

        resolved_list.append(ResolvedPeriod(name=period_name, start_date=start_date, end_date=end_date))
    return resolved_list
