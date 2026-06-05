# engine/contribution.py
from datetime import date as dt_date
from typing import Any, Dict, Mapping, Protocol, Sequence, Tuple

import numpy as np
import pandas as pd

from common.enums import WeightingScheme
from engine.config import EngineConfig
from engine.contribution_smoothing import (
    ContributionSmoothingLike,
    _calculate_carino_factor_for_return,
    _calculate_carino_factors,
    _carino_smoothing_domain_is_valid,
    apply_contribution_smoothing,
)
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns

__all__ = [
    "_calculate_carino_factor_for_return",
    "_calculate_carino_factors",
    "_carino_smoothing_domain_is_valid",
    "_calculate_daily_instrument_contributions",
    "_prepare_hierarchical_data",
    "build_hierarchical_contribution_result",
    "calculate_hierarchical_contribution",
]


class ModelDumpLike(Protocol):
    def model_dump(self) -> dict[str, Any]: ...


class ContributionValuationPointLike(ModelDumpLike, Protocol):
    @property
    def perf_date(self) -> dt_date: ...


class ContributionPortfolioDataLike(Protocol):
    @property
    def metric_basis(self) -> Any: ...

    @property
    def valuation_points(self) -> Sequence[ContributionValuationPointLike]: ...


class ContributionPositionDataLike(Protocol):
    @property
    def position_id(self) -> str: ...

    @property
    def meta(self) -> Mapping[str, Any]: ...

    @property
    def valuation_points(self) -> Sequence[ModelDumpLike]: ...


class ContributionAnalysisLike(Protocol):
    @property
    def period(self) -> Any: ...


class ContributionRequestLike(Protocol):
    @property
    def portfolio_data(self) -> ContributionPortfolioDataLike: ...

    @property
    def positions_data(self) -> Sequence[ContributionPositionDataLike]: ...

    @property
    def report_start_date(self) -> dt_date: ...

    @property
    def report_end_date(self) -> dt_date: ...

    @property
    def analyses(self) -> Sequence[ContributionAnalysisLike]: ...

    @property
    def precision_mode(self) -> Any: ...

    @property
    def rounding_precision(self) -> int: ...

    @property
    def currency_mode(self) -> Any: ...

    @property
    def report_ccy(self) -> str | None: ...

    @property
    def fx(self) -> Any: ...

    @property
    def hedging(self) -> Any: ...

    @property
    def weighting_scheme(self) -> WeightingScheme: ...

    @property
    def smoothing(self) -> ContributionSmoothingLike: ...

    @property
    def hierarchy(self) -> Sequence[str] | None: ...


def _calculate_daily_instrument_contributions(
    instruments_df: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    weighting_scheme: WeightingScheme,
    smoothing: ContributionSmoothingLike,
) -> pd.DataFrame:
    """
    Calculates daily weights and smoothed contributions for each instrument.
    """
    if instruments_df.empty:
        return instruments_df

    df = pd.merge(
        instruments_df,
        portfolio_df[
            [PortfolioColumns.PERF_DATE.value, PortfolioColumns.BEGIN_MV.value, PortfolioColumns.BOD_CF.value]
        ],
        on=PortfolioColumns.PERF_DATE.value,
        suffixes=("", "_port"),
    )

    if weighting_scheme == WeightingScheme.BOD:
        df["capital_inst"] = df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value]
        df["capital_port"] = df[f"{PortfolioColumns.BEGIN_MV.value}_port"] + df[f"{PortfolioColumns.BOD_CF.value}_port"]

    with np.errstate(divide="ignore", invalid="ignore"):
        daily_weight = df["capital_inst"] / df["capital_port"]
    df["daily_weight"] = daily_weight.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    df["raw_local_contribution"] = df["daily_weight"] * (df.get("local_ror", 0.0) / 100)
    df["raw_fx_contribution"] = df["daily_weight"] * (df.get("fx_ror", 0.0) / 100)
    df["raw_contribution"] = df["daily_weight"] * (df[PortfolioColumns.DAILY_ROR.value] / 100)
    df = apply_contribution_smoothing(df, portfolio_df, smoothing)

    nip_reset_dates = portfolio_df[
        (portfolio_df[PortfolioColumns.NIP.value] == 1) | (portfolio_df[PortfolioColumns.PERF_RESET.value] == 1)
    ][PortfolioColumns.PERF_DATE.value]

    contrib_cols = ["smoothed_contribution", "smoothed_local_contribution", "smoothed_fx_contribution"]
    df.loc[df[PortfolioColumns.PERF_DATE.value].isin(nip_reset_dates), contrib_cols] = 0.0

    return df


def _prepare_hierarchical_data(request: ContributionRequestLike) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Runs TWR calculations and combines all position data and metadata into a single DataFrame.
    """
    twr_config = _build_contribution_twr_config(request)
    portfolio_results_df = run_engine_for_valuation_points(
        [item.model_dump() for item in request.portfolio_data.valuation_points],
        twr_config,
        force_base_only=twr_config.currency_mode == "BOTH",
    )

    fx_rates_df = _build_contribution_fx_rates_frame(request)
    all_positions_data = []
    for position in request.positions_data:
        if not position.valuation_points:
            continue

        all_positions_data.append(
            _build_position_contribution_results_frame(
                position=position,
                request=request,
                twr_config=twr_config,
                fx_rates_df=fx_rates_df,
            )
        )

    if not all_positions_data:
        return pd.DataFrame(), portfolio_results_df

    instruments_df = pd.concat(all_positions_data, ignore_index=True)
    return instruments_df, portfolio_results_df


def _build_contribution_twr_config(request: ContributionRequestLike) -> EngineConfig:
    perf_start_date = request.portfolio_data.valuation_points[0].perf_date
    return EngineConfig(
        performance_start_date=perf_start_date,
        report_start_date=request.report_start_date,
        report_end_date=request.report_end_date,
        metric_basis=request.portfolio_data.metric_basis,
        period_type=request.analyses[0].period,
        precision_mode=request.precision_mode,
        rounding_precision=request.rounding_precision,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )


def _build_contribution_fx_rates_frame(request: ContributionRequestLike) -> pd.DataFrame:
    if request.currency_mode != "BOTH" or not request.fx:
        return pd.DataFrame()
    fx_rates_df = pd.DataFrame([rate.model_dump() for rate in request.fx.rates])
    fx_rates_df["date"] = pd.to_datetime(fx_rates_df["date"])
    fx_rates_df.drop_duplicates(subset=["date", "ccy"], keep="last", inplace=True)
    return fx_rates_df


def _build_position_contribution_results_frame(
    *,
    position: ContributionPositionDataLike,
    request: ContributionRequestLike,
    twr_config: EngineConfig,
    fx_rates_df: pd.DataFrame,
) -> pd.DataFrame:
    position_ccy = position.meta.get("currency")
    position_results_df = run_engine_for_valuation_points(
        [item.model_dump() for item in position.valuation_points],
        twr_config,
        force_base_only=not (request.currency_mode == "BOTH" and position_ccy != request.report_ccy),
    )
    _ensure_same_currency_local_fx_columns(
        position_results_df=position_results_df,
        request=request,
        position_ccy=position_ccy,
    )
    position_results_df["position_id"] = position.position_id
    for key, value in position.meta.items():
        position_results_df[key] = value
    return _apply_position_fx_capital_conversion(
        position_results_df=position_results_df,
        request=request,
        position_ccy=position_ccy,
        fx_rates_df=fx_rates_df,
    )


def _ensure_same_currency_local_fx_columns(
    *,
    position_results_df: pd.DataFrame,
    request: ContributionRequestLike,
    position_ccy: Any,
) -> None:
    if (
        request.currency_mode != "BOTH"
        or position_ccy != request.report_ccy
        or "local_ror" in position_results_df.columns
    ):
        return
    position_results_df["local_ror"] = position_results_df[PortfolioColumns.DAILY_ROR.value]
    position_results_df["fx_ror"] = 0.0


def _apply_position_fx_capital_conversion(
    *,
    position_results_df: pd.DataFrame,
    request: ContributionRequestLike,
    position_ccy: Any,
    fx_rates_df: pd.DataFrame,
) -> pd.DataFrame:
    if request.currency_mode != "BOTH" or position_ccy == request.report_ccy or fx_rates_df.empty:
        return position_results_df
    pos_fx_lookup = fx_rates_df[fx_rates_df["ccy"] == position_ccy][["date", "rate"]].rename(
        columns={"rate": "fx_rate"}
    )
    position_results_df["prior_date"] = position_results_df[PortfolioColumns.PERF_DATE.value] - pd.Timedelta(days=1)
    converted_df = pd.merge(
        position_results_df, pos_fx_lookup, left_on="prior_date", right_on="date", how="left"
    ).ffill()
    if "fx_rate" in converted_df.columns:
        for col in [PortfolioColumns.BEGIN_MV.value, PortfolioColumns.BOD_CF.value]:
            converted_df[col] *= converted_df["fx_rate"]
    return converted_df


def calculate_hierarchical_contribution(request: ContributionRequestLike) -> Tuple[Dict, Dict]:
    instruments_df, portfolio_results_df = _prepare_hierarchical_data(request)

    daily_contributions_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_results_df, request.weighting_scheme, request.smoothing
    )

    port_ror_series = portfolio_results_df[PortfolioColumns.DAILY_ROR.value] / 100
    total_portfolio_return = (1 + port_ror_series).prod() - 1

    results = build_hierarchical_contribution_result(
        daily_contributions_df,
        request,
        total_portfolio_return=total_portfolio_return,
    )
    lineage_data = {"portfolio_twr.csv": portfolio_results_df, "daily_contributions.csv": daily_contributions_df}

    return results, lineage_data


def build_hierarchical_contribution_result(
    daily_contributions_df: pd.DataFrame,
    request: ContributionRequestLike,
    *,
    total_portfolio_return,
) -> Dict:
    """Aggregates hierarchical contribution output for a single period slice."""
    if daily_contributions_df.empty:
        summary = {
            "portfolio_contribution": 0.0,
            "coverage_mv_pct": 100.0,
            "weighting_scheme": request.weighting_scheme.value,
        }
        if request.currency_mode == "BOTH":
            summary["local_contribution"] = 0.0
            summary["fx_contribution"] = 0.0
        return {"summary": summary, "levels": []}

    totals = (
        daily_contributions_df.groupby("position_id")
        .agg(
            contribution=("smoothed_contribution", "sum"),
            local_contribution=("smoothed_local_contribution", "sum"),
            fx_contribution=("smoothed_fx_contribution", "sum"),
            weight_avg=("daily_weight", "mean"),
        )
        .reset_index()
    )

    sum_of_contributions = totals["contribution"].sum()
    residual = total_portfolio_return - sum_of_contributions
    total_avg_weight = totals["weight_avg"].sum()

    if total_avg_weight != 0 and request.smoothing.method == "CARINO":
        totals["weight_proportion"] = totals["weight_avg"] / total_avg_weight
        sum_of_contribs_unalloc = totals["contribution"].sum()
        local_prop = totals["local_contribution"].sum() / sum_of_contribs_unalloc if sum_of_contribs_unalloc != 0 else 0
        fx_prop = totals["fx_contribution"].sum() / sum_of_contribs_unalloc if sum_of_contribs_unalloc != 0 else 0

        residual_local = residual * local_prop
        residual_fx = residual * fx_prop

        totals["contribution"] += residual * totals["weight_proportion"]
        totals["local_contribution"] += residual_local * totals["weight_proportion"]
        totals["fx_contribution"] += residual_fx * totals["weight_proportion"]

    hierarchy = list(request.hierarchy or [])
    temp_meta_cols = ["position_id"] + hierarchy
    metadata_cols = list(dict.fromkeys(temp_meta_cols))
    unique_meta = daily_contributions_df[metadata_cols].drop_duplicates()
    aggregated_df = pd.merge(totals, unique_meta, on="position_id")

    response_levels = []
    for i, level_name in enumerate(hierarchy):
        level_keys = hierarchy[: i + 1]
        level_agg = (
            aggregated_df.groupby(level_keys)
            .agg(
                contribution=("contribution", "sum"),
                local_contribution=("local_contribution", "sum"),
                fx_contribution=("fx_contribution", "sum"),
                weight_avg=("weight_avg", "sum"),
            )
            .reset_index()
        )

        rows = []
        for _, row in level_agg.iterrows():
            key_dict = {key: row[key] for key in level_keys}
            row_data = {
                "key": key_dict,
                "contribution": row["contribution"] * 100,
                "weight_avg": row["weight_avg"] * 100,
            }
            if request.currency_mode == "BOTH":
                row_data["local_contribution"] = row["local_contribution"] * 100
                row_data["fx_contribution"] = row["fx_contribution"] * 100
            rows.append(row_data)

        response_levels.append(
            {"level": i + 1, "name": level_name, "parent": hierarchy[i - 1] if i > 0 else None, "rows": rows}
        )

    portfolio_contribution = aggregated_df["contribution"].sum()
    summary = {
        "portfolio_contribution": portfolio_contribution * 100,
        "coverage_mv_pct": 100.0,
        "weighting_scheme": request.weighting_scheme.value,
    }
    if request.currency_mode == "BOTH":
        summary["local_contribution"] = aggregated_df["local_contribution"].sum() * 100
        summary["fx_contribution"] = aggregated_df["fx_contribution"].sum() * 100

    return {"summary": summary, "levels": response_levels}
