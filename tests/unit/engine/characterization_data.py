# tests/unit/engine/characterization_data.py
from datetime import date

import pandas as pd

from engine.config import EngineConfig, FXRequestBlock, PeriodType
from engine.schema import PortfolioColumns


def cumulative_return_scenario():
    """Provides a simple two-day scenario to validate running cumulative return."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        metric_basis="GROSS",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.DAY: [1, 2],
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.BEGIN_MV: [100.0, 110.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0],
            PortfolioColumns.END_MV: [110.0, 126.5],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: [date(2025, 1, 1), date(2025, 1, 2)],
            PortfolioColumns.DAILY_ROR: [10.0, 15.0],
            # Day 1: 10%
            # Day 2: (1.10 * 1.15) - 1 = 1.265 - 1 = 26.5%
            PortfolioColumns.FINAL_CUM_ROR: [10.0, 26.5],
        }
    )
    return engine_config, input_df, expected_df


def long_flip_scenario():
    """Provides the input and expected output for the long flip scenario."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 4),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.DAY: [1, 2, 3, 4],
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]),
            PortfolioColumns.BEGIN_MV: [1000.0, 500.0, -50.0, 1050.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0, 1000.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.END_MV: [500.0, -50.0, 1050.0, 1155.0],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4)],
            PortfolioColumns.SIGN: [1, 1, 1, 1],
            PortfolioColumns.DAILY_ROR: [-50.0, -110.0, 10.5263, 10.0],
            PortfolioColumns.NIP: [0, 0, 0, 0],
            PortfolioColumns.PERF_RESET: [0, 1, 0, 0],
            PortfolioColumns.LONG_SHORT: ["L", "L", "L", "L"],
            PortfolioColumns.NCTRL_1: [0, 1, 0, 0],
            PortfolioColumns.NCTRL_2: [0, 0, 0, 0],
            PortfolioColumns.NCTRL_3: [0, 0, 0, 0],
            PortfolioColumns.NCTRL_4: [0, 0, 0, 0],
            PortfolioColumns.TEMP_LONG_CUM_ROR: [-50.0, -105.0, -105.5263, -106.0789],
            PortfolioColumns.TEMP_SHORT_CUM_ROR: [0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.LONG_CUM_ROR: [-50.0, 0.0, 10.5263, 21.5789],
            PortfolioColumns.SHORT_CUM_ROR: [0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.FINAL_CUM_ROR: [-50.0, 0.0, 10.5263, 21.5789],
        }
    )
    return engine_config, input_df, expected_df


def short_flip_scenario():
    """Provides the input and expected output for the short position flip scenario."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 3),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.DAY: [1, 2, 3],
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            PortfolioColumns.BEGIN_MV: [-1000.0, -900.0, 500.0],
            PortfolioColumns.BOD_CF: [0.0, 1500.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0, 0.0],
            PortfolioColumns.END_MV: [-900.0, 500.0, 550.0],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)],
            PortfolioColumns.SIGN: [-1, 1, 1],
            PortfolioColumns.DAILY_ROR: [10.0, -16.6667, 10.0],
            PortfolioColumns.NIP: [0, 0, 0],
            PortfolioColumns.PERF_RESET: [0, 0, 0],
            PortfolioColumns.LONG_SHORT: ["S", "L", "L"],
            PortfolioColumns.NCTRL_1: [0, 0, 0],
            PortfolioColumns.NCTRL_2: [0, 0, 0],
            PortfolioColumns.NCTRL_3: [0, 0, 0],
            PortfolioColumns.NCTRL_4: [0, 0, 0],
            PortfolioColumns.TEMP_LONG_CUM_ROR: [0.0, -16.6667, -8.3333],
            PortfolioColumns.TEMP_SHORT_CUM_ROR: [10.0, 10.0, 10.0],
            PortfolioColumns.LONG_CUM_ROR: [0.0, -16.6667, -8.3333],
            PortfolioColumns.SHORT_CUM_ROR: [10.0, 10.0, 10.0],
            PortfolioColumns.FINAL_CUM_ROR: [10.0, -8.3333, 0.8333],
        }
    )
    return engine_config, input_df, expected_df


def zero_value_nip_scenario():
    """Provides data for a scenario involving zero-value days and NIP."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 5),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.DAY: [1, 2, 3, 4, 5],
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ),
            PortfolioColumns.BEGIN_MV: [1000.0, 1050.0, 0.0, 0.0, 0.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0, 20.0, 0.0, 100.0],
            PortfolioColumns.EOD_CF: [0.0, -1050.0, -20.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.END_MV: [1050.0, 0.0, 0.0, 0.0, 110.0],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ).date,
            PortfolioColumns.SIGN: [1, 1, 1, 0, 1],
            PortfolioColumns.DAILY_ROR: [5.0, 0.0, 0.0, 0.0, 10.0],
            PortfolioColumns.NIP: [0, 0, 0, 1, 0],
            PortfolioColumns.PERF_RESET: [0, 0, 0, 0, 0],
            PortfolioColumns.LONG_CUM_ROR: [5.0, 5.0, 5.0, 5.0, 15.5],
            PortfolioColumns.FINAL_CUM_ROR: [5.0, 5.0, 5.0, 5.0, 15.5],
        }
    )
    return engine_config, input_df, expected_df


def standard_growth_scenario():
    """Provides data for a standard growth scenario with cashflows."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 5),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.DAY: [1, 2, 3, 4, 5],
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ),
            PortfolioColumns.BEGIN_MV: [100000.0, 101000.0, 102010.0, 100989.9, 127249.29],
            PortfolioColumns.BOD_CF: [0.0, 0.0, 0.0, 25000.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.END_MV: [101000.0, 102010.0, 100989.9, 127249.29, 125976.7971],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ).date,
            PortfolioColumns.DAILY_ROR: [1.0, 1.0, -1.0, 0.9996, -1.0],
            PortfolioColumns.FINAL_CUM_ROR: [1.0, 2.01, 0.9899, 1.9994, 0.9794],
        }
    )
    return engine_config, input_df, expected_df


def short_growth_scenario():
    """Provides data for a short position with negative growth."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 4),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]),
            PortfolioColumns.BEGIN_MV: [-1000.0, -1500.0, -3500.0, -1400.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0, 2000.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0, 0.0, 0.0],
            PortfolioColumns.END_MV: [-1500.0, -3500.0, -1400.0, -1300.0],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]).date,
            PortfolioColumns.DAILY_ROR: [-50.0, -133.3333, 6.6667, 7.1429],
            PortfolioColumns.FINAL_CUM_ROR: [-50.0, -250.0, -226.6667, -203.3333],
        }
    )
    return engine_config, input_df, expected_df


def eod_flip_net_scenario():
    """Provides data for a sign flip caused by an EOD cashflow, NET basis."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 5),
        metric_basis="NET",
        period_type=PeriodType.YTD,
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ),
            PortfolioColumns.BEGIN_MV: [1000.0, 1100.0, -200.0, -100.0, 400.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0, 0.0, 600.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, -1500.0, 0.0, 0.0, -20.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0, 0.0, 0.0, -20.0],
            PortfolioColumns.END_MV: [1100.0, -200.0, -100.0, 400.0, 480.0],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ).date,
            PortfolioColumns.FINAL_CUM_ROR: [10.0, 30.0, 95.0, 56.0, 87.2],
        }
    )
    return engine_config, input_df, expected_df


def eod_flip_gross_scenario():
    """Provides data for a sign flip caused by an EOD cashflow, GROSS basis."""
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 5),
        metric_basis="GROSS",
        period_type=PeriodType.YTD,
    )
    _, input_df, _ = eod_flip_net_scenario()
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ).date,
            PortfolioColumns.FINAL_CUM_ROR: [10.0, 30.0, 95.0, 56.0, 95.0],
        }
    )
    return engine_config, input_df, expected_df


def multi_currency_scenario():
    """Provides data for an end-to-end multi-currency TWR calculation."""
    fx_rates_data = {
        "rates": [
            {"date": date(2024, 12, 31), "ccy": "EUR", "rate": 1.05},
            {"date": date(2025, 1, 1), "ccy": "EUR", "rate": 1.08},
            {"date": date(2025, 1, 2), "ccy": "EUR", "rate": 1.07},
        ]
    }
    engine_config = EngineConfig(
        performance_start_date=date(2024, 12, 31),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        metric_basis="GROSS",
        period_type=PeriodType.YTD,
        currency_mode="BOTH",
        report_ccy="USD",
        fx=FXRequestBlock.model_validate(fx_rates_data),
    )
    input_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: pd.to_datetime(["2025-01-01", "2025-01-02"]),
            PortfolioColumns.BEGIN_MV: [100.0, 102.0],
            PortfolioColumns.BOD_CF: [0.0, 0.0],
            PortfolioColumns.EOD_CF: [0.0, 0.0],
            PortfolioColumns.MGMT_FEES: [0.0, 0.0],
            PortfolioColumns.END_MV: [102.0, 103.02],
        }
    )
    expected_df = pd.DataFrame(
        {
            PortfolioColumns.PERF_DATE: [date(2025, 1, 1), date(2025, 1, 2)],
            PortfolioColumns.DAILY_ROR: [4.9143, 0.0648],
            PortfolioColumns.FINAL_CUM_ROR: [4.9143, 4.9823],
        }
    )
    return engine_config, input_df, expected_df


CHARACTERIZATION_SCENARIOS = [
    ("long_flip", long_flip_scenario),
    ("short_flip", short_flip_scenario),
    ("zero_value_nip", zero_value_nip_scenario),
    ("standard_growth", standard_growth_scenario),
    ("short_growth", short_growth_scenario),
    ("eod_flip_net", eod_flip_net_scenario),
    ("eod_flip_gross", eod_flip_gross_scenario),
    ("multi_currency", multi_currency_scenario),
    ("cumulative_return", cumulative_return_scenario),
]
