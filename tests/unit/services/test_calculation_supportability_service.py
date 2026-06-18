from datetime import date

from app.models.source_quality import PerformanceSourceQualityEvidence
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS
from app.services.calculation_supportability_service import (
    _empty_supportability_state_and_reason,
    _normalized_freshness_dates,
    _source_observation_is_current_or_newer,
    _supportability_state_and_reason,
    build_calculation_supportability,
    resolve_freshness_bucket,
)


def test_supportability_state_policy_prioritizes_insufficient_inputs() -> None:
    assert _supportability_state_and_reason(
        input_row_count=0,
        minimum_input_row_count=1,
        resolved_period_count=0,
        freshness_bucket="stale",
        source_quality_evidence=None,
    ) == ("empty", "insufficient_valuation_points")


def test_empty_supportability_state_policy_prioritizes_input_rows_before_periods() -> None:
    assert _empty_supportability_state_and_reason(
        input_row_count=0,
        minimum_input_row_count=1,
        resolved_period_count=0,
    ) == ("empty", "insufficient_valuation_points")
    assert _empty_supportability_state_and_reason(
        input_row_count=1,
        minimum_input_row_count=1,
        resolved_period_count=0,
    ) == ("empty", "empty_resolved_periods")
    assert (
        _empty_supportability_state_and_reason(
            input_row_count=1,
            minimum_input_row_count=1,
            resolved_period_count=1,
        )
        is None
    )


def test_freshness_bucket_policy_classifies_missing_current_and_stale_inputs() -> None:
    assert resolve_freshness_bucket(latest_observation_date=None, report_end_date=date(2026, 3, 31)) == "unknown"
    assert (
        resolve_freshness_bucket(latest_observation_date=date(2026, 3, 31), report_end_date=date(2026, 3, 31))
        == "current"
    )
    assert (
        resolve_freshness_bucket(latest_observation_date=date(2026, 4, 1), report_end_date=date(2026, 3, 31))
        == "current"
    )
    assert (
        resolve_freshness_bucket(latest_observation_date=date(2026, 3, 30), report_end_date=date(2026, 3, 31))
        == "stale"
    )


def test_normalized_freshness_dates_handles_missing_and_date_like_values() -> None:
    assert _normalized_freshness_dates(latest_observation_date=None, report_end_date=date(2026, 3, 31)) is None
    assert _normalized_freshness_dates(
        latest_observation_date="2026-03-31T12:00:00Z",
        report_end_date=date(2026, 3, 31),
    ) == (date(2026, 3, 31), date(2026, 3, 31))


def test_source_observation_is_current_or_newer_compares_normalized_dates() -> None:
    assert _source_observation_is_current_or_newer(
        latest_observation_date=date(2026, 3, 31),
        report_end_date=date(2026, 3, 31),
    )
    assert _source_observation_is_current_or_newer(
        latest_observation_date=date(2026, 4, 1),
        report_end_date=date(2026, 3, 31),
    )
    assert not _source_observation_is_current_or_newer(
        latest_observation_date=date(2026, 3, 30),
        report_end_date=date(2026, 3, 31),
    )


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
    assert supportability.metric_labels == PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS


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


def test_calculation_supportability_normalizes_date_like_freshness_inputs() -> None:
    supportability = build_calculation_supportability(
        input_row_count=4,
        resolved_period_count=1,
        latest_observation_date="2026-03-31T12:00:00Z",
        report_end_date=date(2026, 3, 31),
    )

    assert supportability.state == "ready"
    assert supportability.freshness_bucket == "current"


def test_calculation_supportability_marks_source_quality_degraded() -> None:
    evidence = PerformanceSourceQualityEvidence(
        source_product="PortfolioTimeseriesInput",
        source_owner="lotus-core",
        input_mode="stateful",
        quality_state="degraded",
        observation_count=3,
        valid_valuation_point_count=2,
        skipped_observation_count=1,
        unsupported_cashflow_count=1,
        source_conflict_count=0,
        latest_observation_date=date(2026, 3, 31),
        report_end_date=date(2026, 3, 31),
        warnings=["MISSING_VALUATION_POINTS", "UNSUPPORTED_CASHFLOW_LABELS"],
    )

    supportability = build_calculation_supportability(
        input_row_count=2,
        resolved_period_count=1,
        latest_observation_date=date(2026, 3, 31),
        report_end_date=date(2026, 3, 31),
        source_quality_evidence=evidence,
    )

    assert supportability.state == "degraded"
    assert supportability.reason == "calculation_quality_issue"
    assert supportability.source_quality_evidence == evidence
