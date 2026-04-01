# tests/unit/core/test_periods.py
from datetime import date

import pytest
from pydantic import BaseModel

from common.enums import PeriodType
from core.envelope import Periods
from core.errors import APIBadRequestError
from core.periods import resolve_period, resolve_periods


class ResolvedPeriod(BaseModel):
    name: str
    start_date: date
    end_date: date


@pytest.mark.parametrize(
    "period_def, as_of, expected_start, expected_end",
    [
        (
            {"type": "EXPLICIT", "explicit": {"start": "2025-02-15", "end": "2025-03-10"}},
            "2025-08-31",
            date(2025, 2, 15),
            date(2025, 3, 10),
        ),
        ({"type": "YTD"}, "2025-08-31", date(2025, 1, 1), date(2025, 8, 31)),
        ({"type": "QTD"}, "2025-08-31", date(2025, 7, 1), date(2025, 8, 31)),
        ({"type": "MTD"}, "2025-08-31", date(2025, 8, 1), date(2025, 8, 31)),
        ({"type": "WTD"}, "2025-08-31", date(2025, 8, 25), date(2025, 8, 31)),  # Sunday is day 6
        ({"type": "1Y"}, "2025-08-31", date(2024, 9, 1), date(2025, 8, 31)),
        ({"type": "3Y"}, "2025-08-31", date(2022, 9, 1), date(2025, 8, 31)),
        ({"type": "5Y"}, "2025-08-31", date(2020, 9, 1), date(2025, 8, 31)),
        ({"type": "ROLLING", "rolling": {"months": 12}}, "2025-08-31", date(2024, 9, 1), date(2025, 8, 31)),
        ({"type": "ROLLING", "rolling": {"days": 63}}, "2025-08-31", date(2025, 6, 30), date(2025, 8, 31)),
        ({"type": "ITD"}, "2025-08-31", date.min, date(2025, 8, 31)),
    ],
    ids=["EXPLICIT", "YTD", "QTD", "MTD", "WTD", "1Y", "3Y", "5Y", "ROLLING_M", "ROLLING_D", "ITD"],
)
def test_resolve_period(period_def, as_of, expected_start, expected_end):
    """Tests that all period types are resolved to the correct start and end dates."""
    # This test is for the old single-period resolver, which is now used internally.
    # It remains valuable for validating the underlying logic.
    period_model = Periods.model_validate(period_def)
    as_of_date = date.fromisoformat(as_of)
    start_date, end_date = resolve_period(period_model, as_of_date)
    assert start_date == expected_start
    assert end_date == expected_end


def test_resolve_periods_multi():
    """Tests the new multi-period resolver."""
    as_of = date(2025, 8, 15)
    inception = date(2023, 1, 1)
    requested_periods = [PeriodType.MTD, PeriodType.YTD, PeriodType.ITD, PeriodType.ONE_YEAR]

    resolved = resolve_periods(requested_periods, as_of, inception)

    assert len(resolved) == 4

    mtd = next(p for p in resolved if p.name == PeriodType.MTD.value)
    assert mtd.start_date == date(2025, 8, 1)
    assert mtd.end_date == date(2025, 8, 15)

    ytd = next(p for p in resolved if p.name == PeriodType.YTD.value)
    assert ytd.start_date == date(2025, 1, 1)
    assert ytd.end_date == date(2025, 8, 15)

    itd = next(p for p in resolved if p.name == PeriodType.ITD.value)
    assert itd.start_date == inception
    assert itd.end_date == date(2025, 8, 15)

    y1 = next(p for p in resolved if p.name == PeriodType.ONE_YEAR.value)
    assert y1.start_date == date(2024, 8, 16)
    assert y1.end_date == date(2025, 8, 15)


def test_resolve_periods_keeps_ytd_distinct_from_trailing_one_year():
    """YTD is calendar-year-to-date; 1Y is a trailing one-year window."""
    as_of = date(2025, 8, 15)

    resolved = resolve_periods(
        [PeriodType.YTD, PeriodType.ONE_YEAR],
        as_of,
        performance_start_date=date(2020, 1, 1),
    )

    ytd = next(p for p in resolved if p.name == PeriodType.YTD.value)
    y1 = next(p for p in resolved if p.name == PeriodType.ONE_YEAR.value)

    assert ytd.start_date == date(2025, 1, 1)
    assert y1.start_date == date(2024, 8, 16)
    assert ytd.start_date != y1.start_date
    assert ytd.end_date == y1.end_date == as_of


def test_resolve_periods_supports_explicit_request_windows():
    """Explicit periods should resolve to the caller's requested report window."""
    as_of = date(2025, 8, 15)
    explicit_start = date(2025, 8, 5)

    resolved = resolve_periods(
        [PeriodType.EXPLICIT],
        as_of,
        performance_start_date=date(2020, 1, 1),
        explicit_start_date=explicit_start,
    )

    assert len(resolved) == 1
    assert resolved[0].name == PeriodType.EXPLICIT.value
    assert resolved[0].start_date == explicit_start
    assert resolved[0].end_date == as_of


def test_resolve_periods_handles_empty_list():
    """Tests that the resolver returns an empty list if no periods are requested."""
    resolved = resolve_periods([], date(2025, 1, 1), date(2024, 1, 1))
    assert resolved == []


def test_resolve_periods_requires_explicit_start_for_explicit_requests():
    with pytest.raises(
        APIBadRequestError,
        match="EXPLICIT period requests require report_start_date",
    ):
        resolve_periods(
            [PeriodType.EXPLICIT],
            date(2025, 8, 15),
            performance_start_date=date(2020, 1, 1),
        )


def test_resolve_period_explicit_requires_explicit_block():
    class _ExplicitMissing:
        type = "EXPLICIT"
        explicit = None
        rolling = None

    period_model = _ExplicitMissing()
    with pytest.raises(APIBadRequestError, match="Explicit period definition is missing"):
        resolve_period(period_model, date(2025, 8, 31))


def test_resolve_period_rolling_requires_valid_definition():
    class _RollingMissing:
        type = "ROLLING"
        explicit = None
        rolling = None

    class _RollingEmpty:
        type = "ROLLING"
        explicit = None

        class rolling:
            months = None
            days = None

    period_model = _RollingMissing()
    with pytest.raises(APIBadRequestError, match="Rolling period definition is missing"):
        resolve_period(period_model, date(2025, 8, 31))

    invalid_model = _RollingEmpty()
    with pytest.raises(APIBadRequestError, match="Invalid rolling period definition"):
        resolve_period(invalid_model, date(2025, 8, 31))


def test_resolve_period_unsupported_period_type_raises():
    class _UnsupportedPeriod:
        type = "SINCE_INCEPTION"
        explicit = None
        rolling = None

    unsupported = _UnsupportedPeriod()
    with pytest.raises(NotImplementedError, match="not implemented"):
        resolve_period(unsupported, date(2025, 8, 31))
