from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.models.responses import (
    PerformanceHistoryCoverage,
    PerformanceHistoryCoverageReason,
    PerformanceHistoryCoverageStatus,
)
from app.services.analytics_observation_dates import normalize_observation_date
from core.errors import APIUnprocessableEntityError

_MISSING_DATE_SAMPLE_LIMIT = 10
_MAX_UNATTESTED_BUSINESS_CLOSURE_DAYS = 2
_MAX_HISTORY_COVERAGE_WINDOW_DAYS = 36_600
_HISTORY_COVERAGE_WINDOW_TOO_LARGE = "PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE"


@dataclass(frozen=True)
class _CoverageWindow:
    normalized_observations: tuple[date, ...]
    ignored_dates: frozenset[date]
    required_dates: tuple[date, ...]
    missing_dates: tuple[date, ...]
    effective_dates: tuple[date, ...]
    baseline_applied: bool


def assess_performance_history_coverage(
    *,
    requested_start_date: date,
    requested_end_date: date,
    observation_dates: Iterable[object],
    calendar_type: Literal["BUSINESS", "NATURAL"],
    trading_calendar: str | None,
    explicitly_ignored_dates: Iterable[date] = (),
) -> PerformanceHistoryCoverage:
    """Qualify the requested history without inventing returns for absent observations."""
    validate_performance_history_window(start=requested_start_date, end=requested_end_date)
    window = _coverage_window(
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        observation_dates=observation_dates,
        calendar_type=calendar_type,
        explicitly_ignored_dates=explicitly_ignored_dates,
    )
    reason_codes = _history_coverage_reason_codes(
        missing_dates=window.missing_dates,
        required_dates=window.required_dates,
        effective_dates=window.effective_dates,
        ignored_dates=window.ignored_dates,
        baseline_applied=window.baseline_applied,
    )
    status = _history_coverage_status(
        missing_dates=window.missing_dates,
        required_dates=window.required_dates,
        effective_dates=window.effective_dates,
        calendar_type=calendar_type,
        trading_calendar=trading_calendar,
    )
    reason_codes.extend(
        _status_reason_codes(
            status=status,
            missing_dates=window.missing_dates,
            effective_dates=window.effective_dates,
            calendar_type=calendar_type,
            trading_calendar=trading_calendar,
        )
    )
    covered_start, covered_end = _date_bounds(window.normalized_observations)
    effective_start, effective_end = _date_bounds(window.effective_dates)

    return PerformanceHistoryCoverage(
        status=status,
        calculation_basis={
            "complete": "requested_window",
            "partial": "available_window",
            "unknown": "available_window",
        }[status],
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        covered_start_date=covered_start,
        covered_end_date=covered_end,
        effective_start_date=effective_start,
        effective_end_date=effective_end,
        calendar_basis={"NATURAL": "natural_days", "BUSINESS": "business_weekdays"}[calendar_type],
        missing_required_observation_count=len(window.missing_dates),
        missing_required_observation_dates_sample=window.missing_dates[:_MISSING_DATE_SAMPLE_LIMIT],
        reason_codes=reason_codes,
    )


def validate_performance_history_window(*, start: date, end: date) -> None:
    window_days = (end - start).days
    if window_days <= _MAX_HISTORY_COVERAGE_WINDOW_DAYS:
        return
    raise APIUnprocessableEntityError(
        detail=(
            "Performance history coverage windows cannot exceed "
            f"{_MAX_HISTORY_COVERAGE_WINDOW_DAYS} days; requested {window_days} days."
        ),
        error_code=_HISTORY_COVERAGE_WINDOW_TOO_LARGE,
    )


def _coverage_window(
    *,
    requested_start_date: date,
    requested_end_date: date,
    observation_dates: Iterable[object],
    calendar_type: Literal["BUSINESS", "NATURAL"],
    explicitly_ignored_dates: Iterable[date],
) -> _CoverageWindow:
    observations = tuple(sorted({normalize_observation_date(value) for value in observation_dates}))
    ignored_dates = frozenset(
        value for value in explicitly_ignored_dates if requested_start_date <= value <= requested_end_date
    )
    required_dates, baseline_applied = _apply_beginning_market_value_baseline(
        required_dates=_required_observation_dates(
            start=requested_start_date,
            end=requested_end_date,
            calendar_type=calendar_type,
            ignored_dates=set(ignored_dates),
        ),
        observation_dates=set(observations),
    )
    observation_set = set(observations)
    return _CoverageWindow(
        normalized_observations=observations,
        ignored_dates=ignored_dates,
        required_dates=tuple(required_dates),
        missing_dates=tuple(value for value in required_dates if value not in observation_set),
        effective_dates=tuple(value for value in observations if requested_start_date <= value <= requested_end_date),
        baseline_applied=baseline_applied,
    )


def _date_bounds(values: tuple[date, ...]) -> tuple[date | None, date | None]:
    if not values:
        return None, None
    return values[0], values[-1]


def portfolio_ignored_dates(*, data_policy: object, portfolio_id: str) -> set[date]:
    ignore_days = getattr(data_policy, "ignore_days", None) if data_policy is not None else None
    if not ignore_days:
        return set()
    return {
        ignored_date
        for item in ignore_days
        if item.entity_type == "PORTFOLIO" and item.entity_id == portfolio_id
        for ignored_date in item.dates
    }


def _required_observation_dates(
    *,
    start: date,
    end: date,
    calendar_type: Literal["BUSINESS", "NATURAL"],
    ignored_dates: set[date],
) -> list[date]:
    required_dates: list[date] = []
    current = start
    while current <= end:
        if current not in ignored_dates and (calendar_type == "NATURAL" or current.weekday() < 5):
            required_dates.append(current)
        if current == end:
            break
        current += timedelta(days=1)
    return required_dates


def _apply_beginning_market_value_baseline(
    *,
    required_dates: list[date],
    observation_dates: set[date],
) -> tuple[list[date], bool]:
    if len(required_dates) < 2:
        return required_dates, False
    if required_dates[0] in observation_dates or required_dates[1] not in observation_dates:
        return required_dates, False
    return required_dates[1:], True


def _history_coverage_status(
    *,
    missing_dates: tuple[date, ...],
    required_dates: tuple[date, ...],
    effective_dates: tuple[date, ...],
    calendar_type: Literal["BUSINESS", "NATURAL"],
    trading_calendar: str | None,
) -> PerformanceHistoryCoverageStatus:
    if not effective_dates:
        return "unknown"
    if not missing_dates:
        return "complete"
    if _is_unattested_named_calendar_gap(
        calendar_type=calendar_type,
        trading_calendar=trading_calendar,
        missing_dates=missing_dates,
        required_dates=required_dates,
    ):
        return "unknown"
    return "partial"


def _is_unattested_named_calendar_gap(
    *,
    calendar_type: Literal["BUSINESS", "NATURAL"],
    trading_calendar: str | None,
    missing_dates: tuple[date, ...],
    required_dates: tuple[date, ...],
) -> bool:
    longest_missing_run = _longest_missing_run(missing_dates=missing_dates, required_dates=required_dates)
    return bool(
        calendar_type == "BUSINESS"
        and trading_calendar
        and len(missing_dates) == longest_missing_run
        and longest_missing_run <= _MAX_UNATTESTED_BUSINESS_CLOSURE_DAYS
    )


def _longest_missing_run(*, missing_dates: tuple[date, ...], required_dates: tuple[date, ...]) -> int:
    missing_set = set(missing_dates)
    longest = 0
    current = 0
    for required_date in required_dates:
        if required_date in missing_set:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _history_coverage_reason_codes(
    *,
    missing_dates: tuple[date, ...],
    required_dates: tuple[date, ...],
    effective_dates: tuple[date, ...],
    ignored_dates: frozenset[date],
    baseline_applied: bool,
) -> list[PerformanceHistoryCoverageReason]:
    reasons = _window_reason_codes(
        missing_dates=missing_dates,
        required_dates=required_dates,
        effective_dates=effective_dates,
    )
    reasons.extend(_policy_reason_codes(ignored_dates=ignored_dates, baseline_applied=baseline_applied))
    return reasons


def _window_reason_codes(
    *,
    missing_dates: tuple[date, ...],
    required_dates: tuple[date, ...],
    effective_dates: tuple[date, ...],
) -> list[PerformanceHistoryCoverageReason]:
    if not effective_dates:
        return ["no_observations_in_requested_window"]
    if not missing_dates:
        return ["covered_window_matches_requested_window"]
    return _missing_window_reason_codes(
        missing_dates=missing_dates,
        required_dates=required_dates,
        first_effective=effective_dates[0],
        last_effective=effective_dates[-1],
    )


def _missing_window_reason_codes(
    *,
    missing_dates: tuple[date, ...],
    required_dates: tuple[date, ...],
    first_effective: date,
    last_effective: date,
) -> list[PerformanceHistoryCoverageReason]:
    reasons: list[PerformanceHistoryCoverageReason] = []
    if _contains_date_before(missing_dates, first_effective):
        reasons.append("leading_history_missing")
    if _contains_date_between(missing_dates, first_effective, last_effective):
        reasons.append("interior_history_missing")
    if _contains_date_after(missing_dates, last_effective):
        reasons.append("trailing_history_missing")
    if not reasons and required_dates:
        reasons.append("interior_history_missing")
    return reasons


def _contains_date_before(values: tuple[date, ...], boundary: date) -> bool:
    return any(value < boundary for value in values)


def _contains_date_between(values: tuple[date, ...], start: date, end: date) -> bool:
    return any(start < value < end for value in values)


def _contains_date_after(values: tuple[date, ...], boundary: date) -> bool:
    return any(value > boundary for value in values)


def _policy_reason_codes(
    *,
    ignored_dates: frozenset[date],
    baseline_applied: bool,
) -> list[PerformanceHistoryCoverageReason]:
    reasons: list[PerformanceHistoryCoverageReason] = []
    if ignored_dates:
        reasons.append("explicit_ignored_dates_applied")
    if baseline_applied:
        reasons.append("beginning_market_value_baseline_applied")
    return reasons


def _status_reason_codes(
    *,
    status: PerformanceHistoryCoverageStatus,
    missing_dates: tuple[date, ...],
    effective_dates: tuple[date, ...],
    calendar_type: Literal["BUSINESS", "NATURAL"],
    trading_calendar: str | None,
) -> list[PerformanceHistoryCoverageReason]:
    if status == "unknown" and missing_dates and effective_dates and calendar_type == "BUSINESS" and trading_calendar:
        return ["venue_calendar_not_attested"]
    return []
