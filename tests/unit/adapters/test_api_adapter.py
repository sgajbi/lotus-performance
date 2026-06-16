# tests/unit/adapters/test_api_adapter.py
from datetime import date
from typing import Any, Dict, List

import pandas as pd
import pytest

from adapters.api_adapter import (
    _daily_data_for_breakdown,
    _performance_summary_payload,
    create_engine_config,
    create_engine_dataframe,
    format_breakdowns_for_response,
)
from app.models.requests import PerformanceRequest
from app.models.responses import PerformanceResultItem, PerformanceSummary
from common.enums import Frequency, PeriodType
from engine.config import EngineConfig
from engine.schema import PortfolioColumns


@pytest.fixture
def sample_engine_outputs():
    """Provides sample, raw engine outputs for testing the response formatter."""
    breakdowns_data = {
        Frequency.DAILY: [
            {
                "period": "2025-01-01",
                "summary": {
                    PortfolioColumns.BEGIN_MV: 1000.0,
                    PortfolioColumns.END_MV: 1010.0,
                    "net_cash_flow": 0.0,
                    "period_return_pct": 1.0,
                    "cumulative_return_pct_to_date": 1.0,
                },
            }
        ],
        Frequency.MONTHLY: [
            {
                "period": "2025-01",
                "summary": {
                    PortfolioColumns.BEGIN_MV: 1000.0,
                    PortfolioColumns.END_MV: 1010.0,
                    "net_cash_flow": 0.0,
                    "period_return_pct": 1.0,
                    "cumulative_return_pct_to_date": 1.0,
                },
            }
        ],
    }
    daily_results_df = pd.DataFrame(
        [
            {
                PortfolioColumns.PERF_DATE: date(2025, 1, 1),
                PortfolioColumns.BEGIN_MV: 1000.0,
                PortfolioColumns.END_MV: 1010.0,
            }
        ]
    )
    return breakdowns_data, daily_results_df


def test_create_engine_config():
    """Tests that the adapter correctly converts a PerformanceRequest into an EngineConfig object."""
    request_data = {
        "portfolio_id": "TEST_01",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-31",
        "metric_basis": "NET",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "valuation_points": [],
    }
    pydantic_request = PerformanceRequest.model_validate(request_data)

    start_date = date(2025, 1, 1)
    end_date = date(2025, 1, 31)

    engine_config = create_engine_config(pydantic_request, start_date, end_date)

    assert isinstance(engine_config, EngineConfig)
    assert engine_config.report_start_date == start_date
    assert engine_config.report_end_date == end_date
    assert engine_config.metric_basis == "NET"
    assert engine_config.period_type == PeriodType.YTD


def test_create_engine_dataframe_happy_path():
    """Tests that a list of daily data dictionaries is correctly converted into a DataFrame."""
    api_valuation_points: List[Dict[str, Any]] = [
        {"perf_date": "2025-01-01", "begin_mv": 1000},
        {"perf_date": "2025-01-02", "begin_mv": 1010},
    ]

    engine_df = create_engine_dataframe(api_valuation_points)

    assert isinstance(engine_df, pd.DataFrame)
    assert not engine_df.empty
    assert "perf_date" in engine_df.columns
    assert "begin_mv" in engine_df.columns


def test_create_engine_dataframe_empty_input():
    """Tests that an empty list of daily data correctly results in an empty DataFrame."""
    empty_api_data: List[Dict[str, Any]] = []
    engine_df = create_engine_dataframe(empty_api_data)
    assert isinstance(engine_df, pd.DataFrame)
    assert engine_df.empty


def test_create_engine_dataframe_raises_error():
    """Tests that the adapter function correctly raises a ValueError for malformed input."""
    malformed_api_data = [{"perf_date": "2025-01-01", "begin_mv": 1000}, "not_a_dictionary"]
    with pytest.raises(ValueError, match="Failed to process daily data"):
        create_engine_dataframe(malformed_api_data)


def test_format_breakdowns_for_response_daily(sample_engine_outputs):
    """Tests that the daily breakdown is formatted correctly with snake_case keys."""
    breakdowns_data, daily_results_df = sample_engine_outputs
    formatted_response = format_breakdowns_for_response(breakdowns_data, daily_results_df, include_timeseries=True)

    assert Frequency.DAILY in formatted_response
    daily_breakdown = formatted_response[Frequency.DAILY]
    result_item = daily_breakdown[0]
    assert isinstance(result_item, PerformanceResultItem)
    assert isinstance(result_item.summary, PerformanceSummary)
    assert result_item.summary.begin_mv == 1000.0
    assert result_item.daily_data is not None
    nested_daily = result_item.daily_data[0]
    assert "begin_mv" in nested_daily
    assert PortfolioColumns.BEGIN_MV.value in nested_daily


def test_format_breakdowns_for_response_monthly(sample_engine_outputs):
    """Tests that aggregated breakdowns are formatted correctly, with daily_data being None."""
    breakdowns_data, daily_results_df = sample_engine_outputs
    formatted_response = format_breakdowns_for_response(breakdowns_data, daily_results_df, include_timeseries=False)

    assert Frequency.MONTHLY in formatted_response
    monthly_breakdown = formatted_response[Frequency.MONTHLY]
    result_item = monthly_breakdown[0]
    assert isinstance(result_item, PerformanceResultItem)
    assert result_item.period == "2025-01"
    assert result_item.daily_data is None


def test_format_breakdowns_for_response_empty_input():
    """Tests that the formatter handles empty engine output gracefully."""
    empty_breakdowns = {}
    empty_df = pd.DataFrame()
    formatted_response = format_breakdowns_for_response(empty_breakdowns, empty_df, include_timeseries=False)
    assert formatted_response == {}


def test_performance_summary_payload_maps_engine_summary_keys():
    payload = _performance_summary_payload(
        {
            PortfolioColumns.BEGIN_MV: 1000.0,
            PortfolioColumns.END_MV: 1010.0,
            "net_cash_flow": 5.0,
            "period_return_pct": 1.0,
            "cumulative_return_pct_to_date": 2.0,
            "annualized_return_pct": 12.0,
        }
    )

    assert payload == {
        "begin_mv": 1000.0,
        "end_mv": 1010.0,
        "net_cash_flow": 5.0,
        "period_return_pct": 1.0,
        "cumulative_return_pct_to_date": 2.0,
        "annualized_return_pct": 12.0,
    }


def test_daily_data_for_breakdown_respects_frequency_bounds_and_flag():
    daily_records = [{"perf_date": date(2025, 1, 1)}]

    assert _daily_data_for_breakdown(
        frequency=Frequency.DAILY,
        item_index=0,
        daily_records=daily_records,
        include_timeseries=True,
    ) == [daily_records[0]]
    assert (
        _daily_data_for_breakdown(
            frequency=Frequency.MONTHLY,
            item_index=0,
            daily_records=daily_records,
            include_timeseries=True,
        )
        is None
    )
    assert (
        _daily_data_for_breakdown(
            frequency=Frequency.DAILY,
            item_index=1,
            daily_records=daily_records,
            include_timeseries=True,
        )
        is None
    )
    assert (
        _daily_data_for_breakdown(
            frequency=Frequency.DAILY,
            item_index=0,
            daily_records=daily_records,
            include_timeseries=False,
        )
        is None
    )


def test_format_breakdowns_populates_daily_cumulative_return(sample_engine_outputs):
    """Tests that the cumulative return is correctly populated for daily summaries."""
    breakdowns_data, daily_results_df = sample_engine_outputs

    breakdowns_data[Frequency.DAILY][0]["summary"].pop("cumulative_return_pct_to_date", None)

    formatted_response = format_breakdowns_for_response(breakdowns_data, daily_results_df, include_timeseries=True)

    daily_summary = formatted_response[Frequency.DAILY][0].summary
    assert daily_summary.cumulative_return_pct_to_date is None
