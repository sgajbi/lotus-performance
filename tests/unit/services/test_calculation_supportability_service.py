from datetime import date

from app.services.calculation_supportability_service import build_calculation_supportability


def test_calculation_supportability_marks_current_completed_calculation_ready() -> None:
    supportability = build_calculation_supportability(
        input_row_count=4,
        resolved_period_count=1,
        latest_observation_date=date(2026, 3, 31),
        report_end_date=date(2026, 3, 31),
        benchmark_row_count=2,
    )

    assert supportability.state == "ready"
    assert supportability.reason == "calculation_complete"
    assert supportability.freshness_bucket == "current"
    assert supportability.input_row_count == 4
    assert supportability.resolved_period_count == 1
    assert supportability.benchmark_row_count == 2


def test_calculation_supportability_marks_missing_periods_empty() -> None:
    supportability = build_calculation_supportability(
        input_row_count=4,
        resolved_period_count=0,
        latest_observation_date=date(2026, 3, 31),
        report_end_date=date(2026, 3, 31),
    )

    assert supportability.state == "empty"
    assert supportability.reason == "empty_resolved_periods"
    assert supportability.freshness_bucket == "current"


def test_calculation_supportability_marks_lagged_observations_stale() -> None:
    supportability = build_calculation_supportability(
        input_row_count=4,
        resolved_period_count=1,
        latest_observation_date=date(2026, 3, 29),
        report_end_date=date(2026, 3, 31),
    )

    assert supportability.state == "stale"
    assert supportability.reason == "stale_source_observations"
    assert supportability.freshness_bucket == "stale"
