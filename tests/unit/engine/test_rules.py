# tests/unit/engine/test_rules.py

from decimal import Decimal

import pandas as pd
import pytest

from engine.config import EngineConfig, FeatureFlags, PeriodType
from engine.rules import (
    _get_decimal_sign,
    calculate_initial_resets,
    calculate_nctrl4_reset,
    calculate_nip,
    calculate_sign,
)
from engine.schema import PortfolioColumns


@pytest.fixture
def sign_test_df() -> pd.DataFrame:
    """Provides a sample DataFrame for testing sign calculation logic."""
    data = {
        PortfolioColumns.BEGIN_MV: [1000, 500, -200, -150, 800],
        PortfolioColumns.BOD_CF: [0, 0, 1000, 0, 0],
        PortfolioColumns.EOD_CF: [0, -800, 0, 0, 0],
        PortfolioColumns.PERF_RESET: [0, 0, 0, 1, 0],
    }
    df = pd.DataFrame(data)
    return df


def test_calculate_sign_initial_day(sign_test_df):
    """Tests that the sign is correctly determined by BMV + BOD_CF on the first day."""
    result = calculate_sign(sign_test_df)
    assert result.iloc[0] == 1  # 1000 + 0 is positive


def test_calculate_sign_persists_on_flip_without_cashflow(sign_test_df):
    """
    Tests that the sign carries over from the previous day if it flips without
    a cashflow or reset event to justify it.
    """
    df = sign_test_df.copy()
    df.at[1, PortfolioColumns.BEGIN_MV] = -600
    df.at[1, PortfolioColumns.BOD_CF] = 0
    df.at[1, PortfolioColumns.EOD_CF] = 0

    result = calculate_sign(df)
    assert result.iloc[1] == 1


def test_calculate_sign_flips_with_bod_cashflow(sign_test_df):
    """Tests that the sign correctly flips when there is a BOD cashflow."""
    result = calculate_sign(sign_test_df)
    assert result.iloc[2] == 1


def test_calculate_sign_flips_with_prev_eod_cashflow(sign_test_df):
    """Tests that the sign correctly flips when there was an EOD cashflow on the prior day."""
    df = sign_test_df.copy()
    df.at[2, PortfolioColumns.BEGIN_MV] = -900
    df.at[2, PortfolioColumns.BOD_CF] = 0
    df.at[1, PortfolioColumns.EOD_CF] = -1500

    result = calculate_sign(df)
    assert result.iloc[2] == -1


def test_calculate_sign_flips_after_perf_reset(sign_test_df):
    """Tests that the sign is allowed to flip on the day after a performance reset."""
    df = sign_test_df.copy()
    df.at[4, PortfolioColumns.BEGIN_MV] = -100
    df.at[3, PortfolioColumns.PERF_RESET] = 1

    result = calculate_sign(df)
    assert result.iloc[4] == -1


# --- Tests for NIP Calculation ---


@pytest.fixture
def nip_test_df() -> pd.DataFrame:
    """Provides a sample DataFrame for testing NIP calculation logic."""
    data = {
        PortfolioColumns.BEGIN_MV: [0, 0, 1000, 0],
        PortfolioColumns.BOD_CF: [0, 20, 0, 20],
        PortfolioColumns.EOD_CF: [0, -20, 0, -20],
        PortfolioColumns.END_MV: [0, 0, 1000, 0],
    }
    return pd.DataFrame(data)


def test_calculate_nip_v1_triggered_for_zero_value_day(nip_test_df):
    """Tests that NIP (v1) is flagged for a day where all values are zero."""
    config = EngineConfig(
        "2025-01-01", "2025-01-01", "NET", PeriodType.YTD, feature_flags=FeatureFlags(use_nip_v2_rule=False)
    )
    result = calculate_nip(nip_test_df, config)
    assert result.iloc[0] == 1


def test_calculate_nip_v1_not_triggered_for_offsetting_cashflow(nip_test_df):
    """Tests NIP (v1) is NOT flagged for a zero-net-change day with offsetting flows."""
    config = EngineConfig(
        "2025-01-01", "2025-01-01", "NET", PeriodType.YTD, feature_flags=FeatureFlags(use_nip_v2_rule=False)
    )
    result = calculate_nip(nip_test_df, config)
    assert result.iloc[1] == 0


def test_calculate_nip_not_triggered_for_non_zero_day(nip_test_df):
    """Tests that NIP is not flagged for a normal day with non-zero values."""
    config = EngineConfig(
        "2025-01-01", "2025-01-01", "NET", PeriodType.YTD, feature_flags=FeatureFlags(use_nip_v2_rule=False)
    )
    result = calculate_nip(nip_test_df, config)
    assert result.iloc[2] == 0


def test_calculate_nip_v2_triggered_with_feature_flag(nip_test_df):
    """Tests that the simpler NIP v2 rule is used when the feature flag is set."""
    config = EngineConfig(
        "2025-01-01", "2025-01-01", "NET", PeriodType.YTD, feature_flags=FeatureFlags(use_nip_v2_rule=True)
    )
    result = calculate_nip(nip_test_df, config)
    # V2 Rule: (BMV+BOD==0) AND (EMV+EOD==0)
    # Day 0: (0+0==0) & (0+0==0) -> TRUE
    assert result.iloc[0] == 1
    # Day 1: (0+20!=0) -> FALSE
    assert result.iloc[1] == 0
    # Day 2: (1000+0!=0) -> FALSE
    assert result.iloc[2] == 0
    # Day 3: (0+20!=0) -> FALSE
    assert result.iloc[3] == 0


# --- Tests for Reset Calculation ---


@pytest.fixture
def reset_test_df() -> pd.DataFrame:
    """Provides a sample DataFrame for testing reset (NCTRL) calculation logic."""
    data = {
        PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]),
        PortfolioColumns.TEMP_LONG_CUM_ROR: [-50, -105, 10, 15],
        PortfolioColumns.TEMP_SHORT_CUM_ROR: [50, 10, 105, 20],
        PortfolioColumns.LONG_CUM_ROR: [-50, 0, 10, 15],
        PortfolioColumns.SHORT_CUM_ROR: [50, 10, 105, 20],
        PortfolioColumns.BOD_CF: [0, 0, 1000, 0],
        PortfolioColumns.EOD_CF: [0, 0, 0, 0],
        PortfolioColumns.SIGN: [1, 1, 1, 1],
        PortfolioColumns.NCTRL_1: [0, 0, 0, 0],
        PortfolioColumns.NCTRL_2: [0, 0, 0, 0],
        PortfolioColumns.NCTRL_3: [0, 0, 0, 0],
        PortfolioColumns.NCTRL_4: [0, 0, 0, 0],
    }
    return pd.DataFrame(data)


def test_calculate_initial_resets_nctrl1_triggered(reset_test_df):
    """Tests that NCTRL1 is triggered when Temp Long RoR breaches -100%."""
    df = reset_test_df
    resets, nctrl1, _, _ = calculate_initial_resets(
        df,
        report_end_date=pd.to_datetime("2025-01-31"),
        temp_long_col=PortfolioColumns.TEMP_LONG_CUM_ROR.value,
        temp_short_col=PortfolioColumns.TEMP_SHORT_CUM_ROR.value,
    )
    assert nctrl1.iloc[1]
    assert resets.iloc[1]


def test_calculate_initial_resets_nctrl2_triggered(reset_test_df):
    """Tests that NCTRL2 is triggered when Temp Short RoR breaches 100%."""
    df = reset_test_df
    resets, _, nctrl2, _ = calculate_initial_resets(
        df,
        report_end_date=pd.to_datetime("2025-01-31"),
        temp_long_col=PortfolioColumns.TEMP_LONG_CUM_ROR.value,
        temp_short_col=PortfolioColumns.TEMP_SHORT_CUM_ROR.value,
    )
    assert nctrl2.iloc[2]
    assert resets.iloc[2]


def test_calculate_initial_resets_not_triggered_without_common_condition(reset_test_df):
    """Tests that NCTRL flags are not set if the RoR breach occurs but no common condition is met."""
    df = reset_test_df.copy()
    df.at[2, PortfolioColumns.BOD_CF] = 0
    df[PortfolioColumns.PERF_DATE] = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])
    resets, _, nctrl2, _ = calculate_initial_resets(
        df,
        report_end_date=pd.to_datetime("2025-02-28"),
        temp_long_col=PortfolioColumns.TEMP_LONG_CUM_ROR.value,
        temp_short_col=PortfolioColumns.TEMP_SHORT_CUM_ROR.value,
    )
    assert not nctrl2.iloc[2]
    assert not resets.iloc[2]


def test_calculate_nctrl4_reset_triggered(reset_test_df):
    """Tests NCTRL4 is triggered when the previous day had a major loss and there's a new cashflow."""
    df = reset_test_df
    df.at[1, PortfolioColumns.LONG_CUM_ROR] = -105

    resets = calculate_nctrl4_reset(
        df,
        long_cum_col=PortfolioColumns.LONG_CUM_ROR.value,
        short_cum_col=PortfolioColumns.SHORT_CUM_ROR.value,
    )
    assert resets.iloc[2]


def test_get_decimal_sign_negative_value():
    assert _get_decimal_sign(Decimal("-1")) == Decimal(-1)
