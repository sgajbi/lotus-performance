from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd

LOTUS_REFERENCE_MARKET_CALENDAR_ID = "lotus-reference-market"
LOTUS_REFERENCE_MARKET_CALENDAR_VERSION = "lotus-reference-market-holidays.v1"
LOTUS_REFERENCE_MARKET_CALENDAR_START = date(1970, 1, 1)
LOTUS_REFERENCE_MARKET_CALENDAR_END = date(2099, 12, 31)


@dataclass(frozen=True)
class LotusReferenceMarketCalendarMetadata:
    source_id: str
    version: str
    supported_from: date
    supported_to: date
    holiday_count: int


def is_lotus_reference_market_date(value: Any) -> bool:
    timestamp = pd.Timestamp(value)
    if (
        timestamp.date() < LOTUS_REFERENCE_MARKET_CALENDAR_START
        or timestamp.date() > LOTUS_REFERENCE_MARKET_CALENDAR_END
    ):
        return False
    return timestamp.weekday() < 5 and timestamp.date() not in lotus_reference_market_holidays()


def lotus_reference_market_holidays() -> frozenset[date]:
    return _generated_lotus_reference_market_holidays()


def lotus_reference_market_calendar_metadata() -> LotusReferenceMarketCalendarMetadata:
    return LotusReferenceMarketCalendarMetadata(
        source_id=LOTUS_REFERENCE_MARKET_CALENDAR_ID,
        version=LOTUS_REFERENCE_MARKET_CALENDAR_VERSION,
        supported_from=LOTUS_REFERENCE_MARKET_CALENDAR_START,
        supported_to=LOTUS_REFERENCE_MARKET_CALENDAR_END,
        holiday_count=len(lotus_reference_market_holidays()),
    )


def lotus_reference_market_calendar_supports(*, start: date, end: date) -> bool:
    return LOTUS_REFERENCE_MARKET_CALENDAR_START <= start <= end <= LOTUS_REFERENCE_MARKET_CALENDAR_END


@lru_cache(maxsize=1)
def _generated_lotus_reference_market_holidays() -> frozenset[date]:
    holidays: set[date] = set()
    for year in range(LOTUS_REFERENCE_MARKET_CALENDAR_START.year, LOTUS_REFERENCE_MARKET_CALENDAR_END.year + 1):
        holidays.update(_fixed_holiday_observance(date(year, 1, 1)))
        holidays.add(_good_friday(year))
        holidays.update(_fixed_holiday_observance(date(year, 12, 25)))
    return frozenset(
        holiday
        for holiday in holidays
        if LOTUS_REFERENCE_MARKET_CALENDAR_START <= holiday <= LOTUS_REFERENCE_MARKET_CALENDAR_END
    )


def _fixed_holiday_observance(actual_date: date) -> set[date]:
    if actual_date.weekday() == 5:
        return {actual_date - timedelta(days=1)}
    if actual_date.weekday() == 6:
        return {actual_date + timedelta(days=1)}
    return {actual_date}


def _good_friday(year: int) -> date:
    return _western_easter_sunday(year) - timedelta(days=2)


def _western_easter_sunday(year: int) -> date:
    century = year // 100
    year_in_century = year % 100
    leap_correction = century // 4
    century_remainder = century % 4
    epact_base = (century + 8) // 25
    epact_adjustment = (century - epact_base + 1) // 3
    golden_year = (19 * (year % 19) + century - leap_correction - epact_adjustment + 15) % 30
    leap_days = year_in_century // 4
    year_remainder = year_in_century % 4
    weekday_offset = (32 + 2 * century_remainder + 2 * leap_days - golden_year - year_remainder) % 7
    paschal_adjustment = (year % 19 + 11 * golden_year + 22 * weekday_offset) // 451
    easter_month = (golden_year + weekday_offset - 7 * paschal_adjustment + 114) // 31
    easter_day = ((golden_year + weekday_offset - 7 * paschal_adjustment + 114) % 31) + 1
    return date(year, easter_month, easter_day)
