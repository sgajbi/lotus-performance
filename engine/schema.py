# engine/schema.py
from enum import Enum


class PortfolioColumns(str, Enum):
    """
    Defines the internal, standardized snake_case column names for the performance engine.
    This serves as the single source of truth for all data contracts within the engine.
    """

    # --- Input Fields ---
    DAY = "day"
    PERF_DATE = "perf_date"
    BEGIN_MV = "begin_mv"
    BOD_CF = "bod_cf"
    EOD_CF = "eod_cf"
    MGMT_FEES = "mgmt_fees"
    END_MV = "end_mv"

    # --- Core Calculated Fields ---
    SIGN = "sign"
    DAILY_ROR = "daily_ror"
    NIP = "nip"
    PERF_RESET = "perf_reset"
    LONG_SHORT = "long_short"

    # --- Control Flags ---
    ACCOUNT_RESET = "account_reset"
    SOD_RESET = "sod_reset"
    NCTRL_1 = "nctrl_1"
    NCTRL_2 = "nctrl_2"
    NCTRL_3 = "nctrl_3"
    NCTRL_4 = "nctrl_4"

    # --- Cumulative Return Fields ---
    TEMP_LONG_CUM_ROR = "temp_long_cum_ror"
    TEMP_SHORT_CUM_ROR = "temp_short_cum_ror"
    LONG_CUM_ROR = "long_cum_ror"
    SHORT_CUM_ROR = "short_cum_ror"
    FINAL_CUM_ROR = "final_cum_ror"

    # --- Helper/Temporary Fields ---
    EFFECTIVE_PERIOD_START_DATE = "effective_period_start_date"
    ACCOUNT_PERFORMANCE_RESET = "account_performance_reset"
