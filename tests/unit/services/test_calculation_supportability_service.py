from datetime import date

from app.models.source_quality import PerformanceSourceQualityEvidence
from app.observability_contracts import PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS
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
