from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.models.contribution_responses import AverageWeightMethodologyStatus, PositionContribution
from app.services.analytics_numeric import numeric_series, numeric_series_or_default, numeric_value
from app.services.analytics_observation_dates import observation_date_series
from engine.schema import PortfolioColumns

RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF = "OFF"
RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS = "CANDIDATE_PERIODS"


@dataclass(frozen=True)
class AverageWeightShadowCutoverAssessment:
    """Period-level rollout assessment for reset-aware average-weight promotion."""

    is_cutover_candidate: bool
    blocker_reason_codes: set[str]


def _to_basis_points(decimal_ratio: Any) -> int:
    """Converts a decimal-ratio delta into rounded basis points for audit reporting."""
    return int(round(decimal_ratio * 10000))


def _to_percentage_point_basis_points(percentage_point_delta: Any) -> int:
    """Converts a percentage-point delta into rounded basis points for audit reporting."""
    return int(round(percentage_point_delta * 100))


def _as_numeric(value: Any, default: Any = 0) -> Any:
    return numeric_value(value, default=default)


def _numeric_series_or_default(df: pd.DataFrame, column_name: str) -> pd.Series:
    return numeric_series_or_default(df, column_name)


def _calculate_reset_aware_average_weight_shadow(
    period_slice_df: pd.DataFrame,
    portfolio_period_slice_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int, int]:
    """Calculates a shadow average-weight view using reset-relative valid portfolio days.

    Domain meaning:
    the active contribution response still uses the simple arithmetic mean of daily weights.
    This helper computes the methodology candidate that contribution would use after RFC-043:

    - ignore pre-final-active-reset history
    - exclude no-investment days from the valid-day denominator
    - treat missing position rows on valid days as zero weight rather than shrinking the denominator
    """
    current_average_weights = (
        period_slice_df.groupby("position_id").agg(average_weight=("daily_weight", "mean")).reset_index()
    )
    if current_average_weights.empty:
        current_average_weights["reset_aware_average_weight_shadow"] = pd.Series(index=current_average_weights.index)
        return current_average_weights, 0, 0, 0

    required_columns = {PortfolioColumns.PERF_DATE.value, PortfolioColumns.NIP.value, PortfolioColumns.PERF_RESET.value}
    if portfolio_period_slice_df.empty or not required_columns.issubset(portfolio_period_slice_df.columns):
        current_average_weights["reset_aware_average_weight_shadow"] = current_average_weights["average_weight"]
        return current_average_weights, 0, 0, 0

    portfolio_window = portfolio_period_slice_df.copy()
    portfolio_window[PortfolioColumns.PERF_DATE.value] = observation_date_series(
        portfolio_window[PortfolioColumns.PERF_DATE.value]
    )
    portfolio_window = portfolio_window.sort_values(PortfolioColumns.PERF_DATE.value)

    active_reset_mask = numeric_series(portfolio_window[PortfolioColumns.PERF_RESET.value]) == 1
    if active_reset_mask.any():
        last_reset_index = portfolio_window[active_reset_mask].index[-1]
        portfolio_window = portfolio_window.loc[last_reset_index:]

    valid_portfolio_days = portfolio_window[numeric_series(portfolio_window[PortfolioColumns.NIP.value]) != 1][
        PortfolioColumns.PERF_DATE.value
    ]
    valid_day_count = int(valid_portfolio_days.nunique())

    if valid_day_count == 0:
        current_average_weights["reset_aware_average_weight_shadow"] = 0.0
    else:
        shadow_totals = (
            period_slice_df[
                observation_date_series(period_slice_df[PortfolioColumns.PERF_DATE.value]).isin(
                    set(valid_portfolio_days)
                )
            ]
            .groupby("position_id")
            .agg(weight_sum=("daily_weight", "sum"))
            .reset_index()
        )
        current_average_weights = current_average_weights.merge(shadow_totals, on="position_id", how="left")
        current_average_weights["weight_sum"] = current_average_weights["weight_sum"].fillna(0.0)
        current_average_weights["reset_aware_average_weight_shadow"] = (
            current_average_weights["weight_sum"] / valid_day_count
        )
        current_average_weights = current_average_weights.drop(columns=["weight_sum"])

    delta_position_count = int(
        (current_average_weights["average_weight"] - current_average_weights["reset_aware_average_weight_shadow"])
        .abs()
        .gt(1e-12)
        .sum()
    )
    absolute_shadow_delta = (
        current_average_weights["average_weight"] - current_average_weights["reset_aware_average_weight_shadow"]
    ).abs()
    max_shadow_delta_bp = _to_basis_points(absolute_shadow_delta.max()) if not absolute_shadow_delta.empty else 0
    sum_shadow_delta_bp = _to_basis_points(absolute_shadow_delta.sum()) if not absolute_shadow_delta.empty else 0
    return current_average_weights, delta_position_count, max_shadow_delta_bp, sum_shadow_delta_bp


def _calculate_average_weight_sum_residual_bp(position_contributions: list[PositionContribution]) -> int:
    """Measures how far emitted position average weights drift from a full 100% portfolio weight.

    Domain meaning:
    position average weights should normally add to 100%. Tiny residual drift can appear from
    floating-point arithmetic or allocation edge cases, but the response should make that residual
    explicit instead of assuming it away.
    """
    if not position_contributions:
        return 0

    total_average_weight = sum(
        _as_numeric(position_contribution.average_weight) for position_contribution in position_contributions
    )
    return _to_percentage_point_basis_points(abs(total_average_weight - 100.0))


def _classify_average_weight_shadow_period(max_shadow_delta_bp: int) -> str:
    """Classifies a period-level shadow delta into severity buckets for audit reporting."""
    if max_shadow_delta_bp >= 500:
        return "material"
    if max_shadow_delta_bp >= 101:
        return "warning"
    if max_shadow_delta_bp > 0:
        return "noise"
    return "none"


def _normalize_reset_aware_average_weight_mode(raw_mode: Any) -> str:
    """Normalizes the runtime rollout mode for reset-aware average-weight promotion."""
    normalized_mode = str(raw_mode or RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF).strip().upper()
    if normalized_mode in {
        RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF,
        RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS,
    }:
        return normalized_mode
    return RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF


def _calculate_average_weight_sum_residual_bp_from_ratio_series(average_weight_series: pd.Series) -> int:
    """Measures how far a ratio-based weight series drifts from a full 100% portfolio weight."""
    if average_weight_series.empty:
        return 0
    total_average_weight_percentage = numeric_series(average_weight_series, default=0.0).sum() * 100
    return _to_percentage_point_basis_points(abs(total_average_weight_percentage - 100.0))


def _calculate_promotion_ready_rate_bp(*, ready_periods: int, material_periods: int) -> int:
    """Summarizes how much of the observed material-shadow traffic is rollout-ready.

    Domain meaning:
    this metric is intentionally observational. It answers a simple rollout question: among
    periods with material reset-aware denominator pressure, what share is structurally clean enough
    to promote under the current guardrails.
    """
    if material_periods <= 0:
        return 0
    return round((ready_periods / material_periods) * 10000)


def _classify_average_weight_methodology_status(
    *,
    max_shadow_delta_bp: int,
    is_cutover_candidate: bool,
    is_promoted: bool,
    blocker_reason_codes: set[str],
) -> str:
    """Classifies the per-period reset-aware average-weight rollout state."""
    if max_shadow_delta_bp < 500:
        return "NO_MATERIAL_SHADOW"
    if is_promoted:
        return "PROMOTED"
    if is_cutover_candidate:
        return "PROMOTION_READY"
    if blocker_reason_codes:
        return "BLOCKED"
    return "UNDER_REVIEW"


def _build_average_weight_methodology_status(
    *,
    max_shadow_delta_bp: int,
    is_cutover_candidate: bool,
    is_promoted: bool,
    blocker_reason_codes: set[str],
) -> AverageWeightMethodologyStatus:
    """Maps reset-aware average-weight rollout state into the response DTO."""
    return AverageWeightMethodologyStatus(
        status=_classify_average_weight_methodology_status(
            max_shadow_delta_bp=max_shadow_delta_bp,
            is_cutover_candidate=is_cutover_candidate,
            is_promoted=is_promoted,
            blocker_reason_codes=blocker_reason_codes,
        ),
        max_shadow_delta_bp=max_shadow_delta_bp,
        is_material_shadow=max_shadow_delta_bp >= 500,
        is_cutover_candidate=is_cutover_candidate,
        is_promoted=is_promoted,
        blocker_reason_codes=sorted(blocker_reason_codes),
    )


def _is_average_weight_shadow_cutover_candidate(
    *,
    max_shadow_delta_bp: int,
    average_weight_sum_residual_bp: int,
    position_flow_residual_days: int,
    portfolio_reset_without_position_reset_days: int,
    position_reset_without_portfolio_reset_days: int,
    timeseries_total_delta_periods: int,
) -> bool:
    """Returns whether a period looks structurally ready for future denominator cutover analysis.

    Domain meaning:
    a material shadow delta alone is not enough. We only want to treat a slice as a serious
    cutover candidate when the surrounding bookkeeping and reconciliation signals are otherwise
    clean. That keeps us from mistaking unrelated flow or reset defects for denominator evidence.
    """
    return (
        max_shadow_delta_bp >= 500
        and average_weight_sum_residual_bp <= 1
        and position_flow_residual_days == 0
        and portfolio_reset_without_position_reset_days == 0
        and position_reset_without_portfolio_reset_days == 0
        and timeseries_total_delta_periods == 0
    )


def _classify_average_weight_shadow_cutover_blockers(
    *,
    max_shadow_delta_bp: int,
    average_weight_sum_residual_bp: int,
    position_flow_residual_days: int,
    portfolio_reset_without_position_reset_days: int,
    position_reset_without_portfolio_reset_days: int,
    timeseries_total_delta_periods: int,
) -> set[str]:
    """Returns the structural reasons a materially different weight period is not promotion-ready.

    Domain meaning:
    a material shadow delta is useful rollout evidence only when the surrounding bookkeeping is
    otherwise clean. These blocker labels make it explicit why a period was kept shadow-only:
    weight coverage drift, broken internal flow cancellation, reset-boundary misalignment, or
    timeseries reconciliation drift.
    """
    blockers: set[str] = set()
    if max_shadow_delta_bp < 500:
        return blockers
    if average_weight_sum_residual_bp > 1:
        blockers.add("weight_residual")
    if position_flow_residual_days > 0:
        blockers.add("flow_balance")
    if portfolio_reset_without_position_reset_days > 0 or position_reset_without_portfolio_reset_days > 0:
        blockers.add("reset_alignment")
    if timeseries_total_delta_periods > 0:
        blockers.add("timeseries_reconciliation")
    return blockers


def _assess_average_weight_shadow_cutover(
    *,
    max_shadow_delta_bp: int,
    average_weight_sum_residual_bp: int,
    position_flow_residual_days: int,
    portfolio_reset_without_position_reset_days: int,
    position_reset_without_portfolio_reset_days: int,
    timeseries_total_delta_periods: int,
) -> AverageWeightShadowCutoverAssessment:
    """Assesses whether a material reset-aware weight shadow is promotion-ready or blocked."""
    is_cutover_candidate = _is_average_weight_shadow_cutover_candidate(
        max_shadow_delta_bp=max_shadow_delta_bp,
        average_weight_sum_residual_bp=average_weight_sum_residual_bp,
        position_flow_residual_days=position_flow_residual_days,
        portfolio_reset_without_position_reset_days=portfolio_reset_without_position_reset_days,
        position_reset_without_portfolio_reset_days=position_reset_without_portfolio_reset_days,
        timeseries_total_delta_periods=timeseries_total_delta_periods,
    )
    if is_cutover_candidate:
        return AverageWeightShadowCutoverAssessment(
            is_cutover_candidate=True,
            blocker_reason_codes=set(),
        )

    return AverageWeightShadowCutoverAssessment(
        is_cutover_candidate=False,
        blocker_reason_codes=_classify_average_weight_shadow_cutover_blockers(
            max_shadow_delta_bp=max_shadow_delta_bp,
            average_weight_sum_residual_bp=average_weight_sum_residual_bp,
            position_flow_residual_days=position_flow_residual_days,
            portfolio_reset_without_position_reset_days=portfolio_reset_without_position_reset_days,
            position_reset_without_portfolio_reset_days=position_reset_without_portfolio_reset_days,
            timeseries_total_delta_periods=timeseries_total_delta_periods,
        ),
    )
