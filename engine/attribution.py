# engine/attribution.py
from dataclasses import dataclass
from datetime import date as dt_date
from typing import Any, Dict, Mapping, Protocol, Sequence, Tuple, TypedDict

import numpy as np
import pandas as pd

from common.enums import AttributionMode, AttributionModel, LinkingMethod
from engine.attribution_supportability import (
    build_attribution_supportability_evidence,
    classify_attribution_residual,
)
from engine.attribution_types import (
    AttributionGroupResult,
    AttributionLevelResult,
    AttributionLevelTotals,
    CurrencyAttributionEffects,
    CurrencyAttributionResult,
    CurrencyAttributionTotals,
    Reconciliation,
    SinglePeriodAttributionResult,
)
from engine.config import EngineConfig
from engine.dataframe import create_engine_dataframe_from_valuation_points
from engine.runtime import run_engine_for_valuation_points
from engine.schema import PortfolioColumns


class ModelDumpLike(Protocol):
    def model_dump(self) -> dict[str, Any]: ...


class AttributionValuationPointLike(ModelDumpLike, Protocol):
    @property
    def perf_date(self) -> dt_date: ...


class AttributionAnalysisLike(Protocol):
    @property
    def period(self) -> Any: ...


class AttributionPortfolioDataLike(Protocol):
    @property
    def metric_basis(self) -> Any: ...

    @property
    def valuation_points(self) -> Sequence[AttributionValuationPointLike]: ...


class AttributionInstrumentDataLike(Protocol):
    @property
    def meta(self) -> Mapping[str, Any]: ...

    @property
    def valuation_points(self) -> Sequence[ModelDumpLike]: ...


class AttributionObservationGroupLike(Protocol):
    @property
    def key(self) -> Mapping[str, Any]: ...

    @property
    def observations(self) -> Sequence[Any]: ...


class AttributionRequestLike(Protocol):
    @property
    def report_start_date(self) -> dt_date: ...

    @property
    def report_end_date(self) -> dt_date: ...

    @property
    def analyses(self) -> Sequence[AttributionAnalysisLike]: ...

    @property
    def mode(self) -> AttributionMode: ...

    @property
    def frequency(self) -> Any: ...

    @property
    def group_by(self) -> Sequence[str]: ...

    @property
    def model(self) -> AttributionModel: ...

    @property
    def linking(self) -> LinkingMethod: ...

    @property
    def portfolio_data(self) -> AttributionPortfolioDataLike | None: ...

    @property
    def instruments_data(self) -> Sequence[AttributionInstrumentDataLike] | None: ...

    @property
    def portfolio_groups_data(self) -> Sequence[AttributionObservationGroupLike] | None: ...

    @property
    def benchmark_groups_data(self) -> Sequence[AttributionObservationGroupLike]: ...

    @property
    def currency_mode(self) -> str | None: ...

    @property
    def report_ccy(self) -> str | None: ...

    @property
    def fx(self) -> Any: ...

    @property
    def hedging(self) -> Any: ...


@dataclass(frozen=True)
class AttributionObservationGroup:
    key: dict[str, Any]
    observations: list[dict[str, Any]]


@dataclass(frozen=True)
class _AttributionAggregationBase:
    active_return: Any
    granular_totals: pd.DataFrame
    linking_status: str


class _BaseWeightRecord(TypedDict):
    date: pd.Timestamp
    capital: float


def _calculate_linked_return(return_series: pd.Series) -> float:
    """Calculates a linked period return from per-date group returns expressed as decimal ratios."""
    numeric_returns = pd.to_numeric(return_series, errors="coerce").dropna()
    if numeric_returns.empty:
        return 0.0
    return float((1 + numeric_returns).prod() - 1)


def _calculate_weighted_average_return(weights: pd.Series, returns: pd.Series) -> float:
    """Calculates a one-date weighted average group return from aligned weight and return series."""
    numeric_weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    numeric_returns = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    total_weight = float(numeric_weights.sum())
    if total_weight == 0.0:
        return 0.0
    return float((numeric_weights * numeric_returns).sum() / total_weight)


def _calculate_group_context_metrics(effects_df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame:
    """Builds side-by-side portfolio/benchmark context for attribution rows.

    The front-office attribution view needs more than effect totals. It also needs the average
    portfolio and benchmark weights plus the linked portfolio and benchmark returns for the same
    grouped slice so that allocation, selection, and interaction can be read in economic context.
    """
    if effects_df.empty:
        return pd.DataFrame(
            columns=[
                "portfolio_weight_avg",
                "benchmark_weight_avg",
                "portfolio_return",
                "benchmark_return",
            ]
        )

    dated_grouped = effects_df.groupby(["date"] + group_by, dropna=False).apply(
        lambda group: pd.Series(
            {
                "portfolio_weight": float(pd.to_numeric(group["w_p"], errors="coerce").fillna(0.0).sum()),
                "benchmark_weight": float(pd.to_numeric(group["w_b"], errors="coerce").fillna(0.0).sum()),
                "portfolio_return": _calculate_weighted_average_return(group["w_p"], group["r_base_p"]),
                "benchmark_return": _calculate_weighted_average_return(group["w_b"], group["r_base_b"]),
            }
        ),
        include_groups=False,
    )

    grouped = dated_grouped.groupby(level=group_by, dropna=False)
    return grouped.apply(
        lambda group: pd.Series(
            {
                "portfolio_weight_avg": float(pd.to_numeric(group["portfolio_weight"], errors="coerce").mean()),
                "benchmark_weight_avg": float(pd.to_numeric(group["benchmark_weight"], errors="coerce").mean()),
                "portfolio_return": _calculate_linked_return(group["portfolio_return"]),
                "benchmark_return": _calculate_linked_return(group["benchmark_return"]),
            }
        )
    )


def _build_group_key_dict(group_key: object, level_group_by: list[str]) -> dict[str, object]:
    """Normalizes a grouped index key into the response key dictionary."""
    if isinstance(group_key, tuple):
        return {key_name: group_key[index] for index, key_name in enumerate(level_group_by)}
    return {level_group_by[0]: group_key}


def _build_attribution_group_result(
    group_key: object,
    level_group_by: list[str],
    row: pd.Series,
) -> AttributionGroupResult:
    """Builds a single attribution group row with side-by-side portfolio and benchmark context."""
    return AttributionGroupResult(
        key=_build_group_key_dict(group_key, level_group_by),
        portfolio_weight_avg=float(row["portfolio_weight_avg"]) * 100,
        benchmark_weight_avg=float(row["benchmark_weight_avg"]) * 100,
        portfolio_return=float(row["portfolio_return"]) * 100,
        benchmark_return=float(row["benchmark_return"]) * 100,
        allocation=float(row["allocation"]) * 100,
        selection=float(row["selection"]) * 100,
        interaction=float(row["interaction"]) * 100,
        total_effect=float(row["total_effect"]) * 100,
    )


def _normalize_instrument_group_columns(full_df: pd.DataFrame, group_cols: list[str]) -> None:
    for group_col in group_cols:
        if group_col not in full_df.columns:
            full_df[group_col] = "unknown"
            continue
        full_df[group_col] = full_df[group_col].where(
            full_df[group_col].notna() & (full_df[group_col].astype(str).str.len() > 0),
            "unknown",
        )


def _prepare_data_from_instruments(request: AttributionRequestLike) -> list[AttributionObservationGroup]:
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

    portfolio_df = create_engine_dataframe_from_valuation_points(
        [item.model_dump() for item in request.portfolio_data.valuation_points]
    )
    portfolio_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(portfolio_df[PortfolioColumns.PERF_DATE.value])
    portfolio_df = portfolio_df.set_index(PortfolioColumns.PERF_DATE.value)
    portfolio_bop_mv = portfolio_df[PortfolioColumns.BEGIN_MV.value] + portfolio_df[PortfolioColumns.BOD_CF.value]

    all_instruments = _instrument_attribution_panels(
        request=request,
        twr_config=twr_config,
        portfolio_bop_mv=portfolio_bop_mv,
    )

    if not all_instruments:
        return []

    full_df = pd.concat(all_instruments)
    group_cols = list(request.group_by)
    _normalize_instrument_group_columns(full_df, group_cols)

    aggregated_panel = _build_instrument_group_aggregation(full_df, group_cols)
    return _build_instrument_attribution_groups(aggregated_panel, group_cols)


def _instrument_attribution_panels(
    *,
    request: AttributionRequestLike,
    twr_config: EngineConfig,
    portfolio_bop_mv: pd.Series,
) -> list[pd.DataFrame]:
    panels: list[pd.DataFrame] = []
    for inst in request.instruments_data:
        instrument_panel = _build_instrument_attribution_panel(
            inst=inst,
            request=request,
            twr_config=twr_config,
            portfolio_bop_mv=portfolio_bop_mv,
        )
        if instrument_panel is not None:
            panels.append(instrument_panel)
    return panels


def _build_instrument_attribution_panel(
    *,
    inst: AttributionInstrumentDataLike,
    request: AttributionRequestLike,
    twr_config: EngineConfig,
    portfolio_bop_mv: pd.Series,
) -> pd.DataFrame | None:
    if not inst.valuation_points:
        return None

    inst_results = run_engine_for_valuation_points(
        [item.model_dump() for item in inst.valuation_points],
        twr_config,
        force_base_only=not (request.currency_mode == "BOTH" and inst.meta.get("currency") != request.report_ccy),
    )
    inst_results = inst_results.set_index(PortfolioColumns.PERF_DATE.value)

    inst_bop_mv = _instrument_bop_mv_series(inst_results, inst.meta)
    with np.errstate(divide="ignore", invalid="ignore"):
        weight_bop = inst_bop_mv / portfolio_bop_mv
    inst_results["weight_bop"] = weight_bop.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    _normalize_instrument_return_columns(
        inst_results,
        currency_mode=request.currency_mode,
        instrument_currency=inst.meta.get("currency"),
        report_ccy=request.report_ccy,
    )

    for key, value in inst.meta.items():
        inst_results[key] = value
    return inst_results.reset_index()


def _instrument_bop_mv_series(inst_results: pd.DataFrame, meta: Mapping[str, Any]) -> pd.Series:
    base_weight_series = _build_base_weight_series(meta)
    if base_weight_series is not None:
        return base_weight_series.reindex(inst_results.index).fillna(0.0)
    return inst_results[PortfolioColumns.BEGIN_MV.value] + inst_results[PortfolioColumns.BOD_CF.value]


def _normalize_instrument_return_columns(
    inst_results: pd.DataFrame,
    *,
    currency_mode: object,
    instrument_currency: object,
    report_ccy: object,
) -> None:
    inst_results.rename(
        columns={
            PortfolioColumns.DAILY_ROR.value: "return_base",
            "local_ror": "return_local",
            "fx_ror": "return_fx",
        },
        inplace=True,
    )
    _backfill_same_currency_return_columns(
        inst_results,
        currency_mode=currency_mode,
        instrument_currency=instrument_currency,
        report_ccy=report_ccy,
    )

    for col in ["return_base", "return_local", "return_fx"]:
        if col in inst_results.columns:
            inst_results[col] /= 100


def _backfill_same_currency_return_columns(
    inst_results: pd.DataFrame,
    *,
    currency_mode: object,
    instrument_currency: object,
    report_ccy: object,
) -> None:
    if currency_mode != "BOTH" or instrument_currency != report_ccy:
        return
    if "return_local" not in inst_results.columns:
        inst_results["return_local"] = inst_results["return_base"]
    if "return_fx" not in inst_results.columns:
        inst_results["return_fx"] = 0.0


def _build_instrument_group_aggregation(full_df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return_cols = ["return_base", "return_local", "return_fx"]
    for col in return_cols:
        if col in full_df.columns:
            full_df[f"weighted_{col}"] = full_df[col] * full_df["weight_bop"]

    grouped = full_df.groupby([PortfolioColumns.PERF_DATE.value] + group_cols, dropna=False)
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
    return aggregated_panel


def _build_instrument_attribution_groups(
    aggregated_panel: pd.DataFrame, group_cols: list[str]
) -> list[AttributionObservationGroup]:
    output_groups = []
    for keys, group_df in aggregated_panel.groupby(group_cols):
        output_groups.append(
            AttributionObservationGroup(
                key=_build_group_key_dict(keys, group_cols),
                observations=_instrument_group_observations(group_df),
            )
        )
    return output_groups


def _instrument_group_observations(group_df: pd.DataFrame) -> list[dict[str, Any]]:
    return_cols = ["return_base", "return_local", "return_fx"]
    obs_cols = [PortfolioColumns.PERF_DATE.value, "weight_bop"] + return_cols
    obs_df = group_df[[col for col in obs_cols if col in group_df.columns]]
    return obs_df.rename(columns={PortfolioColumns.PERF_DATE.value: "date"}).to_dict(orient="records")


def _build_base_weight_series(meta: Mapping[str, Any]) -> pd.Series | None:
    weight_points_raw = meta.get("base_weight_points")
    if not isinstance(weight_points_raw, list):
        return None

    records: list[_BaseWeightRecord] = []
    for item in weight_points_raw:
        record = _base_weight_record_from_point(item)
        if record is not None:
            records.append(record)

    if not records:
        return None

    weights_df = pd.DataFrame(records).drop_duplicates(subset=["date"], keep="last").set_index("date")
    return weights_df["capital"]


def _base_weight_record_from_point(item: object) -> _BaseWeightRecord | None:
    if not isinstance(item, dict):
        return None
    perf_date = item.get("perf_date")
    begin_mv = item.get("begin_mv")
    bod_cf = item.get("bod_cf", 0.0)
    if perf_date is None or begin_mv is None:
        return None
    return {
        "date": pd.to_datetime(perf_date),
        "capital": float(begin_mv) + float(bod_cf),
    }


def _attribution_group_observation_record(
    obs: Any,
    group_key_tuple: tuple[Any, ...],
    group_by: Sequence[str],
) -> dict[str, Any]:
    obs_data = obs if isinstance(obs, dict) else obs.model_dump()
    return_base = obs_data.get("return_base")
    if return_base is None:
        return_base = obs_data.get("return")
    record = {
        "date": pd.to_datetime(obs_data["date"]),
        "weight_bop": obs_data.get("weight_bop", 0.0),
        "return_base": return_base,
        "return_local": obs_data.get("return_local"),
        "return_fx": obs_data.get("return_fx"),
        "has_return_base": return_base is not None,
    }
    for index, key in enumerate(group_by):
        record[key] = group_key_tuple[index]
    return record


def _prepare_panel_from_groups(
    groups: Sequence[AttributionObservationGroupLike], group_by: Sequence[str]
) -> pd.DataFrame:
    """Helper to convert list of group data into a tidy DataFrame panel."""
    all_obs = []
    if not groups:
        return pd.DataFrame()

    for group in groups:
        group_key_tuple = tuple(group.key.get(k) for k in group_by)
        for obs in group.observations:
            all_obs.append(_attribution_group_observation_record(obs, group_key_tuple, group_by))

    if not all_obs:
        return pd.DataFrame()
    df = pd.DataFrame(all_obs)
    return df.set_index(["date"] + group_by)


def _align_and_prepare_data(
    request: AttributionRequestLike,
    portfolio_groups_data: Sequence[AttributionObservationGroupLike],
) -> pd.DataFrame:
    """Pre-processes and aligns portfolio and benchmark group data for attribution."""
    group_by = list(request.group_by)
    portfolio_panel = _prepare_panel_from_groups(portfolio_groups_data, group_by)
    benchmark_panel = _prepare_panel_from_groups(request.benchmark_groups_data, group_by)

    if portfolio_panel.empty or benchmark_panel.empty:
        return pd.DataFrame()

    freq_map = {"daily": "D", "monthly": "ME", "quarterly": "QE", "yearly": "YE"}
    freq_code = freq_map.get(request.frequency.value, "ME")

    return_cols = ["return_base", "return_local", "return_fx"]

    def first_row_preserving_missing(series: pd.Series) -> float | None:
        if series.empty:
            return None
        first_value = series.iloc[0]
        return None if pd.isna(first_value) else float(first_value)

    def link_period_returns(series: pd.Series) -> float | None:
        numeric_returns = pd.to_numeric(series, errors="coerce").dropna()
        if numeric_returns.empty:
            return None
        return float((1 + numeric_returns).prod() - 1)

    def resample_panel(panel):
        wide_panel = panel.unstack(level=group_by).sort_index()
        weights = (
            wide_panel["weight_bop"]
            .resample(freq_code)
            .agg(first_row_preserving_missing)
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
        )
        resampled_data = {"w": weights}
        for col in return_cols:
            if col in wide_panel.columns.get_level_values(0) and panel[col].notna().any():
                resampled_data[f"r_{col.split('_')[1]}"] = (
                    wide_panel[col]
                    .resample(freq_code)
                    .agg(link_period_returns)
                    .apply(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                )
        if "has_return_base" in wide_panel.columns.get_level_values(0):
            resampled_data["has_base_return"] = (
                wide_panel["has_return_base"].resample(freq_code).max().where(lambda series: series.notna(), False)
            )
        return pd.concat(
            [df.stack(group_by, future_stack=True) for df in resampled_data.values()],
            axis=1,
            keys=resampled_data.keys(),
        )

    df_p = resample_panel(portfolio_panel)
    df_b = resample_panel(benchmark_panel)

    aligned_df = pd.merge(df_p, df_b, left_index=True, right_index=True, how="outer", suffixes=("_p", "_b"))
    return _finalize_aligned_attribution_frame(aligned_df, group_by)


def _finalize_aligned_attribution_frame(aligned_df: pd.DataFrame, group_by: Sequence[str]) -> pd.DataFrame:
    aligned_df["portfolio_observation_present"] = aligned_df["w_p"].notna() | aligned_df["r_base_p"].notna()
    aligned_df["benchmark_observation_present"] = aligned_df["w_b"].notna() | aligned_df["r_base_b"].notna()
    if "has_base_return_b" not in aligned_df.columns:
        aligned_df["has_base_return_b"] = aligned_df["r_base_b"].notna()
    if "has_base_return_p" not in aligned_df.columns:
        aligned_df["has_base_return_p"] = aligned_df["r_base_p"].notna()
    bool_columns = {
        "portfolio_observation_present",
        "benchmark_observation_present",
        "has_base_return_p",
        "has_base_return_b",
    }
    for column in aligned_df.columns:
        if column in bool_columns:
            aligned_df[column] = aligned_df[column].where(aligned_df[column].notna(), False).astype(bool)
        else:
            aligned_df[column] = aligned_df[column].fillna(0.0)
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


def _build_currency_attribution_panel(effects_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregates granular attribution rows into a date/currency panel.

    Currency attribution is portfolio-level evidence. If callers request a more granular grouping,
    such as currency plus sector, returns must be recomputed as currency-weighted returns rather
    than summed across the visible groups.
    """
    currency_input = effects_df.reset_index()

    def aggregate_currency_row(group: pd.DataFrame) -> pd.Series:
        w_p = pd.to_numeric(group["w_p"], errors="coerce").fillna(0.0)
        w_b = pd.to_numeric(group["w_b"], errors="coerce").fillna(0.0)
        return pd.Series(
            {
                "w_p": float(w_p.sum()),
                "w_b": float(w_b.sum()),
                "r_local_p": _calculate_weighted_average_return(w_p, group["r_local_p"]),
                "r_local_b": _calculate_weighted_average_return(w_b, group["r_local_b"]),
                "r_fx_b": _calculate_weighted_average_return(w_b, group["r_fx_b"]),
            }
        )

    return currency_input.groupby(["date", "currency"], dropna=False).apply(
        aggregate_currency_row,
        include_groups=False,
    )


def _currency_attribution_requirements_met(effects_df: pd.DataFrame, request: AttributionRequestLike) -> bool:
    required_cols = {"r_local_p", "r_local_b", "r_fx_b", "w_p", "w_b"}
    if request.currency_mode != "BOTH":
        return False
    if "currency" not in request.group_by:
        return False
    if not required_cols.issubset(effects_df.columns):
        return False
    return "currency" in effects_df.reset_index().columns


def _currency_attribution_status(effects_df: pd.DataFrame, request: AttributionRequestLike) -> str:
    if request.currency_mode != "BOTH":
        return "not_requested"
    return "complete" if _currency_attribution_requirements_met(effects_df, request) else "unavailable"


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


def _build_attribution_levels(
    granular_totals: pd.DataFrame,
    effects_reset: pd.DataFrame,
    group_by: Sequence[str],
) -> list[AttributionLevelResult]:
    levels: list[AttributionLevelResult] = []
    granular_totals_df = granular_totals.reset_index()
    effect_columns = ["allocation", "selection", "interaction"]

    for index in range(len(group_by), 0, -1):
        level_group_by = list(group_by[:index])
        level_totals = granular_totals_df.groupby(level_group_by).sum(numeric_only=True)
        level_context = _calculate_group_context_metrics(effects_reset, level_group_by)
        level_totals = level_totals.join(level_context, how="left").fillna(0.0)
        level_totals["total_effect"] = level_totals[effect_columns].sum(axis=1)

        group_results = [
            _build_attribution_group_result(group_key, level_group_by, row)
            for group_key, row in level_totals.iterrows()
        ]
        overall_level_totals = level_totals[effect_columns + ["total_effect"]].sum()
        levels.append(
            AttributionLevelResult(
                dimension=" -> ".join(level_group_by),
                groups=sorted(group_results, key=lambda item: str(item.key)),
                totals=AttributionLevelTotals(**(overall_level_totals * 100).to_dict()),
            )
        )

    levels.reverse()
    return levels


def aggregate_attribution_results(
    effects_df: pd.DataFrame, request: AttributionRequestLike
) -> Tuple[SinglePeriodAttributionResult, Dict[str, pd.DataFrame]]:
    """Aggregates a DataFrame of daily effects into the final response model for a single period."""
    aggregation_lineage = {}
    aggregation_base = _build_attribution_aggregation_base(effects_df, request)

    effects_reset = effects_df.reset_index()
    levels = _build_attribution_levels(aggregation_base.granular_totals, effects_reset, request.group_by)
    final_totals = (
        levels[0].totals if levels else AttributionLevelTotals(allocation=0, selection=0, interaction=0, total_effect=0)
    )
    residual = (aggregation_base.active_return * 100) - final_totals.total_effect
    residual_materiality = classify_attribution_residual(residual)

    currency_attribution_status = _currency_attribution_status(effects_df, request)

    status, reason_codes, reasons, supportability_evidence, supportability_lineage = (
        build_attribution_supportability_evidence(
            effects_df,
            request,
            currency_attribution_status=currency_attribution_status,
            linking_status=aggregation_base.linking_status,
            residual_materiality=residual_materiality,
        )
    )
    aggregation_lineage["attribution_supportability_evidence.csv"] = supportability_lineage

    period_result = SinglePeriodAttributionResult(
        status=status,
        reason_codes=reason_codes,
        reasons=reasons,
        supportability_evidence=supportability_evidence,
        levels=levels,
        reconciliation=Reconciliation(
            total_active_return=aggregation_base.active_return * 100,
            sum_of_effects=final_totals.total_effect,
            residual=residual,
            residual_materiality=residual_materiality,
        ),
    )

    if request.currency_mode == "BOTH":
        if currency_attribution_status == "complete":
            currency_df = _build_currency_attribution_panel(effects_df)
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
            period_result.currency_attribution_totals = CurrencyAttributionTotals(
                local_allocation=total_fx_effects["local_allocation"].sum() * 100,
                local_selection=total_fx_effects["local_selection"].sum() * 100,
                currency_allocation=total_fx_effects["currency_allocation"].sum() * 100,
                currency_selection=total_fx_effects["currency_selection"].sum() * 100,
                total_effect=(
                    total_fx_effects[
                        [
                            "local_allocation",
                            "local_selection",
                            "currency_allocation",
                            "currency_selection",
                        ]
                    ]
                    .sum()
                    .sum()
                    * 100
                ),
                currency_count=len(fx_results),
            )

    return period_result, aggregation_lineage


def _build_attribution_aggregation_base(
    effects_df: pd.DataFrame, request: AttributionRequestLike
) -> _AttributionAggregationBase:
    per_period_p_return = (effects_df["w_p"] * effects_df["r_base_p"]).groupby(level="date").sum()
    per_period_b_return = effects_df.groupby(level="date")["r_b_total"].first()
    per_period_active_return = per_period_p_return - per_period_b_return

    if request.linking == LinkingMethod.NONE:
        return _AttributionAggregationBase(
            active_return=per_period_active_return.sum(),
            granular_totals=effects_df.groupby(request.group_by)[["allocation", "selection", "interaction"]].sum(),
            linking_status="not_requested",
        )

    arithmetic_active_return = per_period_active_return.sum()
    invalid_return_chain = bool(((per_period_p_return <= -1) | (per_period_b_return <= -1)).any())
    if invalid_return_chain:
        linking_status = "invalid_return_chain"
        geometric_active_return = arithmetic_active_return
        scaled_effects = effects_df.reset_index()
    else:
        geometric_active_return = (1 + per_period_p_return).prod() - 1 - ((1 + per_period_b_return).prod() - 1)
        linking_status = "scaling_skipped" if arithmetic_active_return == 0 else "linked"
        scaled_effects = _link_effects_top_down(
            effects_df.reset_index(), geometric_active_return, arithmetic_active_return
        )
    return _AttributionAggregationBase(
        active_return=geometric_active_return,
        granular_totals=scaled_effects.groupby(request.group_by)[["allocation", "selection", "interaction"]].sum(),
        linking_status=linking_status,
    )


def run_attribution_calculations(request: AttributionRequestLike) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
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
