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


def calculate_sign(df: pd.DataFrame) -> pd.Series:
    """Vectorized calculation of the 'sign' column, supporting both float and Decimal."""
    is_decimal_mode = df[PortfolioColumns.BEGIN_MV.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0

    if is_decimal_mode:
        initial_sign = (df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value]).apply(
            _get_decimal_sign
        )
    else:
        initial_sign = np.sign(df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value])

    prev_eod_cf = df[PortfolioColumns.EOD_CF.value].shift(1, fill_value=zero)
    prev_perf_reset = df[PortfolioColumns.PERF_RESET.value].shift(1, fill_value=0)
    is_flip_event = (df[PortfolioColumns.BOD_CF.value] != zero) | (prev_eod_cf != zero) | (prev_perf_reset == 1)

    if not df.empty:
        is_flip_event.iloc[0] = True

    flip_group = is_flip_event.cumsum()
    event_signs = initial_sign.where(is_flip_event)
    final_sign = event_signs.groupby(flip_group).ffill().fillna(zero)
    return final_sign.astype(int)


def calculate_nip(df: pd.DataFrame, config: EngineConfig) -> pd.Series:
    """Vectorized calculation of the 'No Investment Period' (NIP) flag."""
    is_decimal_mode = df[PortfolioColumns.BEGIN_MV.value].dtype == "object"
    zero = Decimal(0) if is_decimal_mode else 0.0

    if config.feature_flags.use_nip_v2_rule:
        cond = (df[PortfolioColumns.BEGIN_MV.value] + df[PortfolioColumns.BOD_CF.value] == zero) & (
            df[PortfolioColumns.END_MV.value] + df[PortfolioColumns.EOD_CF.value] == zero
        )
        return cond.astype(int)

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
    return (is_zero_value & is_offsetting_cf).astype(int)


def calculate_initial_resets(
    df: pd.DataFrame, report_end_date: pd.Timestamp, temp_long_col: str, temp_short_col: str
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Calculates resets based on NCTRL 1, 2, and 3. This is a pure function."""
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
    """Calculates resets based on NCTRL 4. This is a pure function."""
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
