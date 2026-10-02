from datetime import date

import pytest

from app.services.performance_history_coverage_service import assess_performance_history_coverage
from core.errors import APIUnprocessableEntityError


def test_history_coverage_accepts_complete_natural_window():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 3),
        observation_dates=[date(2026, 1, 3), date(2026, 1, 1), date(2026, 1, 2)],
        calendar_type="NATURAL",
        trading_calendar=None,
    )

    assert coverage.status == "complete"
    assert coverage.calculation_basis == "requested_window"
    assert coverage.effective_start_date == date(2026, 1, 1)
    assert coverage.effective_end_date == date(2026, 1, 3)
    assert coverage.missing_required_observation_count == 0
    assert coverage.reason_codes == ["covered_window_matches_requested_window"]


def test_history_coverage_marks_sustained_leading_gap_as_partial_available_window():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2025, 1, 1),
        requested_end_date=date(2026, 1, 6),
        observation_dates=[date(2026, 1, 5), date(2026, 1, 6)],
        calendar_type="BUSINESS",
        trading_calendar="NYSE",
    )

    assert coverage.status == "partial"
    assert coverage.calculation_basis == "available_window"
    assert coverage.covered_start_date == date(2026, 1, 5)
    assert coverage.effective_start_date == date(2026, 1, 5)
    assert coverage.effective_end_date == date(2026, 1, 6)
    assert coverage.missing_required_observation_count > 250
    assert coverage.reason_codes == ["leading_history_missing"]


def test_history_coverage_keeps_isolated_business_gap_unknown_without_venue_attestation():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2025, 12, 31),
        requested_end_date=date(2026, 1, 5),
        observation_dates=[date(2025, 12, 31), date(2026, 1, 2), date(2026, 1, 5)],
        calendar_type="BUSINESS",
        trading_calendar="NYSE",
    )

    assert coverage.status == "unknown"
    assert coverage.calculation_basis == "available_window"
    assert coverage.missing_required_observation_dates_sample == [date(2026, 1, 1)]
    assert coverage.reason_codes == ["interior_history_missing", "venue_calendar_not_attested"]


def test_history_coverage_honors_explicitly_ignored_portfolio_date():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 3),
        observation_dates=[date(2026, 1, 1), date(2026, 1, 3)],
        calendar_type="NATURAL",
        trading_calendar=None,
        explicitly_ignored_dates=[date(2026, 1, 2)],
    )

    assert coverage.status == "complete"
    assert coverage.reason_codes == [
        "covered_window_matches_requested_window",
        "explicit_ignored_dates_applied",
    ]


def test_history_coverage_does_not_claim_out_of_window_ignore_date_was_applied():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 2),
        observation_dates=[date(2026, 1, 1), date(2026, 1, 2)],
        calendar_type="NATURAL",
        trading_calendar=None,
        explicitly_ignored_dates=[date(2025, 12, 31)],
    )

    assert coverage.status == "complete"
    assert coverage.reason_codes == ["covered_window_matches_requested_window"]


def test_history_coverage_accepts_immediate_beginning_market_value_baseline():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2024, 12, 31),
        requested_end_date=date(2025, 1, 3),
        observation_dates=[date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)],
        calendar_type="BUSINESS",
        trading_calendar="NYSE",
    )

    assert coverage.status == "complete"
    assert coverage.reason_codes == [
        "covered_window_matches_requested_window",
        "beginning_market_value_baseline_applied",
    ]


def test_history_coverage_reports_interior_and_trailing_gaps():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 7),
        observation_dates=[date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 4)],
        calendar_type="NATURAL",
        trading_calendar=None,
    )

    assert coverage.status == "partial"
    assert coverage.missing_required_observation_dates_sample == [
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    ]
    assert coverage.reason_codes == ["interior_history_missing", "trailing_history_missing"]


def test_history_coverage_treats_repeated_short_named_calendar_gaps_as_partial():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 9),
        observation_dates=[
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 5),
            date(2026, 1, 7),
            date(2026, 1, 9),
        ],
        calendar_type="BUSINESS",
        trading_calendar="NYSE",
    )

    assert coverage.status == "partial"
    assert coverage.missing_required_observation_count == 2
    assert coverage.missing_required_observation_dates_sample == [date(2026, 1, 6), date(2026, 1, 8)]
    assert coverage.reason_codes == ["interior_history_missing"]


def test_history_coverage_does_not_report_venue_ambiguity_when_no_natural_day_observations_exist():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 2),
        observation_dates=[],
        calendar_type="NATURAL",
        trading_calendar=None,
    )

    assert coverage.status == "unknown"
    assert coverage.reason_codes == ["no_observations_in_requested_window"]


def test_history_coverage_does_not_report_venue_ambiguity_when_named_calendar_has_no_observations():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 2),
        observation_dates=[],
        calendar_type="BUSINESS",
        trading_calendar="NYSE",
    )

    assert coverage.status == "unknown"
    assert coverage.reason_codes == ["no_observations_in_requested_window"]


def test_history_coverage_accepts_window_ending_at_python_maximum_date_without_overflow():
    coverage = assess_performance_history_coverage(
        requested_start_date=date(9999, 12, 30),
        requested_end_date=date.max,
        observation_dates=[date(9999, 12, 30), date.max],
        calendar_type="NATURAL",
        trading_calendar=None,
    )

    assert coverage.status == "complete"
    assert coverage.missing_required_observation_count == 0


def test_history_coverage_rejects_unreasonably_large_expansion_before_materializing_dates():
    with pytest.raises(APIUnprocessableEntityError) as exc_info:
        assess_performance_history_coverage(
            requested_start_date=date.min,
            requested_end_date=date.max,
            observation_dates=[date.min, date.max],
            calendar_type="NATURAL",
            trading_calendar=None,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "PERFORMANCE_HISTORY_COVERAGE_WINDOW_TOO_LARGE"
