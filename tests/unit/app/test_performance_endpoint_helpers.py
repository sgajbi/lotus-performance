from datetime import date

import pandas as pd
import pytest

from app.services.twr_service import (
    _as_numeric,
    _calculate_total_return_from_slice,
    _get_total_cum_ror,
)
from engine.schema import PortfolioColumns


def test_as_numeric_returns_default_for_non_numeric_values():
    assert _as_numeric("not-a-number", default=7) == 7


def test_get_total_cum_ror_returns_zero_for_missing_row():
    assert _get_total_cum_ror(None, "local_ror_") == 0.0


def test_calculate_total_return_from_slice_returns_zero_for_empty_slice():
    empty_df = pd.DataFrame(
        columns=[
            PortfolioColumns.PERF_DATE.value,
            PortfolioColumns.PERF_RESET.value,
            PortfolioColumns.DAILY_ROR.value,
        ]
    )
    result = _calculate_total_return_from_slice(empty_df, empty_df)
    assert result.base == 0.0
    assert result.local == 0.0
    assert result.fx == 0.0


def test_calculate_total_return_from_slice_reset_handles_zero_base_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: -100.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 0.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 12.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 2.0,
                "local_ror_short_cum_ror": 3.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    assert result.base == pytest.approx(12.0)


def test_calculate_total_return_from_slice_reset_handles_zero_fx_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: 0.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 0.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 5.0,
                "local_ror": -100.0,
                "local_ror_long_cum_ror": -100.0,
                "local_ror_short_cum_ror": 0.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    assert result.local == pytest.approx(-100.0)
    assert result.fx == 0.0


def test_calculate_total_return_from_slice_reset_handles_zero_local_start_denominator():
    full_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 1),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.FINAL_CUM_ROR.value: 0.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": -100.0,
                "local_ror_short_cum_ror": 0.0,
            },
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: True,
                PortfolioColumns.FINAL_CUM_ROR.value: 5.0,
                "local_ror": 0.0,
                "local_ror_long_cum_ror": 2.0,
                "local_ror_short_cum_ror": 3.0,
            },
        ]
    )
    period_slice = full_df[full_df[PortfolioColumns.PERF_DATE.value] == date(2025, 1, 2)]

    result = _calculate_total_return_from_slice(period_slice, full_df)
    expected_end_local = ((1 + 2.0 / 100) * (1 + 3.0 / 100) - 1) * 100
    assert result.local == pytest.approx(expected_end_local)


def test_calculate_total_return_from_slice_non_reset_handles_zero_fx_denominator():
    non_reset_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE.value: date(2025, 1, 2),
                PortfolioColumns.PERF_RESET.value: False,
                PortfolioColumns.DAILY_ROR.value: -100.0,
                "local_ror": -100.0,
            }
        ]
    )

    result = _calculate_total_return_from_slice(non_reset_df, non_reset_df)
    assert result.local == pytest.approx(-100.0)
    assert result.fx == 0.0
