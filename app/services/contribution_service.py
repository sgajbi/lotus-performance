from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.contribution_analytics_requests import ContributionInputMode
from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    AverageWeightMethodologyStatus,
    ContributionResponse,
    DailyContribution,
    PositionContribution,
    PositionContributionSeries,
    PositionDailyContribution,
    SinglePeriodContributionResult,
)
from app.services.execution_lifecycle_service import (
    complete_execution_with_lineage,
    record_execution_failure,
)
from app.services.execution_registry import execution_registry
from core.envelope import Audit, Diagnostics, Meta
from core.periods import resolve_periods
from engine.config import EngineConfig
from engine.contribution import (
    _calculate_daily_instrument_contributions,
    _prepare_hierarchical_data,
    build_hierarchical_contribution_result,
)
from engine.diagnostics import EngineDiagnostics
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns

RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF = "OFF"
RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS = "CANDIDATE_PERIODS"


def _to_basis_points(decimal_ratio: Any) -> int:
    """Converts a decimal-ratio delta into rounded basis points for audit reporting."""
    return int(round(float(decimal_ratio) * 10000))


def _to_percentage_point_basis_points(percentage_point_delta: Any) -> int:
    """Converts a percentage-point delta into rounded basis points for audit reporting."""
    return int(round(float(percentage_point_delta) * 100))


def _as_numeric(value: Any, default: Any = 0) -> Any:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return numeric


def _numeric_series_or_default(df: pd.DataFrame, column_name: str) -> pd.Series:
    """Returns a numeric Series for a column, or a zero-filled fallback aligned to the frame index."""
    if column_name not in df.columns:
        return pd.Series(0, index=df.index, dtype=float)
    return pd.to_numeric(df[column_name], errors="coerce").fillna(0)


def _calculate_reset_relative_day_counts(portfolio_results_df: pd.DataFrame) -> tuple[int, int]:
    """Calculates reset-relative NIP and valid day counts from the portfolio engine frame."""
    if portfolio_results_df.empty:
        return 0, 0

    perf_reset_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value)
    nip_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.NIP.value)
    reset_rows = perf_reset_series == 1
    if reset_rows.any():
        relevant_df = portfolio_results_df.loc[reset_rows[reset_rows].index[-1] :]
        relevant_nip_series = nip_series.loc[relevant_df.index]
    else:
        relevant_df = portfolio_results_df
        relevant_nip_series = nip_series

    nip_days_since_last_reset = int(relevant_nip_series.sum())
    valid_days_since_last_reset = int(len(relevant_df) - nip_days_since_last_reset)
    return nip_days_since_last_reset, valid_days_since_last_reset


def _calculate_reset_characterization_counts(
    portfolio_results_df: pd.DataFrame,
) -> tuple[int, int, int, int, int, int, int]:
    """Calculates reset characterization counts from the portfolio engine frame."""
    if portfolio_results_df.empty:
        return 0, 0, 0, 0, 0, 0, 0

    active_reset_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value) == 1
    nctrl4_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.NCTRL_4.value) == 1
    account_reset_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.ACCOUNT_RESET.value) == 1
    sod_reset_mask = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.SOD_RESET.value) == 1
    shadow_overlap_mask = account_reset_mask & sod_reset_mask
    any_shadow_mask = account_reset_mask | sod_reset_mask
    nctrl4_exclusive_mask = nctrl4_mask & ~any_shadow_mask
    shadow_only_candidate_reset_mask = any_shadow_mask & ~active_reset_mask
    active_reset_with_shadow_mask = active_reset_mask & any_shadow_mask

    return (
        int(nctrl4_mask.sum()),
        int(nctrl4_exclusive_mask.sum()),
        int(account_reset_mask.sum()),
        int(sod_reset_mask.sum()),
        int(shadow_overlap_mask.sum()),
        int(shadow_only_candidate_reset_mask.sum()),
        int(active_reset_with_shadow_mask.sum()),
    )


def _calculate_reset_aware_period_portfolio_return(
    request: ContributionRequest,
    period_start_date,
    period_end_date,
    period_type,
) -> Any:
    """Calculates the portfolio return for a resolved contribution slice using engine reset semantics.

    Domain meaning:
    contribution must use the same episode-aware portfolio return that the TWR engine produces for
    the same slice. Multiplying daily returns across the window is incorrect once performance resets
    break the economic continuity of the path.
    """
    period_valuation_points = [
        valuation_point.model_dump()
        for valuation_point in request.portfolio_data.valuation_points
        if period_start_date <= valuation_point.perf_date <= period_end_date
    ]
    if not period_valuation_points:
        return 0.0

    period_engine_config = EngineConfig(
        performance_start_date=period_valuation_points[0]["perf_date"],
        report_start_date=period_start_date,
        report_end_date=period_end_date,
        metric_basis=request.portfolio_data.metric_basis,
        period_type=period_type,
        precision_mode=request.precision_mode,
        rounding_precision=request.rounding_precision,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )
    period_results_df = run_engine_for_valuation_points(
        period_valuation_points,
        period_engine_config,
        force_base_only=period_engine_config.currency_mode == "BOTH",
    )
    if period_results_df.empty:
        return 0.0

    return _as_numeric(period_results_df[PortfolioColumns.FINAL_CUM_ROR.value].iloc[-1] / 100)


def _count_carino_invalid_domain_days(portfolio_period_slice_df: pd.DataFrame) -> int:
    """Counts days where Carino smoothing leaves its valid logarithmic return domain.

    Domain meaning:
    Carino smoothing uses ``log(1 + r)``. Once a daily portfolio return reaches ``-100%`` or
    below, the linked gross return factor stops being positive and logarithmic smoothing is no
    longer economically or mathematically defensible for that period slice.
    """
    if portfolio_period_slice_df.empty or PortfolioColumns.DAILY_ROR.value not in portfolio_period_slice_df.columns:
        return 0

    daily_returns = pd.to_numeric(
        portfolio_period_slice_df[PortfolioColumns.DAILY_ROR.value],
        errors="coerce",
    )
    return int((1 + (daily_returns / 100) <= 0).sum())


def _build_portfolio_engine_diagnostics(portfolio_results_df: pd.DataFrame, effective_period_start) -> Diagnostics:
    """Maps portfolio-engine state already present in contribution inputs into shared diagnostics."""
    if portfolio_results_df.empty:
        return Diagnostics(nip_days=0, reset_days=0, effective_period_start=effective_period_start, notes=[])

    nip_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.NIP.value)
    nip_v1_series = _numeric_series_or_default(portfolio_results_df, "nip_rule_v1_shadow")
    nip_v2_series = _numeric_series_or_default(portfolio_results_df, "nip_rule_v2_shadow")
    perf_reset_series = _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value)
    (
        nctrl4_reset_days,
        nctrl4_exclusive_reset_days,
        account_reset_shadow_days,
        sod_reset_shadow_days,
        shadow_reset_overlap_days,
        shadow_only_candidate_reset_days,
        active_reset_with_shadow_days,
    ) = _calculate_reset_characterization_counts(portfolio_results_df)
    candidate_canonical_reset_days = int(
        (
            perf_reset_series.eq(1)
            | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.ACCOUNT_RESET.value).eq(1)
            | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.SOD_RESET.value).eq(1)
        ).sum()
    )
    reset_delta_days = int(
        (
            (
                perf_reset_series.eq(1)
                | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.ACCOUNT_RESET.value).eq(1)
                | _numeric_series_or_default(portfolio_results_df, PortfolioColumns.SOD_RESET.value).eq(1)
            )
            != perf_reset_series.eq(1)
        ).sum()
    )
    nip_days_since_last_reset, valid_days_since_last_reset = _calculate_reset_relative_day_counts(portfolio_results_df)

    diagnostics = EngineDiagnostics(
        nip_days=int(nip_series.sum()),
        nip_rule_delta_days=int((nip_v1_series != nip_v2_series).sum()),
        reset_days=int(perf_reset_series.sum()),
        nctrl4_reset_days=nctrl4_reset_days,
        nctrl4_exclusive_reset_days=nctrl4_exclusive_reset_days,
        account_reset_shadow_days=account_reset_shadow_days,
        sod_reset_shadow_days=sod_reset_shadow_days,
        shadow_reset_overlap_days=shadow_reset_overlap_days,
        shadow_only_candidate_reset_days=shadow_only_candidate_reset_days,
        active_reset_with_shadow_days=active_reset_with_shadow_days,
        candidate_canonical_reset_days=candidate_canonical_reset_days,
        reset_delta_days=reset_delta_days,
        nip_days_since_last_reset=nip_days_since_last_reset,
        valid_days_since_last_reset=valid_days_since_last_reset,
        effective_period_start=effective_period_start,
    )
    return Diagnostics.model_validate(
        {
            "nip_days": diagnostics.nip_days,
            "nip_rule_delta_days": diagnostics.nip_rule_delta_days,
            "reset_days": diagnostics.reset_days,
            "nctrl4_reset_days": diagnostics.nctrl4_reset_days,
            "nctrl4_exclusive_reset_days": diagnostics.nctrl4_exclusive_reset_days,
            "account_reset_shadow_days": diagnostics.account_reset_shadow_days,
            "sod_reset_shadow_days": diagnostics.sod_reset_shadow_days,
            "shadow_reset_overlap_days": diagnostics.shadow_reset_overlap_days,
            "shadow_only_candidate_reset_days": diagnostics.shadow_only_candidate_reset_days,
            "active_reset_with_shadow_days": diagnostics.active_reset_with_shadow_days,
            "candidate_canonical_reset_days": diagnostics.candidate_canonical_reset_days,
            "reset_delta_days": diagnostics.reset_delta_days,
            "nip_days_since_last_reset": diagnostics.nip_days_since_last_reset,
            "valid_days_since_last_reset": diagnostics.valid_days_since_last_reset,
            "effective_period_start": effective_period_start,
            "notes": [],
        }
    )


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
        current_average_weights["reset_aware_average_weight_shadow"] = pd.Series(dtype=float)
        return current_average_weights, 0, 0, 0

    required_columns = {PortfolioColumns.PERF_DATE.value, PortfolioColumns.NIP.value, PortfolioColumns.PERF_RESET.value}
    if portfolio_period_slice_df.empty or not required_columns.issubset(portfolio_period_slice_df.columns):
        current_average_weights["reset_aware_average_weight_shadow"] = current_average_weights["average_weight"]
        return current_average_weights, 0, 0, 0

    portfolio_window = portfolio_period_slice_df.sort_values(PortfolioColumns.PERF_DATE.value).copy()
    portfolio_window[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
        portfolio_window[PortfolioColumns.PERF_DATE.value]
    ).dt.date

    active_reset_mask = (
        pd.to_numeric(portfolio_window[PortfolioColumns.PERF_RESET.value], errors="coerce").fillna(0) == 1
    )
    if active_reset_mask.any():
        last_reset_index = portfolio_window[active_reset_mask].index[-1]
        portfolio_window = portfolio_window.loc[last_reset_index:]

    valid_portfolio_days = portfolio_window[
        pd.to_numeric(portfolio_window[PortfolioColumns.NIP.value], errors="coerce").fillna(0) != 1
    ][PortfolioColumns.PERF_DATE.value]
    valid_day_count = int(valid_portfolio_days.nunique())

    if valid_day_count == 0:
        current_average_weights["reset_aware_average_weight_shadow"] = 0.0
    else:
        shadow_totals = (
            period_slice_df[
                pd.to_datetime(period_slice_df[PortfolioColumns.PERF_DATE.value]).dt.date.isin(
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


def _calculate_grouped_return_reset_alignment_counts(
    instruments_df: pd.DataFrame,
    portfolio_results_df: pd.DataFrame,
) -> dict[str, int]:
    """Characterizes whether position-level reset days line up with portfolio reset days.

    Domain meaning:
    contribution relies on per-position engine runs plus the portfolio engine run. If those paths
    disagree on reset boundaries, contribution can still reconcile numerically in simple cases while
    telling a different state story from TWR. This helper keeps that alignment visible without
    changing behavior yet.
    """
    if instruments_df.empty or portfolio_results_df.empty:
        return {
            "portfolio_reset_days": 0,
            "position_reset_days": 0,
            "portfolio_reset_without_position_reset_days": 0,
            "position_reset_without_portfolio_reset_days": 0,
        }

    if PortfolioColumns.PERF_RESET.value not in instruments_df.columns:
        position_reset_dates: set[Any] = set()
    else:
        position_reset_dates = set(
            pd.to_datetime(
                instruments_df.loc[
                    _numeric_series_or_default(instruments_df, PortfolioColumns.PERF_RESET.value) == 1,
                    PortfolioColumns.PERF_DATE.value,
                ]
            ).dt.date
        )

    portfolio_reset_dates = set(
        pd.to_datetime(
            portfolio_results_df.loc[
                _numeric_series_or_default(portfolio_results_df, PortfolioColumns.PERF_RESET.value) == 1,
                PortfolioColumns.PERF_DATE.value,
            ]
        ).dt.date
    )

    return {
        "portfolio_reset_days": len(portfolio_reset_dates),
        "position_reset_days": len(position_reset_dates),
        "portfolio_reset_without_position_reset_days": len(portfolio_reset_dates - position_reset_dates),
        "position_reset_without_portfolio_reset_days": len(position_reset_dates - portfolio_reset_dates),
    }


def _calculate_position_flow_balance_counts(
    instruments_df: pd.DataFrame,
    portfolio_results_df: pd.DataFrame,
) -> dict[str, int]:
    """Counts and sizes dates where summed position-level flows fail to net to zero.

    Domain meaning:
    contribution should still calculate for real-world scoped books even when the visible position
    set is not flow-neutral on every date. When the stock leg and cash leg both sit inside the
    scoped position set, summed position flow on a date will normally net to zero. A non-zero
    residual therefore does not invalidate the engine; it characterizes that the current scoped
    slice includes net flow pressure that sits outside the visible offsetting legs. We track both
    the number of affected dates and the materiality of the largest/summed residual relative to the
    portfolio capital base for the date.
    """
    required_columns = {
        PortfolioColumns.PERF_DATE.value,
        PortfolioColumns.BOD_CF.value,
        PortfolioColumns.EOD_CF.value,
    }
    if instruments_df.empty or not required_columns.issubset(instruments_df.columns):
        return {
            "position_flow_residual_days": 0,
            "position_flow_residual_max_bp": 0,
            "position_flow_residual_sum_bp": 0,
        }

    position_flow_by_day = (
        pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: pd.to_datetime(
                    instruments_df[PortfolioColumns.PERF_DATE.value]
                ).dt.date,
                "position_flow": _numeric_series_or_default(instruments_df, PortfolioColumns.BOD_CF.value)
                + _numeric_series_or_default(instruments_df, PortfolioColumns.EOD_CF.value),
            }
        )
        .groupby(PortfolioColumns.PERF_DATE.value, dropna=False)["position_flow"]
        .sum()
    )

    if portfolio_results_df.empty or PortfolioColumns.PERF_DATE.value not in portfolio_results_df.columns:
        residual_days = int(position_flow_by_day.abs().gt(1e-9).sum())
        return {
            "position_flow_residual_days": residual_days,
            "position_flow_residual_max_bp": 0,
            "position_flow_residual_sum_bp": 0,
        }

    portfolio_capital_by_day = (
        pd.DataFrame(
            {
                PortfolioColumns.PERF_DATE.value: pd.to_datetime(
                    portfolio_results_df[PortfolioColumns.PERF_DATE.value]
                ).dt.date,
                "capital_base": _numeric_series_or_default(portfolio_results_df, PortfolioColumns.BEGIN_MV.value).abs()
                + _numeric_series_or_default(portfolio_results_df, PortfolioColumns.BOD_CF.value).abs(),
            }
        )
        .groupby(PortfolioColumns.PERF_DATE.value, dropna=False)["capital_base"]
        .max()
    )
    portfolio_capital_by_day = portfolio_capital_by_day.replace(0, pd.NA).fillna(1.0)

    residual_ratio_by_day = (
        position_flow_by_day.abs().reindex(portfolio_capital_by_day.index, fill_value=0.0) / portfolio_capital_by_day
    )

    return {
        "position_flow_residual_days": int(position_flow_by_day.abs().gt(1e-9).sum()),
        "position_flow_residual_max_bp": _to_basis_points(residual_ratio_by_day.max())
        if not residual_ratio_by_day.empty
        else 0,
        "position_flow_residual_sum_bp": _to_basis_points(residual_ratio_by_day.sum())
        if not residual_ratio_by_day.empty
        else 0,
    }


def _build_daily_contribution_series(period_slice_df: pd.DataFrame) -> list[DailyContribution]:
    totals_by_day = (
        period_slice_df.groupby(PortfolioColumns.PERF_DATE.value, dropna=False)
        .agg(total_contribution=("smoothed_contribution", "sum"))
        .reset_index()
        .sort_values(PortfolioColumns.PERF_DATE.value)
    )
    return [
        DailyContribution(
            date=row[PortfolioColumns.PERF_DATE.value],
            total_contribution=_as_numeric(row["total_contribution"]) * 100,
        )
        for _, row in totals_by_day.iterrows()
    ]


def _build_position_contribution_series(period_slice_df: pd.DataFrame) -> list[PositionContributionSeries]:
    position_id_column = "position_id"
    series_by_position: list[PositionContributionSeries] = []
    for position_id, position_slice in period_slice_df.sort_values(
        [position_id_column, PortfolioColumns.PERF_DATE.value]
    ).groupby(position_id_column, sort=True):
        series_by_position.append(
            PositionContributionSeries(
                position_id=str(position_id),
                series=[
                    PositionDailyContribution(
                        date=row[PortfolioColumns.PERF_DATE.value],
                        contribution=_as_numeric(row["smoothed_contribution"]) * 100,
                    )
                    for _, row in position_slice.iterrows()
                ],
            )
        )
    return series_by_position


def _build_residual_adjusted_position_timeseries(
    period_slice_df: pd.DataFrame,
    position_contributions: list[PositionContribution],
) -> list[PositionContributionSeries]:
    """Builds position daily series that reconcile to residual-adjusted period contribution totals.

    Domain meaning:
    once the service chooses a residual-adjusted period contribution per position, emitted daily
    series should tell the same story. We therefore spread each position's residual delta back
    across its daily path in proportion to absolute daily weight, using an equal split only when
    the period has no usable weight signal.
    """
    if period_slice_df.empty:
        return []

    target_total_by_position = {
        position_contribution.position_id: (position_contribution.total_contribution or 0.0) / 100
        for position_contribution in position_contributions
    }
    if not target_total_by_position:
        return []

    adjusted_rows: list[dict[str, Any]] = []
    for position_id, position_slice in period_slice_df.sort_values(
        ["position_id", PortfolioColumns.PERF_DATE.value]
    ).groupby("position_id", sort=True):
        target_total = target_total_by_position.get(str(position_id), 0.0)
        raw_total = _as_numeric(position_slice["smoothed_contribution"].sum())
        residual_delta = target_total - raw_total

        if "daily_weight" in position_slice.columns:
            allocation_weights = pd.to_numeric(position_slice["daily_weight"], errors="coerce").abs().fillna(0.0)
        else:
            allocation_weights = pd.Series(0.0, index=position_slice.index, dtype=float)
        if allocation_weights.sum() <= 0:
            allocation_weights = pd.Series(1.0, index=position_slice.index, dtype=float)

        normalized_weights = allocation_weights / allocation_weights.sum()
        adjusted_contributions = pd.to_numeric(position_slice["smoothed_contribution"], errors="coerce").fillna(0.0) + (
            normalized_weights * residual_delta
        )

        for row_index, (_, row) in enumerate(position_slice.iterrows()):
            adjusted_rows.append(
                {
                    "position_id": str(position_id),
                    PortfolioColumns.PERF_DATE.value: row[PortfolioColumns.PERF_DATE.value],
                    "adjusted_contribution": _as_numeric(adjusted_contributions.iloc[row_index]),
                }
            )

    adjusted_df = pd.DataFrame(adjusted_rows)
    adjusted_series_by_position: list[PositionContributionSeries] = []
    for position_id, position_slice in adjusted_df.groupby("position_id", sort=True):
        adjusted_series_by_position.append(
            PositionContributionSeries(
                position_id=str(position_id),
                series=[
                    PositionDailyContribution(
                        date=row[PortfolioColumns.PERF_DATE.value],
                        contribution=_as_numeric(row["adjusted_contribution"]) * 100,
                    )
                    for _, row in position_slice.sort_values(PortfolioColumns.PERF_DATE.value).iterrows()
                ],
            )
        )
    return adjusted_series_by_position


def _build_residual_adjusted_daily_contribution_series(
    position_series: list[PositionContributionSeries],
) -> list[DailyContribution]:
    """Aggregates residual-adjusted position series into a reconciled daily total series."""
    if not position_series:
        return []

    totals_by_date: dict[Any, float] = {}
    for position_series_entry in position_series:
        for daily_point in position_series_entry.series:
            totals_by_date[daily_point.date] = totals_by_date.get(daily_point.date, 0.0) + _as_numeric(
                daily_point.contribution
            )

    return [
        DailyContribution(date=series_date, total_contribution=totals_by_date[series_date])
        for series_date in sorted(totals_by_date)
    ]


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
    total_average_weight_percentage = (
        float(pd.to_numeric(average_weight_series, errors="coerce").fillna(0.0).sum()) * 100
    )
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


def calculate_contribution(
    request: ContributionRequest,
    *,
    input_fingerprint: str,
    calculation_hash: str,
    input_mode: ContributionInputMode = ContributionInputMode.STATELESS,
) -> ContributionResponse:
    active_settings = get_settings()
    reset_aware_average_weight_mode = _normalize_reset_aware_average_weight_mode(
        getattr(active_settings, "CONTRIBUTION_RESET_AWARE_AVERAGE_WEIGHT_MODE", RESET_AWARE_AVERAGE_WEIGHT_MODE_OFF)
    )
    execution_registry.mark_running(request.calculation_id)
    execution_registry.start_stage(request.calculation_id, "execution")

    periods_to_resolve = [analysis.period for analysis in request.analyses]
    inception_date = (
        request.portfolio_data.valuation_points[0].perf_date
        if request.portfolio_data.valuation_points
        else request.report_end_date
    )
    resolved_periods = resolve_periods(periods_to_resolve, request.report_end_date, inception_date)

    try:
        if not resolved_periods:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid periods could be resolved.")

        master_start_date = min(p.start_date for p in resolved_periods)
        master_end_date = max(p.end_date for p in resolved_periods)
        instruments_df, portfolio_results_df = _prepare_hierarchical_data(request)
        daily_contributions_df = _calculate_daily_instrument_contributions(
            instruments_df, portfolio_results_df, request.weighting_scheme, request.smoothing
        )
        daily_contributions_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(
            daily_contributions_df[PortfolioColumns.PERF_DATE.value]
        ).dt.date
        average_weight_sum_residual_bp = 0

        if request.hierarchy:
            results_by_period = {}
            average_weight_shadow_delta_positions = 0
            average_weight_shadow_delta_max_bp = 0
            average_weight_shadow_delta_sum_bp = 0
            average_weight_shadow_noise_periods = 0
            average_weight_shadow_warning_periods = 0
            average_weight_shadow_material_periods = 0
            average_weight_shadow_cutover_candidate_periods = 0
            average_weight_shadow_promoted_periods = 0
            average_weight_shadow_blocked_periods = 0
            average_weight_shadow_blocked_by_weight_residual_periods = 0
            average_weight_shadow_blocked_by_flow_balance_periods = 0
            average_weight_shadow_blocked_by_reset_alignment_periods = 0
            average_weight_shadow_blocked_by_timeseries_delta_periods = 0
            timeseries_total_delta_periods = 0
            for period in resolved_periods:
                period_slice_df = daily_contributions_df[
                    (daily_contributions_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                    & (daily_contributions_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
                ].copy()
                portfolio_period_slice_df = portfolio_results_df[
                    (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        >= period.start_date
                    )
                    & (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        <= period.end_date
                    )
                ]

                if period_slice_df.empty or portfolio_period_slice_df.empty:
                    continue

                total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
                    request,
                    period.start_date,
                    period.end_date,
                    period.name,
                )
                period_results = build_hierarchical_contribution_result(
                    period_slice_df,
                    request,
                    total_portfolio_return=total_portfolio_return,
                )
                results_by_period[period.name] = SinglePeriodContributionResult(
                    summary=period_results.get("summary"),
                    levels=period_results.get("levels"),
                )
        else:
            results_by_period = {}
            average_weight_shadow_delta_positions = 0
            average_weight_shadow_delta_max_bp = 0
            average_weight_shadow_delta_sum_bp = 0
            average_weight_shadow_noise_periods = 0
            average_weight_shadow_warning_periods = 0
            average_weight_shadow_material_periods = 0
            average_weight_shadow_cutover_candidate_periods = 0
            average_weight_shadow_promoted_periods = 0
            average_weight_shadow_blocked_periods = 0
            average_weight_shadow_blocked_by_weight_residual_periods = 0
            average_weight_shadow_blocked_by_flow_balance_periods = 0
            average_weight_shadow_blocked_by_reset_alignment_periods = 0
            average_weight_shadow_blocked_by_timeseries_delta_periods = 0
            timeseries_total_delta_periods = 0
            for period in resolved_periods:
                period_slice_df = daily_contributions_df[
                    (daily_contributions_df[PortfolioColumns.PERF_DATE.value] >= period.start_date)
                    & (daily_contributions_df[PortfolioColumns.PERF_DATE.value] <= period.end_date)
                ].copy()

                if period_slice_df.empty:
                    continue

                portfolio_period_slice_df = portfolio_results_df[
                    (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        >= period.start_date
                    )
                    & (
                        pd.to_datetime(portfolio_results_df[PortfolioColumns.PERF_DATE.value]).dt.date
                        <= period.end_date
                    )
                ]

                (
                    average_weight_shadow_df,
                    period_delta_positions,
                    period_max_shadow_delta_bp,
                    period_sum_shadow_delta_bp,
                ) = _calculate_reset_aware_average_weight_shadow(
                    period_slice_df,
                    portfolio_period_slice_df,
                )
                average_weight_shadow_delta_positions += period_delta_positions
                average_weight_shadow_delta_max_bp = max(
                    average_weight_shadow_delta_max_bp,
                    period_max_shadow_delta_bp,
                )
                average_weight_shadow_delta_sum_bp += period_sum_shadow_delta_bp
                shadow_period_bucket = _classify_average_weight_shadow_period(period_max_shadow_delta_bp)
                if shadow_period_bucket == "noise":
                    average_weight_shadow_noise_periods += 1
                elif shadow_period_bucket == "warning":
                    average_weight_shadow_warning_periods += 1
                elif shadow_period_bucket == "material":
                    average_weight_shadow_material_periods += 1

                period_position_reset_dates = set(
                    pd.to_datetime(
                        period_slice_df.loc[
                            _numeric_series_or_default(period_slice_df, PortfolioColumns.PERF_RESET.value) == 1,
                            PortfolioColumns.PERF_DATE.value,
                        ]
                    ).dt.date
                )
                period_portfolio_reset_dates = set(
                    pd.to_datetime(
                        portfolio_period_slice_df.loc[
                            _numeric_series_or_default(portfolio_period_slice_df, PortfolioColumns.PERF_RESET.value)
                            == 1,
                            PortfolioColumns.PERF_DATE.value,
                        ]
                    ).dt.date
                )
                period_position_flow_balance_counts = _calculate_position_flow_balance_counts(
                    period_slice_df,
                    portfolio_period_slice_df,
                )
                active_average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp_from_ratio_series(
                    average_weight_shadow_df["average_weight"]
                )
                use_reset_aware_average_weight = (
                    reset_aware_average_weight_mode == RESET_AWARE_AVERAGE_WEIGHT_MODE_CANDIDATE_PERIODS
                    and _is_average_weight_shadow_cutover_candidate(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        average_weight_sum_residual_bp=active_average_weight_sum_residual_bp,
                        position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                        portfolio_reset_without_position_reset_days=len(
                            period_portfolio_reset_dates - period_position_reset_dates
                        ),
                        position_reset_without_portfolio_reset_days=len(
                            period_position_reset_dates - period_portfolio_reset_dates
                        ),
                        timeseries_total_delta_periods=0,
                    )
                )
                selected_average_weight_column = (
                    "reset_aware_average_weight_shadow" if use_reset_aware_average_weight else "average_weight"
                )
                if use_reset_aware_average_weight:
                    average_weight_shadow_promoted_periods += 1

                totals = (
                    period_slice_df.groupby("position_id")
                    .agg(
                        total_contribution=("smoothed_contribution", "sum"),
                        local_contribution=("smoothed_local_contribution", "sum"),
                    )
                    .reset_index()
                ).merge(
                    average_weight_shadow_df[["position_id", "average_weight", "reset_aware_average_weight_shadow"]],
                    on="position_id",
                    how="left",
                )
                totals["selected_average_weight"] = totals[selected_average_weight_column]

                total_portfolio_return = _calculate_reset_aware_period_portfolio_return(
                    request,
                    period.start_date,
                    period.end_date,
                    period.name,
                )
                sum_of_contributions = _as_numeric(totals["total_contribution"].sum())
                residual = total_portfolio_return - sum_of_contributions
                total_avg_weight = _as_numeric(totals["selected_average_weight"].sum())

                if total_avg_weight > 0 and request.smoothing.method == "CARINO":
                    totals["total_contribution"] += residual * (totals["selected_average_weight"] / total_avg_weight)

                totals["fx_contribution"] = totals["total_contribution"] - totals["local_contribution"]

                position_contributions = [
                    PositionContribution(
                        position_id=row["position_id"],
                        total_contribution=_as_numeric(row["total_contribution"]) * 100,
                        average_weight=_as_numeric(row["selected_average_weight"]) * 100,
                        total_return=0,
                        local_contribution=_as_numeric(row.get("local_contribution", 0)) * 100,
                        fx_contribution=_as_numeric(row.get("fx_contribution", 0)) * 100,
                    )
                    for _, row in totals.iterrows()
                ]
                average_weight_sum_residual_bp = max(
                    average_weight_sum_residual_bp,
                    _calculate_average_weight_sum_residual_bp(position_contributions),
                )

                position_series = (
                    _build_residual_adjusted_position_timeseries(period_slice_df, position_contributions)
                    if request.emit.by_position_timeseries or request.emit.timeseries
                    else []
                )
                daily_series = (
                    _build_residual_adjusted_daily_contribution_series(position_series)
                    if request.emit.timeseries
                    else None
                )
                emitted_position_series = position_series if request.emit.by_position_timeseries else None
                period_average_weight_sum_residual_bp = _calculate_average_weight_sum_residual_bp(
                    position_contributions
                )
                period_timeseries_total_delta_periods = 0
                period_total_contribution = sum(pc.total_contribution for pc in position_contributions)
                if daily_series is not None:
                    daily_timeseries_total = sum(point.total_contribution for point in daily_series)
                    if abs(daily_timeseries_total - period_total_contribution) > 1e-9:
                        period_timeseries_total_delta_periods = 1
                        timeseries_total_delta_periods += 1
                period_cutover_blockers: set[str] = set()
                if _is_average_weight_shadow_cutover_candidate(
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                    position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                    portfolio_reset_without_position_reset_days=len(
                        period_portfolio_reset_dates - period_position_reset_dates
                    ),
                    position_reset_without_portfolio_reset_days=len(
                        period_position_reset_dates - period_portfolio_reset_dates
                    ),
                    timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                ):
                    average_weight_shadow_cutover_candidate_periods += 1
                    period_is_cutover_candidate = True
                else:
                    period_is_cutover_candidate = False
                    period_cutover_blockers = _classify_average_weight_shadow_cutover_blockers(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        average_weight_sum_residual_bp=period_average_weight_sum_residual_bp,
                        position_flow_residual_days=period_position_flow_balance_counts["position_flow_residual_days"],
                        portfolio_reset_without_position_reset_days=len(
                            period_portfolio_reset_dates - period_position_reset_dates
                        ),
                        position_reset_without_portfolio_reset_days=len(
                            period_position_reset_dates - period_portfolio_reset_dates
                        ),
                        timeseries_total_delta_periods=period_timeseries_total_delta_periods,
                    )
                    if period_cutover_blockers:
                        average_weight_shadow_blocked_periods += 1
                    if "weight_residual" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_weight_residual_periods += 1
                    if "flow_balance" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_flow_balance_periods += 1
                    if "reset_alignment" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_reset_alignment_periods += 1
                    if "timeseries_reconciliation" in period_cutover_blockers:
                        average_weight_shadow_blocked_by_timeseries_delta_periods += 1
                period_methodology_status = AverageWeightMethodologyStatus(
                    status=_classify_average_weight_methodology_status(
                        max_shadow_delta_bp=period_max_shadow_delta_bp,
                        is_cutover_candidate=period_is_cutover_candidate,
                        is_promoted=use_reset_aware_average_weight,
                        blocker_reason_codes=period_cutover_blockers,
                    ),
                    max_shadow_delta_bp=period_max_shadow_delta_bp,
                    is_material_shadow=period_max_shadow_delta_bp >= 500,
                    is_cutover_candidate=period_is_cutover_candidate,
                    is_promoted=use_reset_aware_average_weight,
                    blocker_reason_codes=sorted(period_cutover_blockers),
                )
                results_by_period[period.name] = SinglePeriodContributionResult(
                    total_portfolio_return=total_portfolio_return * 100,
                    total_contribution=period_total_contribution,
                    position_contributions=position_contributions,
                    timeseries=daily_series,
                    by_position_timeseries=emitted_position_series,
                    average_weight_methodology_status=period_methodology_status,
                )
    except HTTPException as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=str(exc.detail),
            execution_stage_started=True,
        )
        raise
    except Exception as exc:
        record_execution_failure(
            calculation_id=request.calculation_id,
            message=f"An unexpected error occurred during contribution calculation: {str(exc)}",
            execution_stage_started=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during contribution calculation: {str(exc)}",
        ) from exc

    meta = Meta(
        calculation_id=request.calculation_id,
        engine_version=active_settings.APP_VERSION,
        precision_mode=request.precision_mode,
        calendar=request.calendar,
        annualization=request.annualization,
        periods={
            "requested": [p.value for p in periods_to_resolve],
            "master_start": str(master_start_date),
            "master_end": str(master_end_date),
        },
        input_fingerprint=input_fingerprint,
        calculation_hash=calculation_hash,
        report_ccy=request.report_ccy,
    )
    diagnostics = _build_portfolio_engine_diagnostics(portfolio_results_df, master_start_date)
    carino_invalid_domain_days = (
        _count_carino_invalid_domain_days(portfolio_results_df) if request.smoothing.method == "CARINO" else 0
    )
    reset_alignment_counts = _calculate_grouped_return_reset_alignment_counts(instruments_df, portfolio_results_df)
    position_flow_balance_counts = _calculate_position_flow_balance_counts(instruments_df, portfolio_results_df)
    average_weight_shadow_promotion_ready_rate_bp = _calculate_promotion_ready_rate_bp(
        ready_periods=average_weight_shadow_cutover_candidate_periods,
        material_periods=average_weight_shadow_material_periods,
    )
    if average_weight_shadow_delta_max_bp >= 500:
        diagnostics.notes.append(
            "Reset-aware average-weight shadow differs from the active mean-weight output for "
            f"{average_weight_shadow_delta_positions} position-period rows."
        )
        diagnostics.notes.append(
            "Reset-aware average-weight shadow differs materially from the active average-weight "
            f"output, with a maximum delta of {average_weight_shadow_delta_max_bp} basis points."
        )
    elif average_weight_shadow_delta_positions > 0:
        diagnostics.notes.append(
            "Reset-aware average-weight shadow differs from the active mean-weight output for "
            f"{average_weight_shadow_delta_positions} position-period rows. The maximum delta was "
            f"{average_weight_shadow_delta_max_bp} basis points, which is still under characterization."
        )
    if average_weight_shadow_cutover_candidate_periods > 0:
        diagnostics.notes.append(
            "Some periods show material reset-aware average-weight pressure while the surrounding "
            "bookkeeping remains clean. Those periods are strong candidates for a future denominator "
            f"cutover study ({average_weight_shadow_cutover_candidate_periods} periods)."
        )
    if average_weight_shadow_material_periods > 0:
        diagnostics.notes.append(
            "Reset-aware average-weight rollout readiness is currently "
            f"{average_weight_shadow_promotion_ready_rate_bp} basis points of material-shadow periods "
            f"({average_weight_shadow_cutover_candidate_periods} of {average_weight_shadow_material_periods})."
        )
    if average_weight_shadow_promoted_periods > 0:
        diagnostics.notes.append(
            "Reset-aware average-weight promotion was applied for "
            f"{average_weight_shadow_promoted_periods} periods under the controlled rollout mode."
        )
    if average_weight_shadow_blocked_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods remained shadow-only because one or "
            "more rollout guardrails were not yet clean "
            f"({average_weight_shadow_blocked_periods} periods)."
        )
    if average_weight_shadow_blocked_by_weight_residual_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because emitted "
            "position weights did not sum cleanly to 100%."
        )
    if average_weight_shadow_blocked_by_flow_balance_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because "
            "position-level stock and cash legs did not cancel cleanly."
        )
    if average_weight_shadow_blocked_by_reset_alignment_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because "
            "portfolio and position reset boundaries were not aligned."
        )
    if average_weight_shadow_blocked_by_timeseries_delta_periods > 0:
        diagnostics.notes.append(
            "Some material reset-aware average-weight periods were kept shadow-only because emitted "
            "daily contribution series still drifted from the residual-adjusted period total."
        )
    if average_weight_sum_residual_bp > 1:
        diagnostics.notes.append(
            "Emitted position average weights do not sum to 100% exactly; the maximum residual was "
            f"{average_weight_sum_residual_bp} basis points."
        )
    if carino_invalid_domain_days > 0:
        diagnostics.notes.append(
            "Carino smoothing fell back to raw daily contribution arithmetic on "
            f"{carino_invalid_domain_days} portfolio days because the linked gross return factor "
            "left the valid logarithmic domain."
        )
    if (
        reset_alignment_counts["portfolio_reset_without_position_reset_days"] > 0
        or reset_alignment_counts["position_reset_without_portfolio_reset_days"] > 0
    ):
        diagnostics.notes.append(
            "Portfolio and position reset boundaries differ on some contribution dates; "
            "grouped-return alignment remains under characterization."
        )
    if position_flow_balance_counts["position_flow_residual_max_bp"] > 10:
        diagnostics.notes.append(
            "Summed position-level cash flows show a materially non-flow-neutral scoped slice on "
            f"{position_flow_balance_counts['position_flow_residual_days']} dates. This means the visible "
            "position set is not carrying both offsetting legs inside the current scope, so contribution "
            "is being explained on a partial flow story rather than a fully self-cancelling internal book. "
            f"The maximum residual was {position_flow_balance_counts['position_flow_residual_max_bp']} basis points "
            "of portfolio capital."
        )
    elif position_flow_balance_counts["position_flow_residual_days"] > 0:
        diagnostics.notes.append(
            "Summed position-level cash flows did not net to zero on "
            f"{position_flow_balance_counts['position_flow_residual_days']} dates. This looks like a small "
            "non-flow-neutral scoped slice rather than a material flow imbalance, but it should still be "
            f"reviewed. The maximum residual was {position_flow_balance_counts['position_flow_residual_max_bp']} "
            "basis points of portfolio capital."
        )
    if timeseries_total_delta_periods > 0:
        diagnostics.notes.append(
            "Some emitted daily contribution series remain raw path outputs and do not sum to the "
            "residual-adjusted period total for reset-heavy slices."
        )
    audit = Audit(
        counts={
            "input_positions": len(request.positions_data),
            "average_weight_shadow_delta_positions": average_weight_shadow_delta_positions,
            "average_weight_shadow_delta_max_bp": average_weight_shadow_delta_max_bp,
            "average_weight_shadow_delta_sum_bp": average_weight_shadow_delta_sum_bp,
            "average_weight_shadow_noise_periods": average_weight_shadow_noise_periods,
            "average_weight_shadow_warning_periods": average_weight_shadow_warning_periods,
            "average_weight_shadow_material_periods": average_weight_shadow_material_periods,
            "average_weight_shadow_cutover_candidate_periods": average_weight_shadow_cutover_candidate_periods,
            "average_weight_shadow_promotion_ready_rate_bp": average_weight_shadow_promotion_ready_rate_bp,
            "average_weight_shadow_promoted_periods": average_weight_shadow_promoted_periods,
            "average_weight_shadow_blocked_periods": average_weight_shadow_blocked_periods,
            "average_weight_shadow_blocked_by_weight_residual_periods": (
                average_weight_shadow_blocked_by_weight_residual_periods
            ),
            "average_weight_shadow_blocked_by_flow_balance_periods": (
                average_weight_shadow_blocked_by_flow_balance_periods
            ),
            "average_weight_shadow_blocked_by_reset_alignment_periods": (
                average_weight_shadow_blocked_by_reset_alignment_periods
            ),
            "average_weight_shadow_blocked_by_timeseries_delta_periods": (
                average_weight_shadow_blocked_by_timeseries_delta_periods
            ),
            "average_weight_sum_residual_bp": average_weight_sum_residual_bp,
            "carino_invalid_domain_days": carino_invalid_domain_days,
            "timeseries_total_delta_periods": timeseries_total_delta_periods,
            **reset_alignment_counts,
            **position_flow_balance_counts,
        }
    )

    response_model = ContributionResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        input_mode=input_mode,
        results_by_period=results_by_period,
        meta=meta,
        diagnostics=diagnostics,
        audit=audit,
    )

    complete_execution_with_lineage(
        calculation_id=request.calculation_id,
        calculation_type="Contribution",
        request_model=request,
        response_model=response_model,
        execution_details={"input_positions": len(request.positions_data)},
        calculation_details={
            "portfolio_twr.csv": portfolio_results_df,
            "daily_contributions.csv": daily_contributions_df,
        },
    )
    return response_model
