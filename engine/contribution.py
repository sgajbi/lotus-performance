# engine/contribution.py
from dataclasses import dataclass, replace
from datetime import date as dt_date
from decimal import Decimal
from typing import Any, Dict, Iterator, Mapping, Protocol, Sequence, Tuple

import numpy as np
import pandas as pd

from common.enums import WeightingScheme
from engine.config import EndingValueBasis, EngineConfig, PrecisionMode
from engine.contribution_fee_basis import contribution_data_policy_for_entity
from engine.contribution_smoothing import (
    ContributionSmoothingLike,
    _calculate_carino_factor_for_return,
    _calculate_carino_factors,
    _carino_smoothing_domain_is_valid,
    apply_contribution_smoothing,
)
from engine.diagnostics import EngineDiagnostics
from engine.runtime import run_engine_for_valuation_points_with_diagnostics
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

_RESIDUAL_DENOMINATOR_TOLERANCE = 1e-12
_DECIMAL_RESIDUAL_DENOMINATOR_TOLERANCE = Decimal("1e-12")
_DAILY_CONTRIBUTION_REQUIRED_COLUMNS = (
    "position_id",
    PortfolioColumns.PERF_DATE.value,
    "daily_weight",
    "smoothed_contribution",
    "smoothed_local_contribution",
    "smoothed_fx_contribution",
)


@dataclass(frozen=True)
class ContributionPreparedData:
    """Prepared contribution frames plus diagnostics from every engine run."""

    instruments_df: pd.DataFrame
    portfolio_results_df: pd.DataFrame
    engine_diagnostics: tuple[EngineDiagnostics, ...]

    def __iter__(self) -> Iterator[pd.DataFrame]:
        """Preserve the established two-frame unpacking contract."""
        yield self.instruments_df
        yield self.portfolio_results_df


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
    def portfolio_id(self) -> str: ...

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
    def currency(self) -> str: ...

    @property
    def fx(self) -> Any: ...

    @property
    def hedging(self) -> Any: ...

    @property
    def data_policy(self) -> Any: ...

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
        empty_result = instruments_df.copy()
        for column_name in _DAILY_CONTRIBUTION_REQUIRED_COLUMNS:
            if column_name not in empty_result.columns:
                empty_result[column_name] = pd.Series(dtype="object")
        return empty_result

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

    decimal_mode = _series_uses_decimal(df["capital_inst"]) or _series_uses_decimal(df["capital_port"])
    zero = Decimal(0) if decimal_mode else 0.0
    hundred = Decimal(100) if decimal_mode else 100.0
    df["daily_weight"] = _safe_daily_weight(
        df["capital_inst"],
        df["capital_port"],
        decimal_mode=decimal_mode,
    )

    local_ror = _numeric_column_or_zero(df, "local_ror", zero=zero, decimal_mode=decimal_mode)
    fx_ror = _numeric_column_or_zero(df, "fx_ror", zero=zero, decimal_mode=decimal_mode)
    df["raw_local_contribution"] = df["daily_weight"] * (local_ror / hundred)
    df["raw_fx_contribution"] = df["daily_weight"] * (fx_ror / hundred)
    df["raw_contribution"] = df["daily_weight"] * (df[PortfolioColumns.DAILY_ROR.value] / hundred)
    df = apply_contribution_smoothing(df, portfolio_df, smoothing)

    nip_reset_dates = portfolio_df[
        (portfolio_df[PortfolioColumns.NIP.value] == 1) | (portfolio_df[PortfolioColumns.PERF_RESET.value] == 1)
    ][PortfolioColumns.PERF_DATE.value]

    contrib_cols = ["smoothed_contribution", "smoothed_local_contribution", "smoothed_fx_contribution"]
    df.loc[df[PortfolioColumns.PERF_DATE.value].isin(nip_reset_dates), contrib_cols] = zero

    return df


def _series_uses_decimal(series: pd.Series) -> bool:
    return any(isinstance(value, Decimal) for value in series if pd.notna(value))


def _safe_daily_weight(
    numerator: pd.Series,
    denominator: pd.Series,
    *,
    decimal_mode: bool,
) -> pd.Series:
    zero = Decimal(0) if decimal_mode else 0.0
    if decimal_mode:
        return pd.Series(
            [
                zero if pd.isna(amount) or pd.isna(value) or value == zero else amount / value
                for amount, value in zip(numerator, denominator, strict=True)
            ],
            index=numerator.index,
            dtype=object,
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        daily_weight = numerator / denominator
    return daily_weight.replace([np.inf, -np.inf], np.nan).fillna(zero)


def _numeric_column_or_zero(
    frame: pd.DataFrame,
    column_name: str,
    *,
    zero: Decimal | float,
    decimal_mode: bool,
) -> pd.Series:
    if column_name in frame.columns:
        return frame[column_name]
    return pd.Series(
        [zero] * len(frame),
        index=frame.index,
        dtype=object if decimal_mode else None,
    )


def _prepare_hierarchical_data(request: ContributionRequestLike) -> ContributionPreparedData:
    """
    Runs TWR calculations and combines all position data and metadata into a single DataFrame.
    """
    twr_config = _build_contribution_twr_config(request)
    portfolio_results_df, portfolio_diagnostics = run_engine_for_valuation_points_with_diagnostics(
        [item.model_dump() for item in request.portfolio_data.valuation_points],
        replace(
            twr_config,
            data_policy=contribution_data_policy_for_entity(
                request.data_policy,
                entity_type="PORTFOLIO",
                entity_id=request.portfolio_id,
            ),
        ),
        force_base_only=twr_config.currency_mode == "BOTH",
    )
    _identify_outlier_samples(portfolio_diagnostics, entity_type="PORTFOLIO", entity_id=request.portfolio_id)

    fx_rates_df = _build_contribution_fx_rates_frame(request)
    all_positions_data = []
    engine_diagnostics = [portfolio_diagnostics]
    for position in request.positions_data:
        if not position.valuation_points:
            continue

        position_results_df, position_diagnostics = _build_position_contribution_results_frame(
            position=position,
            request=request,
            twr_config=twr_config,
            fx_rates_df=fx_rates_df,
        )
        all_positions_data.append(position_results_df)
        _identify_outlier_samples(
            position_diagnostics,
            entity_type="POSITION",
            entity_id=position.position_id,
        )
        engine_diagnostics.append(position_diagnostics)

    if not all_positions_data:
        return ContributionPreparedData(pd.DataFrame(), portfolio_results_df, tuple(engine_diagnostics))

    instruments_df = pd.concat(all_positions_data, ignore_index=True)
    return ContributionPreparedData(instruments_df, portfolio_results_df, tuple(engine_diagnostics))


def _identify_outlier_samples(
    diagnostics: EngineDiagnostics,
    *,
    entity_type: str,
    entity_id: str,
) -> None:
    for sample in diagnostics.samples.outliers:
        sample.entity_type = entity_type
        sample.entity_id = entity_id


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
        source_currency=request.currency,
        fx=request.fx,
        hedging=request.hedging,
        ending_value_basis=EndingValueBasis.AFTER_FEES,
    )


def _build_contribution_fx_rates_frame(request: ContributionRequestLike) -> pd.DataFrame:
    if request.currency_mode != "BOTH" or not request.fx or not request.fx.rates:
        return pd.DataFrame()
    fx_rates_df = pd.DataFrame([rate.model_dump() for rate in request.fx.rates])
    fx_rates_df["date"] = pd.to_datetime(fx_rates_df["date"])
    fx_rates_df.drop_duplicates(subset=["date", "ccy"], keep="last", inplace=True)
    if request.precision_mode == PrecisionMode.DECIMAL_STRICT:
        fx_rates_df["rate"] = fx_rates_df["rate"].map(lambda value: Decimal(str(value)))
    return fx_rates_df


def _build_position_contribution_results_frame(
    *,
    position: ContributionPositionDataLike,
    request: ContributionRequestLike,
    twr_config: EngineConfig,
    fx_rates_df: pd.DataFrame,
) -> tuple[pd.DataFrame, EngineDiagnostics]:
    position_ccy = position.meta.get("currency")
    position_results_df, diagnostics = run_engine_for_valuation_points_with_diagnostics(
        [item.model_dump() for item in position.valuation_points],
        replace(
            twr_config,
            source_currency=str(position_ccy) if position_ccy is not None else None,
            data_policy=contribution_data_policy_for_entity(
                request.data_policy,
                entity_type="POSITION",
                entity_id=position.position_id,
            ),
        ),
        force_base_only=not (
            request.currency_mode == "BOTH" and not _currency_values_match(position_ccy, request.report_ccy)
        ),
    )
    _ensure_same_currency_local_fx_columns(
        position_results_df=position_results_df,
        request=request,
        position_ccy=position_ccy,
    )
    position_results_df["position_id"] = position.position_id
    for key, value in position.meta.items():
        if key.startswith("_"):
            continue
        position_results_df[key] = value
    return (
        _apply_position_fx_capital_conversion(
            position_results_df=position_results_df,
            request=request,
            position_ccy=position_ccy,
            fx_rates_df=fx_rates_df,
        ),
        diagnostics,
    )


def _ensure_same_currency_local_fx_columns(
    *,
    position_results_df: pd.DataFrame,
    request: ContributionRequestLike,
    position_ccy: Any,
) -> None:
    if (
        request.currency_mode != "BOTH"
        or not _currency_values_match(position_ccy, request.report_ccy)
        or "local_ror" in position_results_df.columns
    ):
        return
    position_results_df["local_ror"] = position_results_df[PortfolioColumns.DAILY_ROR.value]
    zero = Decimal(0) if _series_uses_decimal(position_results_df[PortfolioColumns.DAILY_ROR.value]) else 0.0
    position_results_df["fx_ror"] = zero


def _apply_position_fx_capital_conversion(
    *,
    position_results_df: pd.DataFrame,
    request: ContributionRequestLike,
    position_ccy: Any,
    fx_rates_df: pd.DataFrame,
) -> pd.DataFrame:
    if not _requires_position_fx_capital_conversion(
        request=request,
        position_ccy=position_ccy,
        fx_rates_df=fx_rates_df,
    ):
        return position_results_df
    pos_fx_lookup = (
        fx_rates_df[
            fx_rates_df["ccy"].str.strip().str.upper()
            == (position_ccy.strip().upper() if isinstance(position_ccy, str) else position_ccy)
        ][["date", "rate"]]
        .drop_duplicates(subset=["date"], keep="last")
        .set_index("date")["rate"]
    )
    converted_df = position_results_df.copy()
    converted_df["prior_date"] = converted_df[PortfolioColumns.PERF_DATE.value] - pd.Timedelta(days=1)
    conversion_rates = converted_df["prior_date"].map(pos_fx_lookup)
    for col in [PortfolioColumns.BEGIN_MV.value, PortfolioColumns.BOD_CF.value]:
        converted_df[col] *= conversion_rates
    return converted_df


def _requires_position_fx_capital_conversion(
    *,
    request: ContributionRequestLike,
    position_ccy: Any,
    fx_rates_df: pd.DataFrame,
) -> bool:
    return (
        request.currency_mode == "BOTH"
        and not _currency_values_match(position_ccy, request.report_ccy)
        and not fx_rates_df.empty
    )


def _currency_values_match(left: object, right: object) -> bool:
    return isinstance(left, str) and isinstance(right, str) and left.strip().upper() == right.strip().upper()


def calculate_hierarchical_contribution(request: ContributionRequestLike) -> Tuple[Dict, Dict]:
    instruments_df, portfolio_results_df = _prepare_hierarchical_data(request)

    daily_contributions_df = _calculate_daily_instrument_contributions(
        instruments_df, portfolio_results_df, request.weighting_scheme, request.smoothing
    )

    decimal_mode = _series_uses_decimal(portfolio_results_df[PortfolioColumns.DAILY_ROR.value])
    hundred = Decimal(100) if decimal_mode else 100.0
    one = Decimal(1) if decimal_mode else 1.0
    port_ror_series = portfolio_results_df[PortfolioColumns.DAILY_ROR.value] / hundred
    total_portfolio_return = (one + port_ror_series).prod() - one

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
        return {"summary": _empty_hierarchical_contribution_summary(request), "levels": []}

    totals = _position_contribution_totals(daily_contributions_df)
    _apply_carino_residual_allocation(
        totals,
        total_portfolio_return=total_portfolio_return,
        smoothing_method=request.smoothing.method,
    )

    hierarchy = list(request.hierarchy or [])
    aggregated_df = _merge_hierarchy_metadata(
        daily_contributions_df=daily_contributions_df,
        totals=totals,
        hierarchy=hierarchy,
    )
    response_levels = _build_hierarchical_response_levels(
        aggregated_df=aggregated_df,
        hierarchy=hierarchy,
        currency_mode=request.currency_mode,
    )

    return {
        "summary": _hierarchical_contribution_summary(aggregated_df, request),
        "levels": response_levels,
    }


def _empty_hierarchical_contribution_summary(request: ContributionRequestLike) -> dict[str, Any]:
    summary = {
        "portfolio_contribution": 0.0,
        "coverage_mv_pct": 100.0,
        "weighting_scheme": request.weighting_scheme.value,
    }
    if request.currency_mode == "BOTH":
        summary["local_contribution"] = 0.0
        summary["fx_contribution"] = 0.0
    return summary


def _position_contribution_totals(daily_contributions_df: pd.DataFrame) -> pd.DataFrame:
    return (
        daily_contributions_df.groupby("position_id")
        .agg(
            contribution=("smoothed_contribution", "sum"),
            local_contribution=("smoothed_local_contribution", "sum"),
            fx_contribution=("smoothed_fx_contribution", "sum"),
            weight_avg=("daily_weight", "mean"),
        )
        .reset_index()
    )


def _merge_hierarchy_metadata(
    *,
    daily_contributions_df: pd.DataFrame,
    totals: pd.DataFrame,
    hierarchy: list[str],
) -> pd.DataFrame:
    metadata_cols = list(dict.fromkeys(["position_id", *hierarchy]))
    unique_meta = daily_contributions_df[metadata_cols].drop_duplicates()
    return pd.merge(totals, unique_meta, on="position_id")


def _hierarchical_contribution_summary(
    aggregated_df: pd.DataFrame,
    request: ContributionRequestLike,
) -> dict[str, Any]:
    summary = {
        "portfolio_contribution": aggregated_df["contribution"].sum() * 100,
        "coverage_mv_pct": 100.0,
        "weighting_scheme": request.weighting_scheme.value,
    }
    if request.currency_mode == "BOTH":
        summary["local_contribution"] = aggregated_df["local_contribution"].sum() * 100
        summary["fx_contribution"] = aggregated_df["fx_contribution"].sum() * 100
    return summary


def _build_hierarchical_response_levels(
    *,
    aggregated_df: pd.DataFrame,
    hierarchy: list[str],
    currency_mode: str,
) -> list[dict[str, Any]]:
    response_levels = []
    for index, level_name in enumerate(hierarchy):
        level_keys = hierarchy[: index + 1]
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
        response_levels.append(
            {
                "level": index + 1,
                "name": level_name,
                "parent": hierarchy[index - 1] if index > 0 else None,
                "rows": [
                    _hierarchical_response_row(row, level_keys=level_keys, currency_mode=currency_mode)
                    for _, row in level_agg.iterrows()
                ],
            }
        )
    return response_levels


def _hierarchical_response_row(
    row: pd.Series,
    *,
    level_keys: list[str],
    currency_mode: str,
) -> dict[str, Any]:
    row_data = {
        "key": {key: row[key] for key in level_keys},
        "contribution": row["contribution"] * 100,
        "weight_avg": row["weight_avg"] * 100,
    }
    if currency_mode == "BOTH":
        row_data["local_contribution"] = row["local_contribution"] * 100
        row_data["fx_contribution"] = row["fx_contribution"] * 100
    return row_data


def _apply_carino_residual_allocation(
    totals: pd.DataFrame,
    *,
    total_portfolio_return,
    smoothing_method: str,
) -> None:
    total_avg_weight = totals["weight_avg"].sum()
    if total_avg_weight == 0 or smoothing_method != "CARINO":
        return

    totals["weight_proportion"] = totals["weight_avg"] / total_avg_weight
    sum_of_contributions = totals["contribution"].sum()
    residual = total_portfolio_return - sum_of_contributions
    local_prop, fx_prop = _local_fx_residual_proportions(
        local_contribution_sum=totals["local_contribution"].sum(),
        fx_contribution_sum=totals["fx_contribution"].sum(),
        total_contribution_sum=sum_of_contributions,
    )

    totals["contribution"] += residual * totals["weight_proportion"]
    totals["local_contribution"] += residual * local_prop * totals["weight_proportion"]
    totals["fx_contribution"] += residual * fx_prop * totals["weight_proportion"]


def _local_fx_residual_proportions(
    *,
    local_contribution_sum: Any,
    fx_contribution_sum: Any,
    total_contribution_sum: Any,
) -> tuple[Any, Any]:
    if any(
        isinstance(value, Decimal) for value in (local_contribution_sum, fx_contribution_sum, total_contribution_sum)
    ):
        local_contribution_sum = Decimal(str(local_contribution_sum))
        fx_contribution_sum = Decimal(str(fx_contribution_sum))
        total_contribution_sum = Decimal(str(total_contribution_sum))
        tolerance: Decimal | float = _DECIMAL_RESIDUAL_DENOMINATOR_TOLERANCE
        one: Decimal | float = Decimal(1)
        zero: Decimal | float = Decimal(0)
    else:
        tolerance = _RESIDUAL_DENOMINATOR_TOLERANCE
        one = 1.0
        zero = 0.0

    if abs(total_contribution_sum) > tolerance:
        return (
            local_contribution_sum / total_contribution_sum,
            fx_contribution_sum / total_contribution_sum,
        )

    absolute_component_sum = abs(local_contribution_sum) + abs(fx_contribution_sum)
    if absolute_component_sum <= tolerance:
        return one, zero

    local_share = abs(local_contribution_sum) / absolute_component_sum
    return local_share, one - local_share
