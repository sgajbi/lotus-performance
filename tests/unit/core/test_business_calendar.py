from datetime import date

import pytest

from core.business_calendar import business_day_evidence
from core.envelope import Calendar


def test_weekday_calendar_counts_start_exclusive_end_inclusive_across_weekends():
    evidence = business_day_evidence(
        calendar=Calendar(type="BUSINESS", trading_calendar="WEEKDAY"),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 7, 1),
    )

    assert evidence.calendar_id == "WEEKDAY"
    assert evidence.calendar_version == "WEEKDAY:v1"
    assert evidence.session_interval == "(start_date, end_date]"
    assert evidence.business_day_count == 129

    leap_window = business_day_evidence(
        calendar=Calendar(type="BUSINESS", trading_calendar="WEEKDAY"),
        start_date=date(2024, 2, 28),
        end_date=date(2024, 3, 1),
    )
    assert leap_window.business_day_count == 2


def test_nyse_calendar_applies_exchange_holidays_and_publishes_provider_version():
    evidence = business_day_evidence(
        calendar=Calendar(type="BUSINESS", trading_calendar="NYSE"),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 7, 1),
    )

    assert evidence.calendar_id == "XNYS"
    assert evidence.calendar_version == "exchange_calendars:4.13.2/XNYS"
    assert evidence.business_day_count == 123


@pytest.mark.parametrize(
    "calendar",
    [
        Calendar(type="NATURAL", trading_calendar=None),
        Calendar(type="BUSINESS", trading_calendar=None),
        Calendar(type="BUSINESS", trading_calendar="UNKNOWN"),
    ],
)
def test_business_day_calendar_rejects_missing_or_unsupported_policy(calendar):
    with pytest.raises(ValueError, match="BUS/252 requires"):
        business_day_evidence(
            calendar=calendar,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 7, 1),
        )


def test_business_day_calendar_returns_zero_for_zero_length_window():
    evidence = business_day_evidence(
        calendar=Calendar(type="BUSINESS", trading_calendar="WEEKDAY"),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 1),
    )

    assert evidence.business_day_count == 0
