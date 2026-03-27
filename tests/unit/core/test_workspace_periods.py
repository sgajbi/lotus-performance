from datetime import date
from enum import Enum

import pytest

from core.errors import APIBadRequestError
from core.workspace_periods import WorkspacePeriodType, resolve_workspace_periods


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


def test_resolve_workspace_periods_clamps_long_horizons_to_performance_start_date():
    resolved = resolve_workspace_periods(
        [WorkspacePeriodType.FIVE_YEARS, WorkspacePeriodType.TEN_YEARS],
        as_of=date(2026, 6, 30),
        performance_start_date=date(2025, 2, 3),
    )

    assert resolved[0].start_date == date(2025, 2, 3)
    assert resolved[1].start_date == date(2025, 2, 3)


def test_resolve_workspace_periods_rejects_unknown_period_type():
    class UnsupportedPeriod(str, Enum):
        UNKNOWN = "UNKNOWN"

    with pytest.raises(APIBadRequestError, match="Unsupported workspace period type 'UNKNOWN'"):
        resolve_workspace_periods(  # type: ignore[arg-type]
            [UnsupportedPeriod.UNKNOWN],
            as_of=date(2026, 6, 30),
            performance_start_date=date(2024, 1, 15),
        )
