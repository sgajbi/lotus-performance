from datetime import date

import pytest

from app.models.request_window_validation import validate_ordered_explicit_window
from common.enums import PeriodType


def test_reversed_explicit_window_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="report_start_date must be on or before report_end_date when an EXPLICIT period is requested",
    ):
        validate_ordered_explicit_window(
            requested_periods=[PeriodType.EXPLICIT],
            report_start_date=date(2025, 1, 3),
            report_end_date=date(2025, 1, 2),
        )


def test_same_day_explicit_window_is_valid() -> None:
    validate_ordered_explicit_window(
        requested_periods=[PeriodType.EXPLICIT],
        report_start_date=date(2025, 1, 2),
        report_end_date=date(2025, 1, 2),
    )


def test_non_explicit_period_ignores_report_start_date() -> None:
    validate_ordered_explicit_window(
        requested_periods=[PeriodType.YTD],
        report_start_date=date(2025, 1, 3),
        report_end_date=date(2025, 1, 2),
    )
