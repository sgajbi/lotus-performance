from __future__ import annotations

from datetime import date
from typing import Any

from app.models.responses import (
    PerformanceCalculationSupportability,
    PerformanceFreshnessBucket,
    PerformanceSupportabilityReason,
    PerformanceSupportabilityState,
)
from app.models.source_quality import PerformanceSourceQualityEvidence
from app.observability import record_analytics_freshness_bucket, record_calculation_supportability
from app.services.analytics_observation_dates import normalize_observation_date


def resolve_freshness_bucket(
    *,
    latest_observation_date: Any,
    report_end_date: Any,
) -> PerformanceFreshnessBucket:
    if latest_observation_date is None or report_end_date is None:
        return "unknown"
    latest = normalize_observation_date(latest_observation_date)
    expected = normalize_observation_date(report_end_date)
    if latest >= expected:
        return "current"
    if latest == expected:
        return "same_day"
    return "stale"


def _has_degraded_source_quality(source_quality_evidence: PerformanceSourceQualityEvidence | None) -> bool:
    return source_quality_evidence is not None and source_quality_evidence.quality_state == "degraded"


def _supportability_state_and_reason(
    *,
    input_row_count: int,
    minimum_input_row_count: int,
    resolved_period_count: int,
    freshness_bucket: PerformanceFreshnessBucket,
    source_quality_evidence: PerformanceSourceQualityEvidence | None,
) -> tuple[PerformanceSupportabilityState, PerformanceSupportabilityReason]:
    if input_row_count < minimum_input_row_count:
        return "empty", "insufficient_valuation_points"
    if resolved_period_count <= 0:
        return "empty", "empty_resolved_periods"
    if freshness_bucket == "stale":
        return "stale", "stale_source_observations"
    if _has_degraded_source_quality(source_quality_evidence):
        return "degraded", "calculation_quality_issue"
    return "ready", "calculation_complete"


def build_calculation_supportability(
    *,
    input_row_count: int,
    resolved_period_count: int,
    report_end_date: date,
    latest_observation_date: Any,
    benchmark_row_count: int = 0,
    minimum_input_row_count: int = 1,
    source_quality_evidence: PerformanceSourceQualityEvidence | None = None,
) -> PerformanceCalculationSupportability:
    freshness_bucket = resolve_freshness_bucket(
        latest_observation_date=latest_observation_date,
        report_end_date=report_end_date,
    )
    state, reason = _supportability_state_and_reason(
        input_row_count=input_row_count,
        minimum_input_row_count=minimum_input_row_count,
        resolved_period_count=resolved_period_count,
        freshness_bucket=freshness_bucket,
        source_quality_evidence=source_quality_evidence,
    )

    return PerformanceCalculationSupportability(
        state=state,
        reason=reason,
        freshness_bucket=freshness_bucket,
        input_row_count=input_row_count,
        resolved_period_count=resolved_period_count,
        benchmark_row_count=benchmark_row_count,
        source_quality_evidence=source_quality_evidence,
    )


def record_supportability_metric(
    *,
    operation: str,
    supportability: PerformanceCalculationSupportability,
) -> None:
    record_calculation_supportability(
        operation=operation,
        supportability_state=supportability.state,
        reason=supportability.reason,
        freshness_bucket=supportability.freshness_bucket,
    )
    record_analytics_freshness_bucket(
        operation=operation,
        freshness_bucket=supportability.freshness_bucket,
        supportability_state=supportability.state,
    )
