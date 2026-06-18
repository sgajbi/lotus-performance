# engine/rules.py
from decimal import Decimal
from typing import Tuple

import numpy as np
import pandas as pd

from engine.config import EngineConfig
from engine.schema import PortfolioColumns


def _get_decimal_sign(d: Decimal) -> Decimal:
    """Helper to get the sign of a Decimal object."""
    if d > 0:
        return Decimal(1)
    elif d < 0:
        return Decimal(-1)
    return Decimal(0)


def calculate_initial_sign(df: pd.DataFrame) -> pd.Series:
    """Calculates the raw start-of-day sign from begin market value plus BOD cash flow."""
    is_decimal_mode = df[PortfolioColumns.BEGIN_MV.value].dtype == "object"
    if is_decimal_mode:
        initial_sign = (df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value]).apply(
            _get_decimal_sign
        )
    else:
        initial_sign = np.sign(df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value])
    return initial_sign.astype(int)


def calculate_sign(df: pd.DataFrame) -> pd.Series:
    """Vectorized calculation of the 'sign' column, supporting both float and Decimal."""
    is_decimal_mode = df[PortfolioColumns.BEGIN_MV.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0

    initial_sign = calculate_initial_sign(df)

    prev_eod_cf = df[PortfolioColumns.EOD_CF.value].shift(1, fill_value=zero)
    prev_perf_reset = df[PortfolioColumns.PERF_RESET.value].shift(1, fill_value=0)
    is_flip_event = (df[PortfolioColumns.BOD_CF.value] != zero) | (prev_eod_cf != zero) | (prev_perf_reset == 1)

    if not df.empty:
        is_flip_event.iloc[0] = True

    flip_group = is_flip_event.cumsum()
    event_signs = initial_sign.where(is_flip_event)
    final_sign = event_signs.groupby(flip_group).ffill().fillna(zero)
    return final_sign.astype(int)


def calculate_nip_variants(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Returns both supported NIP rule variants for characterization and shadow diagnostics."""
    is_decimal_mode = df[PortfolioColumns.BEGIN_MV.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0

    cond_v2 = (df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value] == zero) & (
        df[PortfolioColumns.END_MV.value] + df[PortfolioColumns.EOD_CF.value] == zero
    )

    is_zero_value = (
        df[PortfolioColumns.BEGIN_MV.value]
        + df[PortfolioColumns.BOD_CF.value]
        + df[PortfolioColumns.END_MV.value]
        + df[PortfolioColumns.EOD_CF.value]
    ) == zero

    bod_cf_series = df[PortfolioColumns.BOD_CF.value]
    eod_cf_series = df[PortfolioColumns.EOD_CF.value]

    if is_decimal_mode:
        sign_of_bod_cf = bod_cf_series.apply(_get_decimal_sign)
    else:
        sign_of_bod_cf = np.sign(bod_cf_series)

    is_offsetting_cf = eod_cf_series == -sign_of_bod_cf
    cond_v1 = is_zero_value & is_offsetting_cf
    return cond_v1.astype(int), cond_v2.astype(int)


def calculate_nip(df: pd.DataFrame, config: EngineConfig) -> pd.Series:
    """Vectorized calculation of the 'No Investment Period' (NIP) flag."""
    nip_v1, nip_v2 = calculate_nip_variants(df)
    return nip_v2 if config.feature_flags.use_nip_v2_rule else nip_v1


def calculate_initial_resets(
    df: pd.DataFrame, report_end_date: pd.Timestamp, temp_long_col: str, temp_short_col: str
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Calculates threshold-driven reset reasons NCTRL_1 through NCTRL_3.

    The current engine still uses the legacy reset-permission gate that includes:
    current-day BOD cash flow, next-day BOD cash flow, current-day EOD cash flow,
    month-end, and report-end boundaries. Slice 1 keeps that gate intact while
    promoting the individual reset reasons into a canonical reset model.
    """
    is_decimal_mode = df[PortfolioColumns.BOD_CF.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0

    eom_mask = df[PortfolioColumns.PERF_DATE.value].dt.is_month_end
    next_day_bod_cf = df[PortfolioColumns.BOD_CF.value].shift(-1).fillna(zero)

    future_date = pd.Timestamp.max.normalize()
    next_date_is_after_end = df[PortfolioColumns.PERF_DATE.value].shift(-1, fill_value=future_date) > report_end_date
    if not df.empty:
        next_date_is_after_end.iloc[-1] = True

    cond_common = (
        (df[PortfolioColumns.BOD_CF.value] != zero)
        | (next_day_bod_cf != zero)
        | (df[PortfolioColumns.EOD_CF.value] != zero)
        | eom_mask
        | next_date_is_after_end
    )

    cond_nctrl1 = df[temp_long_col] < -100
    cond_nctrl2 = df[temp_short_col] > 100
    cond_nctrl3 = (df[temp_short_col] < -100) & (df[temp_long_col] != 0)

    nctrl1 = (cond_nctrl1 & ~cond_nctrl1.shift(1, fill_value=False)) & cond_common
    nctrl2 = (cond_nctrl2 & ~cond_nctrl2.shift(1, fill_value=False)) & cond_common
    nctrl3 = (cond_nctrl3 & ~cond_nctrl3.shift(1, fill_value=False)) & cond_common

    resets = nctrl1 | nctrl2 | nctrl3
    return resets, nctrl1, nctrl2, nctrl3


def calculate_nctrl4_reset(df: pd.DataFrame, long_cum_col: str, short_cum_col: str) -> pd.Series:
    """Calculates the reset reason historically labeled as NCTRL_4.

    Domain meaning:
    this branch tries to detect a recapitalization-style boundary after the prior path has
    already broken. It only becomes reachable when:

    - the previous cumulative state already sat on a collapse boundary, and
    - a cash-flow transition suggests the next observation is starting a new economic episode

    The rule is intentionally kept explicit because RFC-043 is still characterizing whether
    this legacy branch captures a real portfolio state or merely preserves historical behavior.
    """
    is_decimal_mode = df[PortfolioColumns.BOD_CF.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0
    hundred = Decimal(-100) if is_decimal_mode else -100.0

    prev_long_ror = df[long_cum_col].shift(1, fill_value=zero)
    prev_short_ror = df[short_cum_col].shift(1, fill_value=zero)
    prev_eod_cf = df[PortfolioColumns.EOD_CF.value].shift(1, fill_value=zero)

    nctrl4 = ((prev_long_ror <= hundred) | (prev_short_ror >= -hundred)) & (
        (df[PortfolioColumns.BOD_CF.value] != zero) | (prev_eod_cf != zero)
    )

    return nctrl4


def calculate_account_reset_reason(df: pd.DataFrame) -> pd.Series:
    """Normalizes caller- or upstream-supplied account reset flags into an engine reset reason."""
    if PortfolioColumns.ACCOUNT_PERFORMANCE_RESET.value not in df.columns:
        return pd.Series(0, index=df.index, dtype=int)
    return (df[PortfolioColumns.ACCOUNT_PERFORMANCE_RESET.value] != 0).astype(int)


def _sod_reset_flags_from_next_open(
    next_day_bod_cf: np.ndarray,
    canonical_reset: np.ndarray,
    zero: object,
) -> np.ndarray:
    """Resolve SOD reset flags by walking backward through next-day opening reset state."""
    sod_reset = np.zeros(len(canonical_reset), dtype=bool)

    for position in range(len(canonical_reset) - 2, -1, -1):
        should_reset_from_next_open = (next_day_bod_cf[position] != zero) and canonical_reset[position + 1]
        sod_reset[position] = should_reset_from_next_open
        canonical_reset[position] = canonical_reset[position] or should_reset_from_next_open

    return sod_reset


def calculate_sod_reset_reason(df: pd.DataFrame, base_reset_mask: pd.Series) -> pd.Series:
    """Calculates the start-of-day reset reason from the next day's canonical reset state.

    Domain meaning:
    a day gets an SOD reset reason when the next day starts with a non-zero BOD cash flow
    and that next day is itself a reset day under the canonical reset reasons already known.

    The computation is performed backward so the current day's SOD reset can see the final
    reset state of the next day.
    """
    if df.empty:
        return pd.Series(dtype=int)

    is_decimal_mode = df[PortfolioColumns.BOD_CF.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0

    next_day_bod_cf = df[PortfolioColumns.BOD_CF.value].shift(-1, fill_value=zero).to_numpy(copy=False)
    canonical_reset = base_reset_mask.astype(bool).to_numpy(copy=True)
    sod_reset = _sod_reset_flags_from_next_open(next_day_bod_cf, canonical_reset, zero)

    return pd.Series(sod_reset.astype(int), index=df.index)
