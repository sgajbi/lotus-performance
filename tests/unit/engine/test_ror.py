# tests/unit/engine/test_ror.py
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from core.envelope import HedgingRequestBlock
from engine.config import EngineConfig, FXRequestBlock
from engine.periods import get_effective_period_start_dates
from engine.ror import (
    _apply_hedging_to_fx_return,
    _apply_local_daily_return_division,
    _calculate_fx_daily_return,
    _compound_ror,
    _compounding_block_ids,
    _cumulative_component_names,
    _hedge_ratios_for_dates,
    _leg_growth_factor,
    _ratio_hedge_series,
    _zero_component_cumulative_returns,
    calculate_cumulative_ror,
    calculate_daily_ror,
)
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


def test_daily_ror_decimal_net_basis_preserves_decimal_result():
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01"]),
            PortfolioColumns.BEGIN_MV: [Decimal("1000")],
            PortfolioColumns.BOD_CF: [Decimal("0")],
            PortfolioColumns.EOD_CF: [Decimal("0")],
            PortfolioColumns.MGMT_FEES: [Decimal("-10")],
            PortfolioColumns.END_MV: [Decimal("1090")],
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01"]),
        }
    )
    for column in [
        PortfolioColumns.BEGIN_MV,
        PortfolioColumns.BOD_CF,
        PortfolioColumns.EOD_CF,
        PortfolioColumns.MGMT_FEES,
        PortfolioColumns.END_MV,
    ]:
        df[column] = df[column].astype("object")

    ror_df = calculate_daily_ror(df, metric_basis="NET")

    daily_ror = ror_df[PortfolioColumns.DAILY_ROR.value].iloc[0]
    assert isinstance(daily_ror, Decimal)
    assert daily_ror == Decimal("8.00")


def test_daily_ror_decimal_gross_basis_skips_management_fees_and_unsafe_division():
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.BEGIN_MV: [Decimal("1000"), Decimal("0")],
            PortfolioColumns.BOD_CF: [Decimal("0"), Decimal("0")],
            PortfolioColumns.EOD_CF: [Decimal("0"), Decimal("0")],
            PortfolioColumns.MGMT_FEES: [Decimal("-10"), Decimal("-5")],
            PortfolioColumns.END_MV: [Decimal("1090"), Decimal("10")],
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01", "2025-01-03"]),
        }
    )
    for column in [
        PortfolioColumns.BEGIN_MV,
        PortfolioColumns.BOD_CF,
        PortfolioColumns.EOD_CF,
        PortfolioColumns.MGMT_FEES,
        PortfolioColumns.END_MV,
    ]:
        df[column] = df[column].astype("object")

    ror_df = calculate_daily_ror(df, metric_basis="GROSS")

    assert ror_df[PortfolioColumns.DAILY_ROR.value].tolist() == [Decimal("9.00"), Decimal("0")]


def test_apply_local_daily_return_division_decimal_no_safe_rows_preserves_zero_result():
    numerator = pd.Series([Decimal("10")], dtype=object)
    denominator = pd.Series([Decimal("0")], dtype=object)
    local_ror = pd.Series([Decimal("0")], dtype=object)

    _apply_local_daily_return_division(
        numerator,
        denominator,
        local_ror,
        pd.Series([False]),
        is_decimal_mode=True,
    )

    assert local_ror.tolist() == [Decimal("0")]


def test_daily_ror_currency_decomposition_requires_config_when_guard_is_forced(monkeypatch, sample_df):
    monkeypatch.setattr("engine.ror._should_decompose_currency", lambda config: True)

    with pytest.raises(ValueError, match="Currency decomposition requires engine configuration"):
        calculate_daily_ror(sample_df, metric_basis="GROSS", config=None)


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


def test_compound_ror_short_leg_compounds_and_inverts_float_returns():
    df = pd.DataFrame(
        {
            PortfolioColumns.SIGN: [-1, -1],
            PortfolioColumns.DAILY_ROR: [5.0, 5.0],
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01", "2025-01-01"]),
            PortfolioColumns.PERF_RESET: [0, 0],
        }
    )

    result = _compound_ror(df, df[PortfolioColumns.DAILY_ROR], "short", use_resets=False)

    assert result.tolist() == pytest.approx([5.0, 9.75])


def test_leg_growth_factor_projects_short_leg_days_only():
    df = pd.DataFrame({PortfolioColumns.SIGN: [1, -1]})
    daily_ror = pd.Series([10.0, 5.0])

    is_leg_day, growth_factor = _leg_growth_factor(
        df=df,
        daily_ror=daily_ror,
        leg="short",
        one=1.0,
        hundred=100.0,
    )

    assert is_leg_day.tolist() == [False, True]
    assert growth_factor.tolist() == [1.0, 0.95]


def test_compounding_block_ids_start_after_reset_and_period_change():
    df = pd.DataFrame(
        {
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-01", "2025-01-01", "2025-02-01"]
            ),
            PortfolioColumns.PERF_RESET: [0, 1, 0, 0],
        }
    )

    block_ids = _compounding_block_ids(df, use_resets=True)

    assert block_ids.tolist() == [1, 1, 2, 3]


def test_compounding_block_ids_handles_empty_series():
    df = pd.DataFrame(
        {
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime([]),
            PortfolioColumns.PERF_RESET: pd.Series([], dtype=int),
        }
    )

    block_ids = _compounding_block_ids(df, use_resets=True)

    assert block_ids.empty


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


def test_ratio_hedge_series_projects_configured_ratio_series():
    hedging = HedgingRequestBlock.model_validate(
        {"mode": "RATIO", "series": [{"date": date(2025, 1, 1), "ccy": "EUR", "hedge_ratio": 0.50}]}
    )
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="GROSS",
        period_type="YTD",
        hedging=hedging,
    )

    hedge_series = _ratio_hedge_series(config)

    assert hedge_series is not None
    assert len(hedge_series) == 1
    assert hedge_series[0].hedge_ratio == 0.50


def test_hedge_ratios_for_dates_maps_missing_dates_to_zero():
    hedging = HedgingRequestBlock.model_validate(
        {"mode": "RATIO", "series": [{"date": date(2025, 1, 1), "ccy": "EUR", "hedge_ratio": 0.50}]}
    )
    perf_dates = pd.Series(pd.to_datetime(["2025-01-01", "2025-01-02"]))

    hedge_ratios = _hedge_ratios_for_dates(perf_dates, list(hedging.series))

    assert hedge_ratios.tolist() == [0.50, 0.0]


def test_hedge_ratios_for_dates_empty_series_defaults_to_zero():
    perf_dates = pd.Series(pd.to_datetime(["2025-01-01", "2025-01-02"]))

    hedge_ratios = _hedge_ratios_for_dates(perf_dates, [])

    assert hedge_ratios.tolist() == [0.0, 0.0]


def test_apply_hedging_to_fx_return_returns_original_series_without_ratio_hedge():
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="GROSS",
        period_type="YTD",
    )
    df = pd.DataFrame({PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01"])})
    fx_ror = pd.Series([0.02])

    result = _apply_hedging_to_fx_return(df, config, fx_ror)

    assert result is fx_ror


def test_calculate_fx_daily_return_requires_fx_configuration():
    df = pd.DataFrame({PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01"])})
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="GROSS",
        period_type="YTD",
        currency_mode="BOTH",
        report_ccy="USD",
    )

    with pytest.raises(ValueError, match="requires FX configuration"):
        _calculate_fx_daily_return(df, config)


def test_calculate_fx_daily_return_accepts_date_rate_series_without_currency_dimension():
    class _Rate:
        def __init__(self, rate_date: date, rate: float) -> None:
            self.rate_date = rate_date
            self.rate = rate

        def model_dump(self):
            return {"date": self.rate_date, "rate": self.rate}

    class _Fx:
        rates = [_Rate(date(2024, 12, 31), 1.0), _Rate(date(2025, 1, 1), 1.1)]

    df = pd.DataFrame({PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01"])})
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="GROSS",
        period_type="YTD",
        currency_mode="BOTH",
        report_ccy="USD",
        fx=_Fx(),  # type: ignore[arg-type]
    )

    fx_ror = _calculate_fx_daily_return(df, config)

    assert fx_ror.tolist() == pytest.approx([0.1])


def test_cumulative_component_names_defaults_to_daily_return_only():
    df = pd.DataFrame({PortfolioColumns.DAILY_ROR: [1.0]})

    assert _cumulative_component_names(df) == [PortfolioColumns.DAILY_ROR.value]


def test_daily_ror_fx_decomposition_keeps_last_duplicate_fx_rate():
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01"]),
            PortfolioColumns.BEGIN_MV: [100.0],
            PortfolioColumns.BOD_CF: [0.0],
            PortfolioColumns.EOD_CF: [0.0],
            PortfolioColumns.MGMT_FEES: [0.0],
            PortfolioColumns.END_MV: [100.0],
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01"]),
        }
    )
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        metric_basis="GROSS",
        period_type="YTD",
        currency_mode="BOTH",
        report_ccy="USD",
        fx=FXRequestBlock.model_validate(
            {
                "rates": [
                    {"date": date(2024, 12, 31), "ccy": "EUR", "rate": 1.0},
                    {"date": date(2025, 1, 1), "ccy": "EUR", "rate": 1.1},
                    {"date": date(2025, 1, 1), "ccy": "EUR", "rate": 1.2},
                ]
            }
        ),
    )

    ror_df = calculate_daily_ror(df, config.metric_basis, config)

    assert ror_df["local_ror"].iloc[0] == 0.0
    assert ror_df["fx_ror"].iloc[0] == pytest.approx(20.0)
    assert ror_df[PortfolioColumns.DAILY_ROR.value].iloc[0] == pytest.approx(20.0)


def test_calculate_cumulative_ror_projects_local_fx_components_and_nip_carry_forward():
    df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            PortfolioColumns.EFFECTIVE_PERIOD_START_DATE: pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-01"]),
            PortfolioColumns.DAILY_ROR: [10.0, 5.0, 2.0],
            "local_ror": [8.0, 4.0, 1.0],
            "fx_ror": [1.0, 0.5, 0.25],
            PortfolioColumns.SIGN: [1, -1, 1],
            PortfolioColumns.BOD_CF: [0.0, 0.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0, 0.0],
            PortfolioColumns.NIP: [0, 0, 1],
        }
    )
    config = EngineConfig(
        performance_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 3),
        metric_basis="GROSS",
        period_type="YTD",
    )

    calculate_cumulative_ror(df, config)

    assert df[PortfolioColumns.LONG_CUM_ROR.value].tolist() == pytest.approx([10.0, 10.0, 10.0])
    assert df[PortfolioColumns.SHORT_CUM_ROR.value].tolist() == pytest.approx([0.0, 5.0, 5.0])
    assert df[PortfolioColumns.FINAL_CUM_ROR.value].iloc[-1] == pytest.approx(15.5)
    assert df["local_ror_long_cum_ror"].tolist() == pytest.approx([8.0, 8.0, 8.0])
    assert df["fx_ror_short_cum_ror"].tolist() == pytest.approx([0.0, 0.5, 0.5])


def test_zero_component_cumulative_returns_accepts_empty_component_list():
    df = pd.DataFrame({PortfolioColumns.PERF_RESET: [0, 1]})

    _zero_component_cumulative_returns(df, [], reset_mask=df[PortfolioColumns.PERF_RESET] == 1)

    assert list(df.columns) == [PortfolioColumns.PERF_RESET]
