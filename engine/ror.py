# engine/ror.py
import warnings
from decimal import Decimal

import numpy as np
import pandas as pd

from engine.config import EngineConfig
from engine.rules import (
    calculate_account_reset_reason,
    calculate_initial_resets,
    calculate_nctrl4_reset,
    calculate_sod_reset_reason,
)
from engine.schema import PortfolioColumns


def calculate_daily_ror(df: pd.DataFrame, metric_basis: str, config: EngineConfig = None) -> pd.DataFrame:
    """
    Calculates the daily rate of return, supporting both float and Decimal.
    If FX config is provided, it returns a DataFrame with local, fx, and base returns.
    """
    is_decimal_mode = df[PortfolioColumns.BEGIN_MV.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0
    hundred = Decimal(100) if is_decimal_mode else 100.0

    if is_decimal_mode:
        numerator = (
            df[PortfolioColumns.END_MV.value]
            - df[PortfolioColumns.BOD_CF.value]
            - df[PortfolioColumns.BEGIN_MV.value]
            - df[PortfolioColumns.EOD_CF.value]
        )
        if metric_basis == "NET":
            numerator += df[PortfolioColumns.MGMT_FEES.value]
        denominator = (df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value]).abs()
        local_ror = pd.Series([zero] * len(df), index=df.index, dtype=object)
    else:
        numerator = (
            df[PortfolioColumns.END_MV.value]
            - df[PortfolioColumns.BOD_CF.value]
            - df[PortfolioColumns.BEGIN_MV.value]
            - df[PortfolioColumns.EOD_CF.value]
        ).to_numpy(copy=True)
        if metric_basis == "NET":
            numerator += df[PortfolioColumns.MGMT_FEES.value].to_numpy(copy=False)
        denominator = np.abs(df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value]).to_numpy(
            copy=False
        )
        local_ror_np = np.full(denominator.shape, 0.0, dtype=np.float64)

    is_after_start = df[PortfolioColumns.PERF_DATE.value] >= df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value]
    safe_division_mask = (denominator != zero) & is_after_start

    with np.errstate(divide="ignore", invalid="ignore"):
        if is_decimal_mode:
            if safe_division_mask.any():
                local_ror.loc[safe_division_mask] = numerator[safe_division_mask] / denominator[safe_division_mask]
        else:
            np.divide(numerator, denominator, out=local_ror_np, where=safe_division_mask)
            local_ror = pd.Series(local_ror_np, index=df.index)

    result_df = pd.DataFrame(index=df.index)
    if config and config.currency_mode and config.currency_mode != "BASE_ONLY" and config.fx:
        fx_rates_df = pd.DataFrame([rate.model_dump() for rate in config.fx.rates])

        if "date" in fx_rates_df.columns and "ccy" in fx_rates_df.columns:
            fx_rates_df.drop_duplicates(subset=["date", "ccy"], keep="last", inplace=True)

        fx_rates_df["date"] = pd.to_datetime(fx_rates_df["date"])
        fx_rates_df = fx_rates_df.set_index("date")["rate"].sort_index()

        start_dt = pd.to_datetime(config.performance_start_date) - pd.Timedelta(days=1)
        end_dt = df[PortfolioColumns.PERF_DATE.value].max()
        full_date_range = pd.date_range(start=start_dt, end=end_dt, freq="D")
        all_rates = fx_rates_df.reindex(full_date_range).ffill()

        df["start_rate"] = df[PortfolioColumns.PERF_DATE.value].apply(lambda x: all_rates.get(x - pd.Timedelta(days=1)))
        df["end_rate"] = df[PortfolioColumns.PERF_DATE.value].map(all_rates)

        fx_ror = (df["end_rate"] / df["start_rate"]) - 1
        fx_ror = fx_ror.fillna(0.0)

        if config.hedging and config.hedging.mode == "RATIO" and config.hedging.series:
            hedge_series_df = pd.DataFrame([s.model_dump() for s in config.hedging.series])
            if not hedge_series_df.empty:
                hedge_series_df["date"] = pd.to_datetime(hedge_series_df["date"])
                hedge_map = hedge_series_df.set_index("date")["hedge_ratio"]
                hedge_ratios = df[PortfolioColumns.PERF_DATE.value].map(hedge_map).fillna(0.0)
                fx_ror = fx_ror * (1.0 - hedge_ratios)

        result_df["local_ror"] = local_ror * hundred
        result_df["fx_ror"] = fx_ror * hundred
        result_df[PortfolioColumns.DAILY_ROR.value] = ((1 + local_ror) * (1 + fx_ror) - 1) * hundred
    else:
        result_df[PortfolioColumns.DAILY_ROR.value] = local_ror * hundred

    return result_df


def calculate_cumulative_ror(df: pd.DataFrame, config):
    """Calculates cumulative return state and reset-reason shadows.

    The active compounding reset behavior intentionally remains on the existing engine path.
    Explicit account and start-of-day reset reasons are computed as shadow signals so the
    methodology can be characterized safely before those reasons are promoted into the
    active reset state.
    """
    is_decimal_mode = df[PortfolioColumns.DAILY_ROR.value].dtype == "object"
    one = Decimal(1) if is_decimal_mode else 1.0
    hundred = Decimal(100) if is_decimal_mode else 100.0

    component_names = _cumulative_component_names(df)
    _calculate_component_cumulative_returns(df, component_names, temp=True, use_resets=False)

    initial_resets, nctrl1, nctrl2, nctrl3 = calculate_initial_resets(
        df,
        pd.to_datetime(config.report_end_date),
        PortfolioColumns.TEMP_LONG_CUM_ROR.value,
        PortfolioColumns.TEMP_SHORT_CUM_ROR.value,
    )
    df[PortfolioColumns.NCTRL_1.value] = nctrl1.astype(int)
    df[PortfolioColumns.NCTRL_2.value] = nctrl2.astype(int)
    df[PortfolioColumns.NCTRL_3.value] = nctrl3.astype(int)
    df[PortfolioColumns.PERF_RESET.value] = initial_resets.astype(int)

    _calculate_component_cumulative_returns(df, component_names, temp=False, use_resets=True)

    nctrl4_resets = calculate_nctrl4_reset(
        df,
        long_cum_col=PortfolioColumns.LONG_CUM_ROR.value,
        short_cum_col=PortfolioColumns.SHORT_CUM_ROR.value,
    )
    df[PortfolioColumns.NCTRL_4.value] = nctrl4_resets.astype(int)
    df.loc[nctrl4_resets, PortfolioColumns.PERF_RESET.value] = 1
    df[PortfolioColumns.ACCOUNT_RESET.value] = calculate_account_reset_reason(df)
    df[PortfolioColumns.SOD_RESET.value] = calculate_sod_reset_reason(
        df,
        (df[PortfolioColumns.PERF_RESET.value] == 1) | (df[PortfolioColumns.ACCOUNT_RESET.value] == 1),
    )

    _zero_component_cumulative_returns(
        df,
        component_names,
        reset_mask=df[PortfolioColumns.PERF_RESET.value] == 1,
    )
    _apply_nip_to_component_cumulative_returns(df, component_names)

    df[PortfolioColumns.FINAL_CUM_ROR.value] = (
        (one + df[PortfolioColumns.LONG_CUM_ROR.value] / hundred)
        * (one + df[PortfolioColumns.SHORT_CUM_ROR.value] / hundred)
        - one
    ) * hundred


def _cumulative_component_names(df: pd.DataFrame) -> list[str]:
    component_names = [PortfolioColumns.DAILY_ROR.value]
    if "local_ror" in df.columns:
        component_names.append("local_ror")
    if "fx_ror" in df.columns:
        component_names.append("fx_ror")
    return component_names


def _component_prefix(component_name: str, *, temp: bool) -> str:
    base_prefix = "" if component_name == PortfolioColumns.DAILY_ROR.value else f"{component_name}_"
    return f"temp_{base_prefix}" if temp else base_prefix


def _calculate_component_cumulative_returns(
    df: pd.DataFrame,
    component_names: list[str],
    *,
    temp: bool,
    use_resets: bool,
) -> None:
    for component_name in component_names:
        prefix = _component_prefix(component_name, temp=temp)
        df[f"{prefix}long_cum_ror"] = _compound_ror(df, df[component_name], "long", use_resets=use_resets)
        df[f"{prefix}short_cum_ror"] = _compound_ror(df, df[component_name], "short", use_resets=use_resets)


def _zero_component_cumulative_returns(
    df: pd.DataFrame,
    component_names: list[str],
    *,
    reset_mask: pd.Series,
) -> None:
    zero_value = 0.0
    for component_name in component_names:
        prefix = _component_prefix(component_name, temp=False)
        df.loc[reset_mask, [f"{prefix}long_cum_ror", f"{prefix}short_cum_ror"]] = zero_value


def _apply_nip_to_component_cumulative_returns(df: pd.DataFrame, component_names: list[str]) -> None:
    is_nip = df[PortfolioColumns.NIP.value] == 1
    for component_name in component_names:
        prefix = _component_prefix(component_name, temp=False)
        columns = [f"{prefix}long_cum_ror", f"{prefix}short_cum_ror"]
        df.loc[is_nip, columns] = np.nan
        df[columns] = df[columns].ffill().fillna(0.0)


def _compound_ror(df: pd.DataFrame, daily_ror: pd.Series, leg: str, use_resets=False) -> pd.Series:
    """Helper for geometric compounding, supporting both float and Decimal."""
    is_decimal_mode = daily_ror.dtype == "object"
    one = Decimal(1) if is_decimal_mode else 1.0
    hundred = Decimal(100) if is_decimal_mode else 100.0
    zero = Decimal(0) if is_decimal_mode else 0.0

    sign = df[PortfolioColumns.SIGN.value]
    if leg == "long":
        is_leg_day = sign == 1
        growth_factor = one + (daily_ror / hundred)
    else:
        is_leg_day = sign == -1
        growth_factor = one - (daily_ror / hundred)
    growth_factor = growth_factor.where(is_leg_day, one)

    prev_eff_start = df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value].shift(1)
    is_period_start = df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE.value] != prev_eff_start
    if not df.empty:
        is_period_start.iloc[0] = True

    block_starts = is_period_start
    if use_resets:
        prev_day_was_reset = df[PortfolioColumns.PERF_RESET.value].shift(1, fill_value=0) == 1
        block_starts |= prev_day_was_reset
    block_ids = block_starts.cumsum()

    if is_decimal_mode:

        def decimal_cumprod(series):
            result = series.copy()
            for i in range(1, len(series)):
                result.iloc[i] = result.iloc[i - 1] * result.iloc[i]
            return result

        cumulative_growth = growth_factor.groupby(block_ids, group_keys=False).apply(decimal_cumprod)
    else:
        cumulative_growth = growth_factor.groupby(block_ids).cumprod()

    cumulative_ror = (cumulative_growth - one) * hundred
    if leg == "short":
        cumulative_ror *= -one
    leg_ror = cumulative_ror.where(is_leg_day)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        filled_ror = leg_ror.ffill().fillna(zero)

    return filled_ror
