from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from importlib.metadata import version

import exchange_calendars
import numpy as np

from core.envelope import Calendar

_CALENDAR_ALIASES = {"NYSE": "XNYS", "XNYS": "XNYS", "WEEKDAY": "WEEKDAY"}
_SESSION_INTERVAL = "(start_date, end_date]"


@dataclass(frozen=True)
class BusinessDayEvidence:
    calendar_id: str
    calendar_version: str
    session_interval: str
    business_day_count: int


def canonical_business_calendar_id(calendar: Calendar) -> str:
    calendar_name = (calendar.trading_calendar or "").strip().upper()
    calendar_id = _CALENDAR_ALIASES.get(calendar_name)
    if calendar.type != "BUSINESS" or calendar_id is None:
        raise ValueError("BUS/252 requires calendar.type=BUSINESS and trading_calendar NYSE, XNYS, or WEEKDAY.")
    return calendar_id


def business_day_evidence(*, calendar: Calendar, start_date: date, end_date: date) -> BusinessDayEvidence:
    evidence, _ = business_day_counts(calendar=calendar, start_date=start_date, end_dates=[end_date])
    return evidence


def business_day_counts(
    *,
    calendar: Calendar,
    start_date: date,
    end_dates: list[date],
) -> tuple[BusinessDayEvidence, list[int]]:
    calendar_id = canonical_business_calendar_id(calendar)
    counts = _business_day_counts_for_calendar(
        calendar_id=calendar_id,
        start_date=start_date,
        end_dates=end_dates,
    )
    evidence = BusinessDayEvidence(
        calendar_id=calendar_id,
        calendar_version=_business_calendar_version(calendar_id),
        session_interval=_SESSION_INTERVAL,
        business_day_count=max(counts, default=0),
    )
    return evidence, counts


def _business_day_counts_for_calendar(*, calendar_id: str, start_date: date, end_dates: list[date]) -> list[int]:
    if not end_dates:
        return []
    if calendar_id == "WEEKDAY":
        return [
            0
            if end_date <= start_date
            else int(
                np.busday_count(
                    np.datetime64(start_date + timedelta(days=1)),
                    np.datetime64(end_date + timedelta(days=1)),
                )
            )
            for end_date in end_dates
        ]
    return _exchange_business_day_counts(
        calendar_id=calendar_id,
        start_date=start_date,
        end_dates=end_dates,
    )


def _exchange_business_day_counts(*, calendar_id: str, start_date: date, end_dates: list[date]) -> list[int]:
    max_end_date = max(end_dates)
    if max_end_date <= start_date:
        return [0 for _ in end_dates]
    calendar_provider = exchange_calendars.get_calendar(
        calendar_id,
        start=start_date - timedelta(days=7),
        end=max_end_date + timedelta(days=7),
    )
    sessions = calendar_provider.sessions_in_range(start_date + timedelta(days=1), max_end_date)
    session_dates = sessions.to_numpy(dtype="datetime64[D]")
    return [
        0 if end_date <= start_date else int(np.searchsorted(session_dates, np.datetime64(end_date), side="right"))
        for end_date in end_dates
    ]


def _business_calendar_version(calendar_id: str) -> str:
    if calendar_id == "WEEKDAY":
        return "WEEKDAY:v1"
    return f"exchange_calendars:{version('exchange-calendars')}/{calendar_id}"
