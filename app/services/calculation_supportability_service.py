from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.models.responses import (
    PerformanceCalculationSupportability,
    PerformanceFreshnessBucket,
    PerformanceSupportabilityReason,
    PerformanceSupportabilityState,
)
from app.observability import record_calculation_supportability


def resolve_freshness_bucket(
    *,
    latest_observation_date: Any,
    report_end_date: Any,
) -> PerformanceFreshnessBucket:
    if latest_observation_date is None or report_end_date is None:
        return "unknown"
    latest = pd.Timestamp(latest_observation_date).date()
    expected = pd.Timestamp(report_end_date).date()
    if latest >= expected:
        return "current"
    if latest == expected:
        return "same_day"
    return "stale"


def build_calculation_supportability(
    *,
    input_row_count: int,
    resolved_period_count: int,
    report_end_date: date,
    latest_observation_date: Any,
    benchmark_row_count: int = 0,
    minimum_input_row_count: int = 1,
) -> PerformanceCalculationSupportability:
    freshness_bucket = resolve_freshness_bucket(
        latest_observation_date=latest_observation_date,
        report_end_date=report_end_date,
    )
    state: PerformanceSupportabilityState
    reason: PerformanceSupportabilityReason
    if input_row_count < minimum_input_row_count:
        state = "empty"
        reason = "insufficient_valuation_points"
    elif resolved_period_count <= 0:
        state = "empty"
        reason = "empty_resolved_periods"
    elif freshness_bucket == "stale":
        state = "stale"
        reason = "stale_source_observations"
    else:
        state = "ready"
        reason = "calculation_complete"

    return PerformanceCalculationSupportability(
        state=state,
        reason=reason,
        freshness_bucket=freshness_bucket,
        input_row_count=input_row_count,
        resolved_period_count=resolved_period_count,
        benchmark_row_count=benchmark_row_count,
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
