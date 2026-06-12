# engine/policies.py
import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from pydantic import BaseModel

from engine.diagnostics import EngineDiagnostics, OutlierSample
from engine.schema import PortfolioColumns

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyInputs:
    overrides: Dict
    ignore_days: list
    ignored_dates: set[date]


def _extract_policy_inputs(data_policy_model: BaseModel | None) -> PolicyInputs:
    if not data_policy_model:
        return PolicyInputs(overrides={}, ignore_days=[], ignored_dates=set())

    policy_payload = data_policy_model.model_dump(exclude_unset=True)
    ignore_days = policy_payload.get("ignore_days") or []
    ignored_dates = {ignored_date for item in ignore_days for ignored_date in item.get("dates", [])}
    return PolicyInputs(
        overrides=policy_payload.get("overrides") or {},
        ignore_days=ignore_days,
        ignored_dates=ignored_dates,
    )


def _apply_overrides(df: pd.DataFrame, overrides: Dict, diagnostics: EngineDiagnostics) -> None:
    """Applies user-provided market value and cash flow overrides in-memory."""
    if not overrides:
        return

    mv_overrides = overrides.get("market_values", [])
    cf_overrides = overrides.get("cash_flows", [])

    for override in mv_overrides:
        diagnostics.policy.overrides.applied_mv_count += _apply_override_values(
            df,
            override,
            keys=("begin_mv", "end_mv"),
            mask=_override_mask(df, override),
        )

    for override in cf_overrides:
        diagnostics.policy.overrides.applied_cf_count += _apply_override_values(
            df,
            override,
            keys=("bod_cf", "eod_cf"),
            mask=_override_mask(df, override),
        )

    if diagnostics.policy.overrides.applied_mv_count > 0 or diagnostics.policy.overrides.applied_cf_count > 0:
        diagnostics.notes.append("Applied overrides from the data_policy request.")


def _override_mask(df: pd.DataFrame, override: Dict) -> pd.Series:
    mask = df[PortfolioColumns.PERF_DATE.value] == pd.to_datetime(override["perf_date"])
    if "position_id" in override and "position_id" in df.columns:
        mask &= df["position_id"] == override["position_id"]
    return mask


def _apply_override_values(
    df: pd.DataFrame,
    override: Dict,
    *,
    keys: tuple[str, ...],
    mask: pd.Series,
) -> int:
    if df.loc[mask].empty:
        return 0
    applied_count = 0
    for key in keys:
        if key in override:
            df.loc[mask, key] = override[key]
            applied_count += 1
    return applied_count


def _apply_ignore_days(df: pd.DataFrame, ignore_days: list, diagnostics: EngineDiagnostics) -> None:
    """Applies policy to ignore specified days by carrying forward previous day's state."""
    if not ignore_days:
        return

    # Ensure DataFrame is sorted by date for correct forward-fill logic
    df.sort_values(by=PortfolioColumns.PERF_DATE.value, inplace=True)
    df.set_index(PortfolioColumns.PERF_DATE.value, inplace=True)

    for item in ignore_days:
        dates_to_ignore = pd.to_datetime(item["dates"])
        for ignored_timestamp in dates_to_ignore:
            if ignored_timestamp in df.index:
                loc = df.index.get_loc(ignored_timestamp)
                if loc > 0:
                    prev_day = df.iloc[loc - 1]
                    df.loc[ignored_timestamp, PortfolioColumns.BEGIN_MV.value] = prev_day[PortfolioColumns.END_MV.value]
                    df.loc[ignored_timestamp, PortfolioColumns.END_MV.value] = prev_day[PortfolioColumns.END_MV.value]
                    df.loc[ignored_timestamp, PortfolioColumns.BOD_CF.value] = 0.0
                    df.loc[ignored_timestamp, PortfolioColumns.EOD_CF.value] = 0.0
                    df.loc[ignored_timestamp, PortfolioColumns.MGMT_FEES.value] = 0.0
                    diagnostics.policy.ignored_days_count += 1

    if diagnostics.policy.ignored_days_count > 0:
        diagnostics.notes.append(f"Ignored {diagnostics.policy.ignored_days_count} day(s) as specified in data_policy.")
    df.reset_index(inplace=True)


def _flag_outliers(
    df: pd.DataFrame,
    data_policy_model: BaseModel | None,
    diagnostics: EngineDiagnostics,
    *,
    ignored_dates: set[date] | None = None,
) -> None:
    """Detects and flags outliers, excluding ignored days from statistical analysis."""
    if not data_policy_model or not data_policy_model.outliers or not data_policy_model.outliers.enabled:
        return

    outlier_policy = data_policy_model.outliers.model_dump()
    if outlier_policy.get("action") != "FLAG":
        return

    window = outlier_policy.get("params", {}).get("window", 63)
    mad_k = outlier_policy.get("params", {}).get("mad_k", 5.0)

    if PortfolioColumns.DAILY_ROR.value not in df.columns:
        return

    outliers, upper_bound, lower_bound = _outlier_mask_and_bounds(
        df=df,
        ignored_dates=ignored_dates,
        window=window,
        mad_k=mad_k,
    )

    diagnostics.policy.outliers.flagged_rows = int(outliers.sum())
    _record_outlier_samples(
        df=df,
        outliers=outliers,
        upper_bound=upper_bound,
        lower_bound=lower_bound,
        diagnostics=diagnostics,
    )


def _record_outlier_samples(
    *,
    df: pd.DataFrame,
    outliers: pd.Series,
    upper_bound: pd.Series,
    lower_bound: pd.Series,
    diagnostics: EngineDiagnostics,
) -> None:
    if int(outliers.sum()) == 0:
        return

    outlier_indices = df.index[outliers]
    for index in outlier_indices:
        sample = df.loc[index]
        raw_return = sample[PortfolioColumns.DAILY_ROR.value]
        diagnostics.samples.outliers.append(
            OutlierSample(
                date=sample[PortfolioColumns.PERF_DATE.value].strftime("%Y-%m-%d"),
                raw_return=raw_return,
                threshold=upper_bound[index] if raw_return > 0 else lower_bound[index],
            )
        )


def _outlier_mask_and_bounds(
    *,
    df: pd.DataFrame,
    ignored_dates: set[date] | None,
    window: int,
    mad_k: float,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ror_series = df[PortfolioColumns.DAILY_ROR.value]
    ror_for_stats = ror_series.copy()
    valid_mask = None
    if ignored_dates:
        valid_mask = ~df[PortfolioColumns.PERF_DATE.value].dt.date.isin(ignored_dates)
        ror_for_stats = ror_for_stats.where(valid_mask)  # Use .where to keep index alignment

    median = ror_for_stats.rolling(window=window, min_periods=1).median().ffill()
    mad = (ror_for_stats - median).abs().rolling(window=window, min_periods=1).median().ffill()

    mad.replace(0, np.nan, inplace=True)
    mad.ffill(inplace=True)
    mad.fillna(1e-9, inplace=True)

    upper_bound = median + mad_k * mad
    lower_bound = median - mad_k * mad

    outliers = (ror_series > upper_bound) | (ror_series < lower_bound)
    if valid_mask is not None:
        outliers &= valid_mask
    return outliers, upper_bound, lower_bound


def apply_robustness_policies(
    df: pd.DataFrame, data_policy_model: BaseModel | None
) -> Tuple[pd.DataFrame, EngineDiagnostics]:
    """Orchestrator to apply pre-calculation robustness policies."""
    diagnostics = EngineDiagnostics()

    if not data_policy_model:
        return df, diagnostics

    policy_inputs = _extract_policy_inputs(data_policy_model)
    if not policy_inputs.overrides and not policy_inputs.ignore_days:
        return df, diagnostics

    # `run_calculations(...)` owns the caller-protection boundary, so this layer only
    # needs one mutable working frame regardless of how many policy transforms apply.
    working_df = df.copy()
    _apply_overrides(working_df, policy_inputs.overrides, diagnostics)
    _apply_ignore_days(working_df, policy_inputs.ignore_days, diagnostics)

    return working_df, diagnostics
