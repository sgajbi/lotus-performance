from __future__ import annotations

from typing import Any

import pandas as pd

from app.models.contribution_requests import ContributionRequest
from app.models.contribution_responses import (
    DailyContribution,
    PositionContribution,
    PositionContributionSeries,
    PositionDailyContribution,
)
from app.services.contribution_methodology import _as_numeric
from engine.schema import PortfolioColumns


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
            allocation_weights = pd.Series(0.0, index=position_slice.index)
        if allocation_weights.sum() <= 0:
            allocation_weights = pd.Series(1.0, index=position_slice.index)

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


def _build_hierarchy_from_adjusted_position_series(
    *,
    period_slice_df: pd.DataFrame,
    position_series: list[PositionContributionSeries],
    request: ContributionRequest,
) -> dict[str, Any]:
    """Builds hierarchy rows from the same adjusted daily position series emitted to clients."""
    summary = {
        "portfolio_contribution": 0.0,
        "coverage_mv_pct": 100.0,
        "weighting_scheme": request.weighting_scheme.value,
    }
    if request.currency_mode == "BOTH":
        summary["local_contribution"] = 0.0
        summary["fx_contribution"] = 0.0
    if not request.hierarchy or period_slice_df.empty or not position_series:
        return {"summary": summary, "levels": []}

    adjusted_records: list[dict[str, Any]] = []
    for series in position_series:
        for point in series.series:
            adjusted_records.append(
                {
                    "position_id": series.position_id,
                    PortfolioColumns.PERF_DATE.value: point.date,
                    "adjusted_contribution": point.contribution / 100,
                }
            )
    if not adjusted_records:
        return {"summary": summary, "levels": []}

    adjusted_df = pd.DataFrame(adjusted_records)
    meta_columns = ["position_id", PortfolioColumns.PERF_DATE.value, "daily_weight"]
    for level_name in request.hierarchy:
        if level_name not in meta_columns:
            meta_columns.append(level_name)

    daily_meta = period_slice_df.copy()
    daily_meta[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(daily_meta[PortfolioColumns.PERF_DATE.value]).dt.date
    for level_name in request.hierarchy:
        if level_name not in daily_meta.columns:
            daily_meta[level_name] = None
    daily_meta = daily_meta[meta_columns]

    merged_df = adjusted_df.merge(
        daily_meta,
        on=["position_id", PortfolioColumns.PERF_DATE.value],
        how="left",
    )
    for level_name in request.hierarchy:
        if request.emit.include_unclassified:
            merged_df[level_name] = merged_df[level_name].fillna("Unclassified")
        else:
            merged_df = merged_df[merged_df[level_name].notna()]

    if merged_df.empty:
        return {"summary": summary, "levels": []}

    observed_dates = {
        value
        for value in pd.to_datetime(period_slice_df[PortfolioColumns.PERF_DATE.value]).dt.date
        if value is not None
    }
    day_count = max(1, len(observed_dates))
    response_levels = []
    for index, level_name in enumerate(request.hierarchy):
        level_keys = request.hierarchy[: index + 1]
        level_agg = (
            merged_df.groupby(level_keys, dropna=False)
            .agg(
                contribution=("adjusted_contribution", "sum"),
                weight_sum=("daily_weight", "sum"),
            )
            .reset_index()
        )
        level_agg["weight_avg"] = level_agg["weight_sum"] / day_count
        rows = _build_hierarchy_rows(level_agg=level_agg, level_keys=level_keys, request=request)
        response_levels.append(
            {
                "level": index + 1,
                "name": level_name,
                "parent": request.hierarchy[index - 1] if index > 0 else None,
                "rows": rows,
            }
        )

    summary["portfolio_contribution"] = _as_numeric(adjusted_df["adjusted_contribution"].sum()) * 100
    return {"summary": summary, "levels": response_levels}


def _build_hierarchy_rows(
    *,
    level_agg: pd.DataFrame,
    level_keys: list[str],
    request: ContributionRequest,
) -> list[dict[str, Any]]:
    ordered = level_agg.copy()
    ordered["_abs_contribution"] = ordered["contribution"].abs()
    ordered = ordered.sort_values("_abs_contribution", ascending=False)

    threshold = max(0.0, request.emit.threshold_weight)
    explicit_rows = ordered[ordered["weight_avg"].abs() >= threshold]
    overflow_rows = ordered[ordered["weight_avg"].abs() < threshold]
    top_n = max(0, int(request.emit.top_n_per_level))
    if top_n and len(explicit_rows) > top_n:
        overflow_rows = pd.concat([overflow_rows, explicit_rows.iloc[top_n:]], ignore_index=True)
        explicit_rows = explicit_rows.iloc[:top_n]

    rows = [_hierarchy_row_to_response(row, level_keys=level_keys) for _, row in explicit_rows.iterrows()]
    if request.emit.include_other and not overflow_rows.empty:
        other_row: dict[str, Any] = {
            "key": {key: "Other" for key in level_keys},
            "contribution": _as_numeric(overflow_rows["contribution"].sum()) * 100,
            "weight_avg": _as_numeric(overflow_rows["weight_avg"].sum()) * 100,
            "children_count": int(len(overflow_rows)),
            "is_other": True,
        }
        rows.append(other_row)
    return rows


def _hierarchy_row_to_response(row: pd.Series, *, level_keys: list[str]) -> dict[str, Any]:
    return {
        "key": {key: row[key] for key in level_keys},
        "contribution": _as_numeric(row["contribution"]) * 100,
        "weight_avg": _as_numeric(row["weight_avg"]) * 100,
    }
