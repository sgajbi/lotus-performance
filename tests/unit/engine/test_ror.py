# tests/unit/engine/test_ror.py
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from core.envelope import HedgingRequestBlock
from engine.config import EngineConfig, FXRequestBlock
from engine.periods import get_effective_period_start_dates
from engine.ror import _compound_ror, calculate_daily_ror
from engine.schema import PortfolioColumns


@pytest.fixture
def sample_df():
    """Provides a sample DataFrame for RoR tests."""
    data = [
        {
            PortfolioColumns.PERF_DATE: date(2025, 1, 1),
            PortfolioColumns.BEGIN_MV: 1000,
            PortfolioColumns.BOD_CF: 0,
            PortfolioColumns.EOD_CF: 0,
            PortfolioColumns.MGMT_FEES: -10,
            PortfolioColumns.END_MV: 1090,
        },
        {
            PortfolioColumns.PERF_DATE: date(2025, 1, 2),
            PortfolioColumns.BEGIN_MV: 1090,
            PortfolioColumns.BOD_CF: 0,
            PortfolioColumns.EOD_CF: 0,
            PortfolioColumns.MGMT_FEES: -10,
            PortfolioColumns.END_MV: 1200,
        },
        {
            PortfolioColumns.PERF_DATE: date(2025, 1, 3),
            PortfolioColumns.BEGIN_MV: 0,
            PortfolioColumns.BOD_CF: 0,
            PortfolioColumns.EOD_CF: 0,
            PortfolioColumns.MGMT_FEES: 0,
            PortfolioColumns.END_MV: 10,
        },
        {
            PortfolioColumns.PERF_DATE: date(2025, 1, 4),
            PortfolioColumns.BEGIN_MV: 100,
            PortfolioColumns.BOD_CF: 0,
            PortfolioColumns.EOD_CF: 0,
            PortfolioColumns.MGMT_FEES: 0,
            PortfolioColumns.END_MV: 110,
        },
    ]
    df = pd.DataFrame(data)
    df[PortfolioColumns.PERF_DATE] = pd.to_datetime(df[PortfolioColumns.PERF_DATE])
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 31),
        metric_basis="NET",
        period_type="YTD",
        report_start_date=date(2025, 1, 4),
    )
    df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE] = get_effective_period_start_dates(
        df[PortfolioColumns.PERF_DATE], config
    )
    return df


def test_daily_ror_net_basis(sample_df):
    """Tests that NET RoR correctly includes management fees."""
    ror_df = calculate_daily_ror(sample_df, metric_basis="NET")
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(8.0)


def test_daily_ror_gross_basis(sample_df):
    """Tests that GROSS RoR correctly ignores management fees."""
    ror_df = calculate_daily_ror(sample_df, metric_basis="GROSS")
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[1] == pytest.approx(10.091743119)


def test_daily_ror_zero_denominator(sample_df):
    """Tests that RoR is 0 when the denominator is 0."""
    ror_df = calculate_daily_ror(sample_df, metric_basis="NET")
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[2] == 0.0


def test_daily_ror_before_effective_start(sample_df):
    """Tests that RoR is 0 for dates before the effective period start."""
    config = EngineConfig(
        performance_start_date=date(2025, 1, 5),
        report_end_date=date(2025, 1, 31),
        metric_basis="NET",
        period_type="YTD",
    )
    df = sample_df.copy()
    df[PortfolioColumns.EFFECTIVE_PERIOD_START_DATE] = get_effective_period_start_dates(
        df[PortfolioColumns.PERF_DATE], config
    )
    ror_df = calculate_daily_ror(df, metric_basis="NET")
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[3] == 0.0


def test_compound_ror_decimal_strict_multi_period():
    """Tests that the decimal-strict compounding works over multiple rows."""
    df = pd.DataFrame(
        {
            PortfolioColumns.SIGN: [1, 1],
            PortfolioColumns.DAILY_ROR: [Decimal("10.0"), Decimal("10.0")],
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01", "2025-01-01"]),
            PortfolioColumns.PERF_RESET: [0, 0],
        }
    )
    df[PortfolioColumns.DAILY_ROR] = df[PortfolioColumns.DAILY_ROR].astype("object")

    result = _compound_ror(df, df[PortfolioColumns.DAILY_ROR], "long", use_resets=False)
    assert isinstance(result.iloc[1], Decimal)
    assert result.iloc[1] == pytest.approx(Decimal("21.0"))


def test_daily_ror_fx_decomposition():
    """Tests the local, fx, and base return decomposition logic."""
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.BEGIN_MV: [100.0, 102.0],  # In EUR
            PortfolioColumns.BOD_CF: [0.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0],
            PortfolioColumns.END_MV: [102.0, 103.02],  # In EUR
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01", "2025-01-01"]),
        }
    )
    fx_rates_data = {
        "rates": [
            {"date": date(2024, 12, 31), "ccy": "EUR", "rate": 1.05},
            {"date": date(2025, 1, 1), "ccy": "EUR", "rate": 1.08},
            {"date": date(2025, 1, 2), "ccy": "EUR", "rate": 1.07},
        ]
    }
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        metric_basis="GROSS",
        period_type="YTD",
        currency_mode="BOTH",
        report_ccy="USD",
        fx=FXRequestBlock.model_validate(fx_rates_data),
    )

    ror_df = calculate_daily_ror(df, config.metric_basis, config)

    # Day 1: Local +2%, FX +2.86%
    assert ror_df["local_ror"].iloc[0] == pytest.approx(2.0)
    assert ror_df["fx_ror"].iloc[0] == pytest.approx(2.85714, abs=1e-5)
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(4.91428, abs=1e-5)

    # Day 2: Local +1%, FX -0.926%
    assert ror_df["local_ror"].iloc[1] == pytest.approx(1.0)
    assert ror_df["fx_ror"].iloc[1] == pytest.approx(-0.92592, abs=1e-5)
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[1] == pytest.approx(0.06481, abs=1e-5)


def test_daily_ror_fx_decomposition_with_hedging():
    """Tests that the hedge_ratio correctly dampens the calculated FX return."""
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.BEGIN_MV: [100.0, 102.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0],
            PortfolioColumns.END_MV: [102.0, 103.02],
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01", "2025-01-01"]),
        }
    )
    fx_rates_data = {
        "rates": [
            {"date": date(2024, 12, 31), "ccy": "EUR", "rate": 1.05},
            {"date": date(2025, 1, 1), "ccy": "EUR", "rate": 1.08},
            {"date": date(2025, 1, 2), "ccy": "EUR", "rate": 1.07},
        ]
    }
    hedging_data = {
        "mode": "RATIO",
        "series": [{"date": date(2025, 1, 1), "ccy": "EUR", "hedge_ratio": 0.50}],  # Hedge 50% on day 1
    }
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        metric_basis="GROSS",
        period_type="YTD",
        currency_mode="BOTH",
        report_ccy="USD",
        fx=FXRequestBlock.model_validate(fx_rates_data),
        hedging=HedgingRequestBlock.model_validate(hedging_data),
    )

    ror_df = calculate_daily_ror(df, config.metric_basis, config)

    # Day 1 was 50% hedged. Original fx_ror was ~2.85714%. Hedged should be half.
    assert ror_df["fx_ror"].iloc[0] == pytest.approx(2.85714 * 0.5, abs=1e-5)
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(
        ((1 + 0.02) * (1 + 0.0285714 * 0.5) - 1) * 100, abs=1e-5
    )

    # Day 2 was not hedged. fx_ror should be the original unhedged value.
    assert ror_df["fx_ror"].iloc[1] == pytest.approx(-0.92592, abs=1e-5)
