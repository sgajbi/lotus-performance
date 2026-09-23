from __future__ import annotations

from datetime import date
from math import isfinite
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
from app.services.currency_code_normalization import normalized_currency_code
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
    portfolio_period_slice_df: pd.DataFrame | None = None,
    source_position_history_df: pd.DataFrame | None = None,
    source_position_window_complete: bool | None = None,
    position_series: list[PositionContributionSeries],
    position_average_weights: pd.DataFrame | None = None,
    proven_position_inception_dates: dict[str, date] | None = None,
    request: ContributionRequest,
) -> dict[str, Any]:
    """Builds hierarchy rows from the same adjusted daily position series emitted to clients."""
    summary = _initial_hierarchy_summary(request)
    calendar_df = portfolio_period_slice_df if portfolio_period_slice_df is not None else period_slice_df
    observed_dates = (
        observation_date_set(calendar_df[PortfolioColumns.PERF_DATE.value])
        if PortfolioColumns.PERF_DATE.value in calendar_df.columns
        else set()
    )
    source_position_memberships = _latest_source_position_hierarchy_memberships(
        source_position_history_df,
        observation_dates=observed_dates,
        request=request,
    )
    prepared_frames = _prepared_hierarchy_frames_or_source_membership_fallback(
        period_slice_df=period_slice_df,
        position_series=position_series,
        position_average_weights=position_average_weights,
        source_position_memberships=source_position_memberships,
        observed_dates=observed_dates,
        request=request,
    )
    if prepared_frames is None:
        return {"summary": summary, "levels": []}
    adjusted_df, merged_df = prepared_frames

    position_day_count = max(
        1,
        len(observation_date_set(period_slice_df[PortfolioColumns.PERF_DATE.value])),
    )
    response_levels = _build_hierarchy_response_levels(
        merged_df=merged_df,
        observation_dates=observed_dates,
        source_position_memberships=source_position_memberships,
        source_position_window_complete=source_position_window_complete,
        day_count=position_day_count,
        proven_position_inception_dates=proven_position_inception_dates,
        request=request,
    )

    summary["portfolio_contribution"] = _as_numeric(adjusted_df["adjusted_contribution"].sum()) * 100
    return {"summary": summary, "levels": response_levels}


def _prepared_hierarchy_frames_or_source_membership_fallback(
    *,
    period_slice_df: pd.DataFrame,
    position_series: list[PositionContributionSeries],
    position_average_weights: pd.DataFrame | None,
    source_position_memberships: pd.DataFrame | None,
    observed_dates: set[date],
    request: ContributionRequest,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    if _has_adjusted_hierarchy_inputs(
        period_slice_df=period_slice_df,
        position_series=position_series,
        request=request,
    ):
        return _prepared_adjusted_hierarchy_frames(
            period_slice_df=period_slice_df,
            position_series=position_series,
            position_average_weights=position_average_weights,
            request=request,
        )
    if not request.hierarchy or not observed_dates or source_position_memberships is None:
        return None
    if source_position_memberships.empty:
        return None

    adjusted_df = pd.DataFrame(columns=["adjusted_contribution"])
    merged_df = pd.DataFrame(columns=[*_hierarchy_metadata_columns(request.hierarchy), "adjusted_contribution"])
    return adjusted_df, merged_df


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
    if "currency" not in daily_meta.columns:
        daily_meta["currency"] = None
    for evidence_column in (PortfolioColumns.DAILY_ROR.value, "capital_inst"):
        if evidence_column not in daily_meta.columns:
            daily_meta[evidence_column] = float("nan")
    _preserve_source_daily_weight(daily_meta)
    daily_meta[PortfolioColumns.PERF_DATE.value] = observation_date_series(daily_meta[PortfolioColumns.PERF_DATE.value])
    daily_meta["selected_average_weight"] = pd.NA
    if position_average_weights is not None and not position_average_weights.empty:
        daily_meta = daily_meta.drop(columns=["selected_average_weight"]).merge(
            position_average_weights[["position_id", "selected_average_weight"]],
            on="position_id",
            how="left",
        )
        daily_meta["selected_average_weight"] = pd.to_numeric(
            daily_meta["selected_average_weight"],
            errors="coerce",
        )
    return daily_meta[meta_columns]


def _preserve_source_daily_weight(daily_meta: pd.DataFrame) -> None:
    if "daily_weight" not in daily_meta.columns:
        daily_meta["source_daily_weight"] = pd.NA
        return
    daily_meta["source_daily_weight"] = pd.to_numeric(daily_meta["daily_weight"], errors="coerce")


def _source_daily_weights(daily_df: pd.DataFrame) -> pd.Series:
    column = "source_daily_weight" if "source_daily_weight" in daily_df.columns else "daily_weight"
    return pd.to_numeric(daily_df[column], errors="coerce")


def _hierarchy_metadata_columns(hierarchy_levels: list[str]) -> list[str]:
    meta_columns = [
        "position_id",
        PortfolioColumns.PERF_DATE.value,
        PortfolioColumns.DAILY_ROR.value,
        "capital_inst",
        "daily_weight",
        "source_daily_weight",
        "selected_average_weight",
        "currency",
    ]
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


def _latest_source_position_hierarchy_memberships(
    source_position_history_df: pd.DataFrame | None,
    *,
    observation_dates: set[date],
    request: ContributionRequest,
) -> pd.DataFrame | None:
    if source_position_history_df is None:
        return None
    required_columns = {"position_id", PortfolioColumns.PERF_DATE.value}
    if source_position_history_df.empty or not required_columns.issubset(source_position_history_df.columns):
        return None
    if not observation_dates:
        return None

    history_df = source_position_history_df.copy()
    for level_name in request.hierarchy or []:
        if level_name not in history_df.columns:
            history_df[level_name] = None
    history_df[PortfolioColumns.PERF_DATE.value] = observation_date_series(history_df[PortfolioColumns.PERF_DATE.value])
    history_df = history_df[
        history_df["position_id"].notna()
        & history_df[PortfolioColumns.PERF_DATE.value].notna()
        & (history_df[PortfolioColumns.PERF_DATE.value] <= max(observation_dates))
    ]
    history_df = _apply_hierarchy_unclassified_policy(history_df, request=request)
    return history_df.sort_values(PortfolioColumns.PERF_DATE.value).drop_duplicates(
        "position_id",
        keep="last",
    )


def _source_group_position_ids(
    source_position_memberships: pd.DataFrame | None,
    *,
    level_keys: list[str],
    key_values: tuple[Any, ...],
) -> set[str] | None:
    if source_position_memberships is None:
        return None
    group_memberships = _hierarchy_group_slice(
        source_position_memberships,
        level_keys=level_keys,
        key_values=key_values,
    )
    return {str(value) for value in group_memberships["position_id"].dropna().tolist()}


def _hierarchy_group_slice(
    source_df: pd.DataFrame,
    *,
    level_keys: list[str],
    key_values: tuple[Any, ...],
) -> pd.DataFrame:
    group_df = source_df
    for level_name, key_value in zip(level_keys, key_values, strict=True):
        if pd.isna(key_value):
            group_df = group_df[group_df[level_name].isna()]
        else:
            group_df = group_df[group_df[level_name] == key_value]
    return group_df


def _hierarchy_group_keys(
    merged_df: pd.DataFrame,
    *,
    source_position_memberships: pd.DataFrame | None,
    level_keys: list[str],
) -> list[tuple[Any, ...]]:
    key_frames = [merged_df[level_keys]]
    if source_position_memberships is not None:
        key_frames.append(source_position_memberships[level_keys])
    distinct_keys = pd.concat(key_frames, ignore_index=True).drop_duplicates()
    return [tuple(row) for row in distinct_keys.itertuples(index=False, name=None)]


def _build_hierarchy_response_levels(
    *,
    merged_df: pd.DataFrame,
    observation_dates: set[date],
    source_position_memberships: pd.DataFrame | None,
    source_position_window_complete: bool | None,
    day_count: int,
    proven_position_inception_dates: dict[str, date] | None,
    request: ContributionRequest,
) -> list[dict[str, Any]]:
    response_levels = []
    hierarchy_levels = request.hierarchy or []
    for index, level_name in enumerate(hierarchy_levels):
        level_keys = hierarchy_levels[: index + 1]
        level_agg = _aggregate_hierarchy_level(
            merged_df=merged_df,
            level_keys=level_keys,
            observation_dates=observation_dates,
            source_position_memberships=source_position_memberships,
            source_position_window_complete=source_position_window_complete,
            proven_position_inception_dates=proven_position_inception_dates,
            request=request,
        )
        level_agg["weight_avg"] = level_agg["selected_weight_sum"].where(
            level_agg["selected_weight_complete"],
            level_agg["weight_sum"] / day_count,
        )
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


def _aggregate_hierarchy_level(
    *,
    merged_df: pd.DataFrame,
    level_keys: list[str],
    observation_dates: set[date],
    source_position_memberships: pd.DataFrame | None,
    source_position_window_complete: bool | None,
    proven_position_inception_dates: dict[str, date] | None,
    request: ContributionRequest,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for key_values in _hierarchy_group_keys(
        merged_df,
        source_position_memberships=source_position_memberships,
        level_keys=level_keys,
    ):
        group_df = _hierarchy_group_slice(
            merged_df,
            level_keys=level_keys,
            key_values=key_values,
        )
        record: dict[str, Any] = {key: value for key, value in zip(level_keys, key_values, strict=True)}
        selected_weight_sum, selected_weight_complete = _selected_group_weight(group_df)
        record.update(
            {
                "contribution": _as_numeric(group_df["adjusted_contribution"].sum()),
                "weight_sum": _as_numeric(group_df["daily_weight"].sum()),
                "selected_weight_sum": selected_weight_sum,
                "selected_weight_complete": selected_weight_complete,
                "group_return": _group_return_evidence(
                    group_df=group_df,
                    request=request,
                    observation_dates=observation_dates,
                    expected_position_ids=_source_group_position_ids(
                        source_position_memberships,
                        level_keys=level_keys,
                        key_values=key_values,
                    ),
                    source_position_window_complete=source_position_window_complete,
                    proven_position_inception_dates=proven_position_inception_dates,
                ),
            }
        )
        records.append(record)
    return pd.DataFrame(records)


def _selected_group_weight(group_df: pd.DataFrame) -> tuple[Any, bool]:
    if group_df.empty:
        return 0.0, False
    selected_weights = group_df[["position_id", "selected_average_weight"]].drop_duplicates("position_id")
    selected_numeric = pd.to_numeric(selected_weights["selected_average_weight"], errors="coerce")
    if selected_numeric.isna().any():
        return 0.0, False
    return _as_numeric(selected_numeric.sum()), True


def _group_return_evidence(
    *,
    group_df: pd.DataFrame,
    request: ContributionRequest,
    observation_dates: set[date] | None = None,
    expected_position_ids: set[str] | None = None,
    source_position_window_complete: bool | None = None,
    proven_position_inception_dates: dict[str, date] | None = None,
) -> dict[str, Any]:
    if _group_return_input_is_incomplete(
        group_df,
        expected_position_ids=expected_position_ids,
        source_position_window_complete=source_position_window_complete,
    ):
        return _unavailable_group_return_evidence("SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE")

    currency = _group_return_currency(group_df=group_df, request=request)
    if currency is None:
        return _unavailable_group_return_evidence("MIXED_LOCAL_CURRENCIES_HAVE_NO_SINGLE_GROUP_RETURN")
    if observation_dates is not None and not _group_position_calendars_are_complete(
        group_df,
        observation_dates=observation_dates,
        proven_position_inception_dates=proven_position_inception_dates,
    ):
        return _unavailable_group_return_evidence(
            "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE",
            currency=currency,
        )

    points_by_date = _group_return_points_by_date(group_df)
    if points_by_date is None:
        return _unavailable_group_return_evidence(
            "SOURCE_POSITION_VALUATION_ECONOMICS_INCOMPLETE",
            currency=currency,
        )
    points = _completed_group_return_points(
        points_by_date,
        observation_dates=observation_dates,
    )
    linked_growth = 1.0
    for point in points:
        linked_growth *= 1.0 + point["return_pct"] / 100
    return {
        "status": "READY",
        "period_return_pct": (linked_growth - 1.0) * 100,
        "currency": currency,
        "series": points,
        "reason": None,
    }


def _group_return_points_by_date(
    group_df: pd.DataFrame,
) -> dict[date, dict[str, Any]] | None:
    points_by_date: dict[date, dict[str, Any]] = {}
    for observation_date, daily_df in group_df.groupby(PortfolioColumns.PERF_DATE.value, sort=True):
        capital = numeric_series(daily_df["capital_inst"], default=float("nan"))
        returns = pd.to_numeric(daily_df[PortfolioColumns.DAILY_ROR.value], errors="coerce")
        source_weights = _source_daily_weights(daily_df)
        denominator = _as_numeric(capital.sum())
        if _group_return_day_is_incomplete(denominator, capital, returns, source_weights):
            return None
        points_by_date[observation_date] = {
            "date": observation_date,
            "return_pct": _as_numeric((capital * returns).sum() / denominator),
            "portfolio_weight_pct": _as_numeric(source_weights.sum()) * 100,
        }
    return points_by_date


def _completed_group_return_points(
    points_by_date: dict[date, dict[str, Any]],
    *,
    observation_dates: set[date] | None,
) -> list[dict[str, Any]]:
    # The portfolio slice is the source-owned observation calendar. Only dates before
    # every position in this group first appears are proven zero exposure. The
    # completeness guard above refuses gaps at or after a position's inception.
    complete_calendar = set(points_by_date) | (observation_dates or set())
    return [
        points_by_date.get(
            observation_date,
            {
                "date": observation_date,
                "return_pct": 0.0,
                "portfolio_weight_pct": 0.0,
            },
        )
        for observation_date in sorted(complete_calendar)
    ]


def _group_position_calendars_are_complete(
    group_df: pd.DataFrame,
    *,
    observation_dates: set[date],
    proven_position_inception_dates: dict[str, date] | None = None,
) -> bool:
    if not observation_dates:
        return False
    portfolio_first_observation_date = min(observation_dates)
    inception_dates = proven_position_inception_dates or {}
    return all(
        _position_calendar_is_complete(
            position_df=position_df,
            observation_dates=observation_dates,
            portfolio_first_observation_date=portfolio_first_observation_date,
            proven_inception_date=inception_dates.get(str(position_id)),
        )
        for position_id, position_df in group_df.groupby("position_id", dropna=False)
    )


def _position_calendar_is_complete(
    *,
    position_df: pd.DataFrame,
    observation_dates: set[date],
    portfolio_first_observation_date: date,
    proven_inception_date: date | None,
) -> bool:
    position_dates = observation_date_set(position_df[PortfolioColumns.PERF_DATE.value])
    if not position_dates:
        return False
    period_first_observation_date = min(position_dates)
    if (
        period_first_observation_date > portfolio_first_observation_date
        and proven_inception_date != period_first_observation_date
    ):
        # A bounded source window cannot distinguish a newly acquired position
        # from a pre-existing position whose valuations resume late. Leading
        # zero exposure is safe only when the source row proves acquisition.
        return False
    required_start = min(
        period_first_observation_date,
        proven_inception_date or period_first_observation_date,
    )
    required_dates = {date_value for date_value in observation_dates if date_value >= required_start}
    return required_dates.issubset(position_dates)


def _proven_position_inception_dates(source_df: pd.DataFrame) -> dict[str, date]:
    selected_columns = (
        "position_id",
        PortfolioColumns.PERF_DATE.value,
        PortfolioColumns.BEGIN_MV.value,
        PortfolioColumns.BOD_CF.value,
    )
    if source_df.empty or not set(selected_columns).issubset(source_df.columns):
        return {}

    source_dates = source_df[list(selected_columns)].copy()
    source_dates[PortfolioColumns.PERF_DATE.value] = observation_date_series(
        source_dates[PortfolioColumns.PERF_DATE.value]
    )
    source_dates = source_dates.dropna(subset=["position_id", PortfolioColumns.PERF_DATE.value])
    source_dates = source_dates.sort_values(PortfolioColumns.PERF_DATE.value).drop_duplicates(
        "position_id", keep="first"
    )
    beginning_values = pd.to_numeric(source_dates[PortfolioColumns.BEGIN_MV.value], errors="coerce")
    beginning_cash_flows = pd.to_numeric(source_dates[PortfolioColumns.BOD_CF.value], errors="coerce")
    proven_inceptions = source_dates[(beginning_values == 0) & (beginning_cash_flows != 0)]
    return {str(row["position_id"]): row[PortfolioColumns.PERF_DATE.value] for _, row in proven_inceptions.iterrows()}


def _group_return_input_is_incomplete(
    group_df: pd.DataFrame,
    *,
    expected_position_ids: set[str] | None = None,
    source_position_window_complete: bool | None = None,
) -> bool:
    if group_df.empty or source_position_window_complete is False:
        return True
    if group_df[PortfolioColumns.PERF_DATE.value].isna().any():
        return True
    if expected_position_ids is None:
        return False
    observed_position_ids = {str(value) for value in group_df["position_id"].dropna().tolist()}
    return not expected_position_ids.issubset(observed_position_ids)


def _group_return_day_is_incomplete(
    denominator: Any,
    capital: pd.Series,
    returns: pd.Series,
    source_weights: pd.Series,
) -> bool:
    return (
        denominator == 0
        or not _all_finite(capital)
        or not _all_finite(returns)
        or not _all_finite(source_weights)
        or not isfinite(denominator)
    )


def _all_finite(values: pd.Series) -> bool:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any():
        return False
    return bool(numeric.map(isfinite).all())


def _unavailable_group_return_evidence(reason: str, *, currency: str | None = None) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "currency": currency,
        "series": [],
        "reason": reason,
    }


def _group_return_currency(*, group_df: pd.DataFrame, request: ContributionRequest) -> str | None:
    if request.currency_mode == "BOTH":
        return normalized_currency_code(request.report_ccy)
    if request.currency_mode != "LOCAL_ONLY":
        return normalized_currency_code(request.currency)
    currencies = {
        currency
        for raw_value in group_df["currency"].tolist()
        for currency in [normalized_currency_code(raw_value)]
        if currency is not None
    }
    return next(iter(currencies)) if len(currencies) == 1 else None


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
    unavailable_mask = ordered["group_return"].map(lambda evidence: evidence.get("status") == "UNAVAILABLE")
    unavailable_rows = ordered[unavailable_mask]
    ready_rows = ordered[~unavailable_mask]
    explicit_ready_rows = ready_rows[ready_rows["weight_avg"].abs() >= threshold]
    overflow_rows = ready_rows[ready_rows["weight_avg"].abs() < threshold]
    if top_n and len(explicit_ready_rows) > top_n:
        overflow_rows = pd.concat([overflow_rows, explicit_ready_rows.iloc[top_n:]], ignore_index=True)
        explicit_ready_rows = explicit_ready_rows.iloc[:top_n]
    explicit_rows = pd.concat([unavailable_rows, explicit_ready_rows], ignore_index=True)
    return explicit_rows, overflow_rows


def _hierarchy_row_to_response(row: pd.Series, *, level_keys: list[str]) -> dict[str, Any]:
    return {
        "key": {key: row[key] for key in level_keys},
        "contribution": _as_numeric(row["contribution"]) * 100,
        "weight_avg": _as_numeric(row["weight_avg"]) * 100,
        "group_return": row["group_return"],
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
        "group_return": {
            "status": "UNAVAILABLE",
            "currency": None,
            "series": [],
            "reason": "OTHER_BUCKET_COMBINES_MULTIPLE_SOURCE_GROUPS",
        },
        "children_count": int(len(overflow_rows)),
        "is_other": True,
    }
