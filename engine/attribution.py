# engine/attribution.py
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from adapters.api_adapter import create_engine_dataframe
from app.models.attribution_requests import (
    AttributionModel,
    AttributionRequest,
    BenchmarkGroup,
    PortfolioGroup,
)
from app.models.attribution_responses import (
    AttributionGroupResult,
    AttributionLevelResult,
    AttributionLevelTotals,
    CurrencyAttributionEffects,
    CurrencyAttributionResult,
    Reconciliation,
    SinglePeriodAttributionResult,
)
from common.enums import AttributionMode, LinkingMethod
from engine.config import EngineConfig
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns


def _prepare_data_from_instruments(request: AttributionRequest) -> List[PortfolioGroup]:
    """
    Runs TWR engine on instrument data and aggregates returns and weights
    up to the requested group levels.
    """
    if not request.portfolio_data or not request.instruments_data:
        raise ValueError("'portfolio_data' and 'instruments_data' are required for 'by_instrument' mode.")

    twr_config = EngineConfig(
        performance_start_date=request.report_start_date,
        report_start_date=request.report_start_date,
        report_end_date=request.report_end_date,
        metric_basis=request.portfolio_data.metric_basis,
        period_type=request.analyses[0].period,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )

    portfolio_df = create_engine_dataframe([item.model_dump() for item in request.portfolio_data.valuation_points])
    portfolio_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(portfolio_df[PortfolioColumns.PERF_DATE.value])
    portfolio_df = portfolio_df.set_index(PortfolioColumns.PERF_DATE.value)
    portfolio_bop_mv = portfolio_df[PortfolioColumns.BEGIN_MV.value] + portfolio_df[PortfolioColumns.BOD_CF.value]

    all_instruments = []
    for inst in request.instruments_data:
        if not inst.valuation_points:
            continue

        inst_results = run_engine_for_valuation_points(
            [item.model_dump() for item in inst.valuation_points],
            twr_config,
            force_base_only=not (request.currency_mode == "BOTH" and inst.meta.get("currency") != request.report_ccy),
        )
        inst_results = inst_results.set_index(PortfolioColumns.PERF_DATE.value)

        inst_bop_mv = inst_results[PortfolioColumns.BEGIN_MV.value] + inst_results[PortfolioColumns.BOD_CF.value]
        with np.errstate(divide="ignore", invalid="ignore"):
            weight_bop = inst_bop_mv / portfolio_bop_mv
        inst_results["weight_bop"] = weight_bop.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        inst_results.rename(
            columns={
                PortfolioColumns.DAILY_ROR.value: "return_base",
                "local_ror": "return_local",
                "fx_ror": "return_fx",
            },
            inplace=True,
        )

        for col in ["return_base", "return_local", "return_fx"]:
            if col in inst_results.columns:
                inst_results[col] /= 100

        for key, value in inst.meta.items():
            inst_results[key] = value
        all_instruments.append(inst_results.reset_index())

    if not all_instruments:
        return []

    full_df = pd.concat(all_instruments)
    group_cols = request.group_by

    return_cols = ["return_base", "return_local", "return_fx"]
    for col in return_cols:
        if col in full_df.columns:
            full_df[f"weighted_{col}"] = full_df[col] * full_df["weight_bop"]

    grouped = full_df.groupby([PortfolioColumns.PERF_DATE.value] + group_cols)
    group_weights = grouped["weight_bop"].sum()

    aggregated_panel = pd.DataFrame({"weight_bop": group_weights})
    for col in return_cols:
        if f"weighted_{col}" in full_df.columns:
            group_weighted_ror = grouped[f"weighted_{col}"].sum()
            with np.errstate(divide="ignore", invalid="ignore"):
                group_returns = group_weighted_ror / group_weights
            group_returns = group_returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
            aggregated_panel[col] = group_returns

    aggregated_panel.reset_index(inplace=True)

    output_groups = []
    for keys, group_df in aggregated_panel.groupby(group_cols):
        key_dict = {group_cols[i]: key_val for i, key_val in enumerate(keys if isinstance(keys, tuple) else [keys])}
        obs_cols = [PortfolioColumns.PERF_DATE.value, "weight_bop"] + return_cols
        obs_df = group_df[[c for c in obs_cols if c in group_df.columns]]
        output_groups.append(
            PortfolioGroup(
                key=key_dict,
                observations=obs_df.rename(columns={PortfolioColumns.PERF_DATE.value: "date"}).to_dict(
                    orient="records"
                ),
            )
        )
    return output_groups


def _prepare_panel_from_groups(groups: List[PortfolioGroup | BenchmarkGroup], group_by: List[str]) -> pd.DataFrame:
    """Helper to convert list of group data into a tidy DataFrame panel."""
    all_obs = []
    if not groups:
        return pd.DataFrame()

    for group in groups:
        group_key_tuple = tuple(group.key.get(k) for k in group_by)
        for obs in group.observations:
            obs_data = obs if isinstance(obs, dict) else obs.model_dump()
            record = {
                "date": pd.to_datetime(obs_data["date"]),
                "weight_bop": obs_data.get("weight_bop", 0.0),
                "return_base": obs_data.get("return_base") or obs_data.get("return", 0.0),
                "return_local": obs_data.get("return_local"),
                "return_fx": obs_data.get("return_fx"),
            }
            for i, key in enumerate(group_by):
                record[key] = group_key_tuple[i]
            all_obs.append(record)

    if not all_obs:
        return pd.DataFrame()
    df = pd.DataFrame(all_obs)
    return df.set_index(["date"] + group_by)


def _align_and_prepare_data(request: AttributionRequest, portfolio_groups_data: List[PortfolioGroup]) -> pd.DataFrame:
    """Pre-processes and aligns portfolio and benchmark group data for attribution."""
    group_by = request.group_by
    portfolio_panel = _prepare_panel_from_groups(portfolio_groups_data, group_by)
    benchmark_panel = _prepare_panel_from_groups(request.benchmark_groups_data, group_by)

    if portfolio_panel.empty or benchmark_panel.empty:
        return pd.DataFrame()

    freq_map = {"daily": "D", "monthly": "ME", "quarterly": "QE", "yearly": "YE"}
    freq_code = freq_map.get(request.frequency.value, "ME")

    return_cols = ["return_base", "return_local", "return_fx"]

    def resample_panel(panel):
        resampler = panel.unstack(level=group_by).resample(freq_code)
        weights = resampler["weight_bop"].first()
        resampled_data = {"w": weights}
        for col in return_cols:
            if col in panel.columns and panel[col].notna().any():
                resampled_data[f"r_{col.split('_')[1]}"] = resampler[col].apply(
                    lambda x: (1 + x).prod() - 1 if not x.empty else None
                )
        return pd.concat(
            [df.stack(group_by, future_stack=True) for df in resampled_data.values()],
            axis=1,
            keys=resampled_data.keys(),
        )

    df_p = resample_panel(portfolio_panel)
    df_b = resample_panel(benchmark_panel)

    aligned_df = pd.merge(df_p, df_b, left_index=True, right_index=True, how="outer", suffixes=("_p", "_b")).fillna(0.0)
    aligned_df.index.names = ["date"] + group_by

    total_benchmark_return = (aligned_df["w_b"] * aligned_df["r_base_b"]).groupby(level="date").sum()
    return aligned_df.join(total_benchmark_return.rename("r_b_total"), on="date")


def _calculate_single_period_effects(df: pd.DataFrame, model: AttributionModel) -> pd.DataFrame:
    """Calculates single-period attribution effects (A, S, I) for an aligned DataFrame."""
    if model == AttributionModel.BRINSON_FACHLER:
        df["allocation"] = (df["w_p"] - df["w_b"]) * (df["r_base_b"] - df["r_b_total"])
        df["selection"] = df["w_b"] * (df["r_base_p"] - df["r_base_b"])
        df["interaction"] = (df["w_p"] - df["w_b"]) * (df["r_base_p"] - df["r_base_b"])
    elif model == AttributionModel.BRINSON_HOOD_BEEBOWER:
        df["allocation"] = (df["w_p"] - df["w_b"]) * df["r_base_b"]
        df["selection"] = df["w_p"] * (df["r_base_p"] - df["r_base_b"])
        df["interaction"] = (df["w_p"] - df["w_b"]) * (df["r_base_p"] - df["r_base_b"])
    return df


def _calculate_currency_attribution_effects(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates the four Karnosky-Singer currency attribution effects."""
    df["local_allocation"] = (df["w_p"] - df["w_b"]) * df["r_local_b"]
    df["local_selection"] = df["w_b"] * (df["r_local_p"] - df["r_local_b"])
    df["currency_allocation"] = (df["w_p"] - df["w_b"]) * (1 + df["r_local_b"]) * df["r_fx_b"]
    df["currency_selection"] = df["w_b"] * (df["r_local_p"] - df["r_local_b"]) * df["r_fx_b"]
    return df


def _link_effects_top_down(
    effects_df: pd.DataFrame, geometric_total_ar: float, arithmetic_total_ar: float
) -> pd.DataFrame:
    """Links multi-period effects by scaling the arithmetic sum to match the geometric total."""
    if arithmetic_total_ar == 0:
        return effects_df

    scaling_factor = geometric_total_ar / arithmetic_total_ar

    linked_effects = effects_df.copy()
    for col in ["allocation", "selection", "interaction"]:
        if col in linked_effects.columns:
            linked_effects[col] *= scaling_factor

    return linked_effects


def aggregate_attribution_results(
    effects_df: pd.DataFrame, request: AttributionRequest
) -> Tuple[SinglePeriodAttributionResult, Dict[str, pd.DataFrame]]:
    """Aggregates a DataFrame of daily effects into the final response model for a single period."""
    aggregation_lineage = {}
    per_period_p_return = (effects_df["w_p"] * effects_df["r_base_p"]).groupby(level="date").sum()
    per_period_b_return = effects_df.groupby(level="date")["r_b_total"].first()
    per_period_active_return = per_period_p_return - per_period_b_return

    if request.linking != LinkingMethod.NONE:
        geometric_active_return = (1 + per_period_p_return).prod() - 1 - ((1 + per_period_b_return).prod() - 1)
        arithmetic_active_return = per_period_active_return.sum()
        scaled_effects = _link_effects_top_down(
            effects_df.reset_index(), geometric_active_return, arithmetic_active_return
        )
        granular_totals = scaled_effects.groupby(request.group_by)[["allocation", "selection", "interaction"]].sum()
        active_return = geometric_active_return
    else:
        granular_totals = effects_df.groupby(request.group_by)[["allocation", "selection", "interaction"]].sum()
        active_return = per_period_active_return.sum()

    levels = []
    granular_totals_df = granular_totals.reset_index()

    for i in range(len(request.group_by), 0, -1):
        level_group_by = request.group_by[:i]
        level_totals = granular_totals_df.groupby(level_group_by).sum(numeric_only=True)
        level_totals["total_effect"] = level_totals.sum(axis=1)

        group_results = []
        for group_key, row in level_totals.iterrows():
            key_dict = {}
            if isinstance(group_key, tuple):
                for j, key_name in enumerate(level_group_by):
                    key_dict[key_name] = group_key[j]
            else:
                key_dict[level_group_by[0]] = group_key
            group_results.append(AttributionGroupResult(key=key_dict, **(row * 100).to_dict()))

        overall_level_totals = level_totals.sum()
        levels.append(
            AttributionLevelResult(
                dimension=" -> ".join(level_group_by),
                groups=sorted(group_results, key=lambda x: str(x.key)),
                totals=AttributionLevelTotals(**(overall_level_totals * 100).to_dict()),
            )
        )

    levels.reverse()
    final_totals = (
        levels[0].totals if levels else AttributionLevelTotals(allocation=0, selection=0, interaction=0, total_effect=0)
    )

    period_result = SinglePeriodAttributionResult(
        levels=levels,
        reconciliation=Reconciliation(
            total_active_return=active_return * 100,
            sum_of_effects=final_totals.total_effect,
            residual=(active_return * 100) - final_totals.total_effect,
        ),
    )

    if request.currency_mode == "BOTH":
        required_cols = {"r_local_p", "r_local_b", "r_fx_b", "w_p", "w_b"}
        effects_df_reset = effects_df.reset_index()
        if required_cols.issubset(effects_df.columns) and "currency" in effects_df_reset.columns:
            currency_df = effects_df_reset.groupby(["date", "currency"]).sum(numeric_only=True)
            fx_effects_df = _calculate_currency_attribution_effects(currency_df)
            aggregation_lineage["currency_attribution_effects.csv"] = fx_effects_df.reset_index()
            total_fx_effects = fx_effects_df.groupby("currency").sum(numeric_only=True)

            fx_results = []
            for currency, row in total_fx_effects.iterrows():
                avg_weights = currency_df.loc[currency_df.index.get_level_values("currency") == currency][
                    ["w_p", "w_b"]
                ].mean()
                effects_sum = (
                    row["local_allocation"]
                    + row["local_selection"]
                    + row["currency_allocation"]
                    + row["currency_selection"]
                )
                effects = CurrencyAttributionEffects(
                    local_allocation=row["local_allocation"] * 100,
                    local_selection=row["local_selection"] * 100,
                    currency_allocation=row["currency_allocation"] * 100,
                    currency_selection=row["currency_selection"] * 100,
                    total_effect=effects_sum * 100,
                )
                fx_results.append(
                    CurrencyAttributionResult(
                        currency=str(currency),
                        weight_portfolio_avg=avg_weights["w_p"] * 100,
                        weight_benchmark_avg=avg_weights["w_b"] * 100,
                        effects=effects,
                    )
                )
            period_result.currency_attribution = fx_results

    return period_result, aggregation_lineage


def run_attribution_calculations(request: AttributionRequest) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    Orchestrates the calculation of daily attribution effects over a master period.
    Returns a tuple of (daily_effects_df, lineage_data_dictionary).
    """
    lineage_data = {}
    if request.mode == AttributionMode.BY_INSTRUMENT:
        portfolio_groups_data = _prepare_data_from_instruments(request)
    elif request.mode == AttributionMode.BY_GROUP:
        portfolio_groups_data = request.portfolio_groups_data or []
    else:
        raise ValueError("Invalid attribution mode specified.")

    aligned_df = _align_and_prepare_data(request, portfolio_groups_data)
    lineage_data["aligned_panel.csv"] = aligned_df.reset_index()

    if aligned_df.empty:
        return pd.DataFrame(), lineage_data

    effects_df = _calculate_single_period_effects(aligned_df, request.model)
    lineage_data["single_period_effects.csv"] = effects_df.reset_index().copy()

    return effects_df, lineage_data
