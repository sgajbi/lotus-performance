# engine/contribution.py
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from app.models.contribution_requests import ContributionRequest, Smoothing
from common.enums import WeightingScheme
from engine.config import EngineConfig
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns


def _calculate_daily_instrument_contributions(
    instruments_df: pd.DataFrame, portfolio_df: pd.DataFrame, weighting_scheme: WeightingScheme, smoothing: Smoothing
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

    if smoothing.method == "CARINO":
        portfolio_df_indexed = portfolio_df.set_index(PortfolioColumns.PERF_DATE.value)
        port_ror_series = portfolio_df_indexed[PortfolioColumns.DAILY_ROR.value] / 100
        k_daily = _calculate_carino_factors(port_ror_series)
        port_total_ror = (1 + port_ror_series).prod() - 1
        K_total = np.log(1 + port_total_ror) / port_total_ror if port_total_ror != 0 else 1.0

        df = pd.merge(df, k_daily.rename("k_t"), left_on=PortfolioColumns.PERF_DATE.value, right_index=True)
        df["K_total"] = K_total

        port_ror_daily_map = portfolio_df_indexed[PortfolioColumns.DAILY_ROR.value] / 100
        df["R_port_t"] = df[PortfolioColumns.PERF_DATE.value].map(port_ror_daily_map)

        adjustment_factor = df["daily_weight"] * (df["R_port_t"] * ((df["K_total"] / df["k_t"]) - 1))

        df["smoothed_contribution"] = df["raw_contribution"] + adjustment_factor.fillna(0.0)
        df["smoothed_local_contribution"] = df["raw_local_contribution"]
        df["smoothed_fx_contribution"] = df["smoothed_contribution"] - df["smoothed_local_contribution"]
    else:
        df["smoothed_local_contribution"] = df["raw_local_contribution"]
        df["smoothed_fx_contribution"] = df["raw_fx_contribution"]
        df["smoothed_contribution"] = df["raw_contribution"]

    nip_reset_dates = portfolio_df[
        (portfolio_df[PortfolioColumns.NIP.value] == 1) | (portfolio_df[PortfolioColumns.PERF_RESET.value] == 1)
    ][PortfolioColumns.PERF_DATE.value]

    contrib_cols = ["smoothed_contribution", "smoothed_local_contribution", "smoothed_fx_contribution"]
    df.loc[df[PortfolioColumns.PERF_DATE.value].isin(nip_reset_dates), contrib_cols] = 0.0

    return df


def _prepare_hierarchical_data(request: ContributionRequest) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Runs TWR calculations and combines all position data and metadata into a single DataFrame.
    """
    perf_start_date = request.portfolio_data.valuation_points[0].perf_date
    twr_config = EngineConfig(
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

    portfolio_results_df = run_engine_for_valuation_points(
        [item.model_dump() for item in request.portfolio_data.valuation_points],
        twr_config,
        force_base_only=twr_config.currency_mode == "BOTH",
    )

    fx_rates_df = pd.DataFrame()
    if request.currency_mode == "BOTH" and request.fx:
        fx_rates_df = pd.DataFrame([rate.model_dump() for rate in request.fx.rates])
        fx_rates_df["date"] = pd.to_datetime(fx_rates_df["date"])
        fx_rates_df.drop_duplicates(subset=["date", "ccy"], keep="last", inplace=True)

    all_positions_data = []
    for position in request.positions_data:
        if not position.valuation_points:
            continue

        position_ccy = position.meta.get("currency")
        position_results_df = run_engine_for_valuation_points(
            [item.model_dump() for item in position.valuation_points],
            twr_config,
            force_base_only=not (request.currency_mode == "BOTH" and position_ccy != request.report_ccy),
        )
        if (
            request.currency_mode == "BOTH"
            and position_ccy == request.report_ccy
            and "local_ror" not in position_results_df.columns
        ):
            position_results_df["local_ror"] = position_results_df[PortfolioColumns.DAILY_ROR.value]
            position_results_df["fx_ror"] = 0.0
        position_results_df["position_id"] = position.position_id
        for key, value in position.meta.items():
            position_results_df[key] = value

        if request.currency_mode == "BOTH" and position_ccy != request.report_ccy and not fx_rates_df.empty:
            pos_fx_lookup = fx_rates_df[fx_rates_df["ccy"] == position_ccy][["date", "rate"]].rename(
                columns={"rate": "fx_rate"}
            )
            position_results_df["prior_date"] = position_results_df[PortfolioColumns.PERF_DATE.value] - pd.Timedelta(
                days=1
            )

            position_results_df = pd.merge(
                position_results_df, pos_fx_lookup, left_on="prior_date", right_on="date", how="left"
            ).ffill()

            if "fx_rate" in position_results_df.columns:
                for col in [PortfolioColumns.BEGIN_MV.value, PortfolioColumns.BOD_CF.value]:
                    position_results_df[col] *= position_results_df["fx_rate"]

        all_positions_data.append(position_results_df)

    if not all_positions_data:
        return pd.DataFrame(), portfolio_results_df

    instruments_df = pd.concat(all_positions_data, ignore_index=True)
    return instruments_df, portfolio_results_df


def calculate_hierarchical_contribution(request: ContributionRequest) -> Tuple[Dict, Dict]:
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
    request: ContributionRequest,
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

    temp_meta_cols = ["position_id"] + request.hierarchy
    metadata_cols = list(dict.fromkeys(temp_meta_cols))
    unique_meta = daily_contributions_df[metadata_cols].drop_duplicates()
    aggregated_df = pd.merge(totals, unique_meta, on="position_id")

    response_levels = []
    for i, level_name in enumerate(request.hierarchy):
        level_keys = request.hierarchy[: i + 1]
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
            {"level": i + 1, "name": level_name, "parent": request.hierarchy[i - 1] if i > 0 else None, "rows": rows}
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


def _calculate_carino_factors(ror_series: pd.Series) -> pd.Series:
    """Calculates the Carino smoothing factor k for a series of returns."""
    if not isinstance(ror_series.index, pd.DatetimeIndex):
        ror_series.index = pd.to_datetime(ror_series.index)

    return pd.Series(np.where(ror_series == 0, 1.0, np.log(1 + ror_series) / ror_series), index=ror_series.index)
