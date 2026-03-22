# core/periods.py
from datetime import date
from typing import List, Tuple

import pandas as pd
from pydantic import BaseModel

from common.enums import PeriodType
from core.envelope import Periods
from core.errors import APIBadRequestError


class ResolvedPeriod(BaseModel):
    """A data carrier for a resolved time period."""

    name: str
    start_date: date
    end_date: date


def resolve_period(period_model: Periods, as_of: date) -> Tuple[date, date]:
    """
    Resolves a Periods model into a concrete (start_date, end_date) tuple.
    This is now an internal helper for the new `resolve_periods` function.
    """
    period_type = period_model.type
    as_of_ts = pd.Timestamp(as_of)

    if period_type == "EXPLICIT":
        if not period_model.explicit:
            raise APIBadRequestError("Explicit period definition is missing.")
        return period_model.explicit.start, period_model.explicit.end

    if period_type == "ITD":
        # Cannot be resolved without a true inception date, signal this.
        # The caller (engine) will substitute the portfolio's actual start date.
        return date.min, as_of

    end_date = as_of
    if period_type == "YTD":
        start_date = as_of_ts.to_period("Y").start_time.date()
    elif period_type == "QTD":
        start_date = as_of_ts.to_period("Q").start_time.date()
    elif period_type == "MTD":
        start_date = as_of_ts.to_period("M").start_time.date()
    elif period_type == "WTD":
        start_date = (as_of_ts - pd.to_timedelta(as_of_ts.dayofweek, unit="d")).date()
    elif period_type in ["1Y", "3Y", "5Y"]:
        years = int(period_type[:-1])  # Parse "1Y" into 1, etc.
        start_date = (as_of_ts - pd.DateOffset(years=years) + pd.Timedelta(days=1)).date()
    elif period_type == "ROLLING":
        if not period_model.rolling:
            raise APIBadRequestError("Rolling period definition is missing.")
        if period_model.rolling.months:
            start_date = (as_of_ts - pd.DateOffset(months=period_model.rolling.months) + pd.Timedelta(days=1)).date()
        elif period_model.rolling.days:
            start_date = (as_of_ts - pd.Timedelta(days=period_model.rolling.days - 1)).date()
        else:
            raise APIBadRequestError("Invalid rolling period definition.")
    else:
        raise NotImplementedError(f"Period type '{period_type}' is not implemented.")

    return start_date, end_date


def resolve_periods(
    periods: List[PeriodType],
    as_of: date,
    performance_start_date: date,
    *,
    explicit_start_date: date | None = None,
) -> List[ResolvedPeriod]:
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
        period_model = Periods(type=period_enum.value)
        start_date, end_date = resolve_period(period_model, as_of)

        # The legacy resolver uses date.min for ITD; we substitute the true inception here.
        if period_enum == PeriodType.ITD:
            start_date = performance_start_date

        resolved_list.append(ResolvedPeriod(name=period_enum.value, start_date=start_date, end_date=end_date))
    return resolved_list
