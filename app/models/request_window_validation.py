from collections.abc import Iterable
from datetime import date
from enum import Enum


def validate_ordered_explicit_window(
    *,
    requested_periods: Iterable[str | Enum],
    report_start_date: date | None,
    report_end_date: date,
) -> None:
    """Reject a reversed window only when the caller requests EXPLICIT."""
    has_explicit_period = any(_period_value(period) == "EXPLICIT" for period in requested_periods)
    if has_explicit_period and report_start_date is not None and report_start_date > report_end_date:
        raise ValueError("report_start_date must be on or before report_end_date when an EXPLICIT period is requested")


def _period_value(period: str | Enum) -> str:
    value = period.value if isinstance(period, Enum) else period
    return str(value)
