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
from app.services.analytics_numeric import numeric_series
from app.services.analytics_observation_dates import observation_date_series, observation_date_set
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

    target_total_by_position = _target_total_contribution_by_position(position_contributions)
    if not target_total_by_position:
        return []

    adjusted_rows = _residual_adjusted_position_timeseries_rows(
        period_slice_df,
        target_total_by_position=target_total_by_position,
    )
    return _position_contribution_series_from_adjusted_rows(adjusted_rows)


def _target_total_contribution_by_position(
    position_contributions: list[PositionContribution],
) -> dict[str, float]:
    return {
        position_contribution.position_id: (position_contribution.total_contribution or 0.0) / 100
        for position_contribution in position_contributions
    }


def _residual_adjusted_position_timeseries_rows(
    period_slice_df: pd.DataFrame,
    *,
    target_total_by_position: dict[str, float],
) -> list[dict[str, Any]]:
    adjusted_rows: list[dict[str, Any]] = []
    for position_id, position_slice in period_slice_df.sort_values(
        ["position_id", PortfolioColumns.PERF_DATE.value]
    ).groupby("position_id", sort=True):
        adjusted_rows.extend(
            _residual_adjusted_position_rows(
                position_id=str(position_id),
                position_slice=position_slice,
                target_total=target_total_by_position.get(str(position_id), 0.0),
            )
        )
    return adjusted_rows


def _position_contribution_series_from_adjusted_rows(
    adjusted_rows: list[dict[str, Any]],
) -> list[PositionContributionSeries]:
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


def _residual_adjusted_position_rows(
    *,
    position_id: str,
    position_slice: pd.DataFrame,
    target_total: float,
) -> list[dict[str, Any]]:
    raw_total = _as_numeric(position_slice["smoothed_contribution"].sum())
    residual_delta = target_total - raw_total

    if "daily_weight" in position_slice.columns:
        allocation_weights = numeric_series(position_slice["daily_weight"], default=0.0).abs()
    else:
        allocation_weights = pd.Series(0.0, index=position_slice.index)
    if allocation_weights.sum() <= 0:
        allocation_weights = pd.Series(1.0, index=position_slice.index)

    normalized_weights = allocation_weights / allocation_weights.sum()
    adjusted_contributions = numeric_series(position_slice["smoothed_contribution"], default=0.0) + (
        normalized_weights * residual_delta
    )
    return [
        {
            "position_id": position_id,
            PortfolioColumns.PERF_DATE.value: row[PortfolioColumns.PERF_DATE.value],
            "adjusted_contribution": _as_numeric(adjusted_contributions.iloc[row_index]),
        }
        for row_index, (_, row) in enumerate(position_slice.iterrows())
    ]


def _build_residual_adjusted_daily_contribution_series(
    position_series: list[PositionContributionSeries],
) -> list[DailyContribution]:
    """Aggregates residual-adjusted position series into a reconciled daily total series."""
    if not position_series:
        return []

    totals_by_date = _residual_adjusted_daily_totals_by_date(position_series)
    return [
        DailyContribution(date=series_date, total_contribution=totals_by_date[series_date])
        for series_date in sorted(totals_by_date)
    ]


def _residual_adjusted_daily_totals_by_date(
    position_series: list[PositionContributionSeries],
) -> dict[Any, float]:
    totals_by_date: dict[Any, float] = {}
    for position_series_entry in position_series:
        for daily_point in position_series_entry.series:
            totals_by_date[daily_point.date] = totals_by_date.get(daily_point.date, 0.0) + _as_numeric(
                daily_point.contribution
            )
    return totals_by_date


def _build_hierarchy_from_adjusted_position_series(
    *,
    period_slice_df: pd.DataFrame,
    position_series: list[PositionContributionSeries],
    position_average_weights: pd.DataFrame | None = None,
    request: ContributionRequest,
) -> dict[str, Any]:
    """Builds hierarchy rows from the same adjusted daily position series emitted to clients."""
    summary = _initial_hierarchy_summary(request)
    if not _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request,
    ):
        return {"summary": summary, "levels": []}

    prepared_frames = _prepared_adjusted_hierarchy_frames(
        period_slice_df=period_slice_df,
        position_series=position_series,
        position_average_weights=position_average_weights,
        request=request,
    )
    if prepared_frames is None:
        return {"summary": summary, "levels": []}
    adjusted_df, merged_df = prepared_frames

    observed_dates = observation_date_set(period_slice_df[PortfolioColumns.PERF_DATE.value])
    day_count = max(1, len(observed_dates))
    response_levels = _build_hierarchy_response_levels(merged_df=merged_df, day_count=day_count, request=request)

    summary["portfolio_contribution"] = _as_numeric(adjusted_df["adjusted_contribution"].sum()) * 100
    return {"summary": summary, "levels": response_levels}


def _has_adjusted_hierarchy_inputs(
    *,
    period_slice_df: pd.DataFrame,
    position_series: list[PositionContributionSeries],
    request: ContributionRequest,
) -> bool:
    return bool(request.hierarchy) and not period_slice_df.empty and bool(position_series)


def _prepared_adjusted_hierarchy_frames(
    *,
    period_slice_df: pd.DataFrame,
    position_series: list[PositionContributionSeries],
    position_average_weights: pd.DataFrame | None = None,
    request: ContributionRequest,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    adjusted_records = _adjusted_position_hierarchy_records(position_series)
    if not adjusted_records:
        return None

    adjusted_df = pd.DataFrame(adjusted_records)
    daily_meta = _daily_hierarchy_metadata(
        period_slice_df,
        hierarchy_levels=request.hierarchy or [],
        position_average_weights=position_average_weights,
    )
    merged_df = adjusted_df.merge(
        daily_meta,
        on=["position_id", PortfolioColumns.PERF_DATE.value],
        how="left",
    )
    merged_df = _apply_hierarchy_unclassified_policy(merged_df, request=request)
    if merged_df.empty:
        return None
    return adjusted_df, merged_df


def _initial_hierarchy_summary(request: ContributionRequest) -> dict[str, Any]:
    summary = {
        "portfolio_contribution": 0.0,
        "coverage_mv_pct": 100.0,
        "weighting_scheme": request.weighting_scheme.value,
    }
    if request.currency_mode == "BOTH":
        summary["local_contribution"] = 0.0
        summary["fx_contribution"] = 0.0
    return summary


def _adjusted_position_hierarchy_records(
    position_series: list[PositionContributionSeries],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for series in position_series:
        for point in series.series:
            records.append(
                {
                    "position_id": series.position_id,
                    PortfolioColumns.PERF_DATE.value: point.date,
                    "adjusted_contribution": point.contribution / 100,
                }
            )
    return records


def _daily_hierarchy_metadata(
    period_slice_df: pd.DataFrame,
    *,
    hierarchy_levels: list[str],
    position_average_weights: pd.DataFrame | None = None,
) -> pd.DataFrame:
    meta_columns = _hierarchy_metadata_columns(hierarchy_levels)
    daily_meta = period_slice_df.copy()
    for level_name in hierarchy_levels:
        if level_name not in daily_meta.columns:
            daily_meta[level_name] = None
    daily_meta[PortfolioColumns.PERF_DATE.value] = observation_date_series(daily_meta[PortfolioColumns.PERF_DATE.value])
    if position_average_weights is not None and not position_average_weights.empty:
        selected_weights = position_average_weights.rename(columns={"selected_average_weight": "daily_weight"})
        daily_meta = daily_meta.drop(columns=["daily_weight"], errors="ignore").merge(
            selected_weights[["position_id", "daily_weight"]],
            on="position_id",
            how="left",
        )
        daily_meta["daily_weight"] = numeric_series(daily_meta["daily_weight"], default=0.0)
    return daily_meta[meta_columns]


def _hierarchy_metadata_columns(hierarchy_levels: list[str]) -> list[str]:
    meta_columns = ["position_id", PortfolioColumns.PERF_DATE.value, "daily_weight"]
    for level_name in hierarchy_levels:
        if level_name not in meta_columns:
            meta_columns.append(level_name)
    return meta_columns


def _apply_hierarchy_unclassified_policy(
    merged_df: pd.DataFrame,
    *,
    request: ContributionRequest,
) -> pd.DataFrame:
    filtered_df = merged_df.copy()
    for level_name in request.hierarchy or []:
        if request.emit.include_unclassified:
            filtered_df[level_name] = filtered_df[level_name].fillna("Unclassified")
        else:
            filtered_df = filtered_df[filtered_df[level_name].notna()]
    return filtered_df


def _build_hierarchy_response_levels(
    *,
    merged_df: pd.DataFrame,
    day_count: int,
    request: ContributionRequest,
) -> list[dict[str, Any]]:
    response_levels = []
    hierarchy_levels = request.hierarchy or []
    for index, level_name in enumerate(hierarchy_levels):
        level_keys = hierarchy_levels[: index + 1]
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
                "parent": hierarchy_levels[index - 1] if index > 0 else None,
                "rows": rows,
            }
        )
    return response_levels


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
    top_n = max(0, int(request.emit.top_n_per_level))
    explicit_rows, overflow_rows = _partition_hierarchy_rows_for_emission(
        ordered,
        threshold=threshold,
        top_n=top_n,
    )

    rows = [_hierarchy_row_to_response(row, level_keys=level_keys) for _, row in explicit_rows.iterrows()]
    other_row = _other_hierarchy_row_for_emission(
        overflow_rows=overflow_rows,
        level_keys=level_keys,
        include_other=request.emit.include_other,
    )
    if other_row is not None:
        rows.append(other_row)
    return rows


def _partition_hierarchy_rows_for_emission(
    ordered: pd.DataFrame,
    *,
    threshold: float,
    top_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    explicit_rows = ordered[ordered["weight_avg"].abs() >= threshold]
    overflow_rows = ordered[ordered["weight_avg"].abs() < threshold]
    if top_n and len(explicit_rows) > top_n:
        overflow_rows = pd.concat([overflow_rows, explicit_rows.iloc[top_n:]], ignore_index=True)
        explicit_rows = explicit_rows.iloc[:top_n]
    return explicit_rows, overflow_rows


def _hierarchy_row_to_response(row: pd.Series, *, level_keys: list[str]) -> dict[str, Any]:
    return {
        "key": {key: row[key] for key in level_keys},
        "contribution": _as_numeric(row["contribution"]) * 100,
        "weight_avg": _as_numeric(row["weight_avg"]) * 100,
    }


def _other_hierarchy_row_for_emission(
    *,
    overflow_rows: pd.DataFrame,
    level_keys: list[str],
    include_other: bool,
) -> dict[str, Any] | None:
    if not include_other or overflow_rows.empty:
        return None
    return {
        "key": {key: "Other" for key in level_keys},
        "contribution": _as_numeric(overflow_rows["contribution"].sum()) * 100,
        "weight_avg": _as_numeric(overflow_rows["weight_avg"].sum()) * 100,
        "children_count": int(len(overflow_rows)),
        "is_other": True,
    }
