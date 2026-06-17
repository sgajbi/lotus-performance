from datetime import date
from enum import Enum

import pandas as pd
import pytest

from core.errors import APIBadRequestError
from core.workspace_periods import WorkspacePeriodType, _direct_workspace_period_start_date, resolve_workspace_periods


def test_resolve_workspace_periods_supports_attached_horizons_and_since_inception():
    resolved = resolve_workspace_periods(
        [
            WorkspacePeriodType.ONE_DAY,
            WorkspacePeriodType.FIVE_DAYS,
            WorkspacePeriodType.ONE_MONTH,
            WorkspacePeriodType.TWO_YEARS,
            WorkspacePeriodType.SINCE_INCEPTION,
        ],
        as_of=date(2026, 6, 30),
        performance_start_date=date(2024, 1, 15),
    )

    assert [item.name for item in resolved] == ["1D", "5D", "1M", "2Y", "SI"]
    assert resolved[0].start_date == date(2026, 6, 30)
    assert resolved[1].start_date == date(2026, 6, 24)
    assert resolved[2].start_date == date(2026, 5, 31)
    assert resolved[3].start_date == date(2024, 7, 1)
    assert resolved[4].start_date == date(2024, 1, 15)


def test_resolve_workspace_periods_requires_report_start_for_explicit():
    with pytest.raises(APIBadRequestError):
        resolve_workspace_periods(
            [WorkspacePeriodType.EXPLICIT],
            as_of=date(2026, 6, 30),
            performance_start_date=date(2024, 1, 15),
        )


def test_resolve_workspace_periods_uses_explicit_start_date_when_provided():
    resolved = resolve_workspace_periods(
        [WorkspacePeriodType.EXPLICIT],
        as_of=date(2026, 6, 30),
        performance_start_date=date(2024, 1, 15),
        explicit_start_date=date(2026, 4, 1),
    )

    assert len(resolved) == 1
    assert resolved[0].name == "EXPLICIT"
    assert resolved[0].start_date == date(2026, 4, 1)
    assert resolved[0].end_date == date(2026, 6, 30)


def test_direct_workspace_period_start_date_projects_direct_periods():
    as_of_ts = pd.Timestamp(date(2026, 6, 30))

    assert _direct_workspace_period_start_date(
        WorkspacePeriodType.EXPLICIT,
        as_of_ts=as_of_ts,
        performance_start_date=date(2024, 1, 15),
        explicit_start_date=date(2026, 4, 1),
    ) == date(2026, 4, 1)
    assert _direct_workspace_period_start_date(
        WorkspacePeriodType.SINCE_INCEPTION,
        as_of_ts=as_of_ts,
        performance_start_date=date(2024, 1, 15),
        explicit_start_date=None,
    ) == date(2024, 1, 15)
    assert _direct_workspace_period_start_date(
        WorkspacePeriodType.YTD,
        as_of_ts=as_of_ts,
        performance_start_date=date(2024, 1, 15),
        explicit_start_date=None,
    ) == date(2026, 1, 1)
    assert (
        _direct_workspace_period_start_date(
            WorkspacePeriodType.ONE_MONTH,
            as_of_ts=as_of_ts,
            performance_start_date=date(2024, 1, 15),
            explicit_start_date=None,
        )
        is None
    )


def test_direct_workspace_period_start_date_requires_explicit_start():
    with pytest.raises(
        APIBadRequestError,
        match="EXPLICIT workspace period requests require report_start_date",
    ):
        _direct_workspace_period_start_date(
            WorkspacePeriodType.EXPLICIT,
            as_of_ts=pd.Timestamp(date(2026, 6, 30)),
            performance_start_date=date(2024, 1, 15),
            explicit_start_date=None,
        )


def test_resolve_workspace_periods_clamps_ytd_to_performance_start_date():
    resolved = resolve_workspace_periods(
        [WorkspacePeriodType.YTD],
        as_of=date(2026, 6, 30),
        performance_start_date=date(2026, 2, 3),
    )

    assert len(resolved) == 1
    assert resolved[0].name == "YTD"
    assert resolved[0].start_date == date(2026, 2, 3)
    assert resolved[0].end_date == date(2026, 6, 30)


def test_resolve_workspace_periods_clamps_long_horizons_to_performance_start_date():
    resolved = resolve_workspace_periods(
        [WorkspacePeriodType.FIVE_YEARS, WorkspacePeriodType.TEN_YEARS],
        as_of=date(2026, 6, 30),
        performance_start_date=date(2025, 2, 3),
    )

    assert resolved[0].start_date == date(2025, 2, 3)
    assert resolved[1].start_date == date(2025, 2, 3)


def test_resolve_workspace_periods_projects_remaining_fixed_lookback_families():
    resolved = resolve_workspace_periods(
        [
            WorkspacePeriodType.TWO_DAYS,
            WorkspacePeriodType.TEN_DAYS,
            WorkspacePeriodType.THREE_MONTHS,
            WorkspacePeriodType.SIX_MONTHS,
            WorkspacePeriodType.ONE_YEAR,
            WorkspacePeriodType.TEN_YEARS,
        ],
        as_of=date(2026, 6, 30),
        performance_start_date=date(2010, 1, 1),
    )

    assert [item.start_date for item in resolved] == [
        date(2026, 6, 29),
        date(2026, 6, 17),
        date(2026, 3, 31),
        date(2025, 12, 31),
        date(2025, 7, 1),
        date(2016, 7, 1),
    ]


def test_resolve_workspace_periods_rejects_unknown_period_type():
    class UnsupportedPeriod(str, Enum):
        UNKNOWN = "UNKNOWN"

    with pytest.raises(APIBadRequestError, match="Unsupported workspace period type 'UNKNOWN'"):
        resolve_workspace_periods(  # type: ignore[arg-type]
            [UnsupportedPeriod.UNKNOWN],
            as_of=date(2026, 6, 30),
            performance_start_date=date(2024, 1, 15),
        )
