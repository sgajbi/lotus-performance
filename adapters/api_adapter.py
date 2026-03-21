# adapters/api_adapter.py
import logging
from datetime import date
from typing import Any, Dict, List

import pandas as pd

from app.models.requests import PerformanceRequest
from app.models.responses import (
    PerformanceBreakdown,
    PerformanceResultItem,
    PerformanceSummary,
)
from common.enums import Frequency, PeriodType
from engine.config import EngineConfig, PrecisionMode
from engine.schema import PortfolioColumns

logger = logging.getLogger(__name__)


def create_engine_config(
    request: PerformanceRequest, effective_start_date: date, effective_end_date: date
) -> EngineConfig:
    """Creates an EngineConfig object from an API PerformanceRequest and an effective date range."""
    # Since we run the engine once on a master period, we can use the first analysis's period type
    # for the engine config. The specific slicing is handled later.
    period_type_for_engine = request.analyses[0].period if request.analyses else PeriodType.ITD

    return EngineConfig(
        performance_start_date=request.performance_start_date,
        report_start_date=effective_start_date,
        report_end_date=effective_end_date,
        metric_basis=request.metric_basis,
        period_type=period_type_for_engine,
        rounding_precision=request.rounding_precision,
        precision_mode=PrecisionMode(request.precision_mode),
        data_policy=request.data_policy,
        currency_mode=request.currency_mode,
        report_ccy=request.report_ccy,
        fx=request.fx,
        hedging=request.hedging,
    )


def create_engine_dataframe(valuation_points: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Creates a Pandas DataFrame for the engine from the raw valuation points list.
    No renaming is needed as the API contract now matches the engine's snake_case schema.
    """
    if not valuation_points:
        return pd.DataFrame()
    try:
        df = pd.DataFrame(valuation_points)
        if "perf_date" in df.columns:
            df.drop_duplicates(subset=["perf_date"], keep="last", inplace=True)
            df["perf_date"] = pd.to_datetime(df["perf_date"]).dt.date
            df.sort_values("perf_date", inplace=True)
            df.reset_index(drop=True, inplace=True)
        if "day" not in df.columns:
            df["day"] = range(1, len(df) + 1)
        return df
    except Exception as e:
        logger.exception("Failed to create DataFrame from daily data.")
        raise ValueError(f"Failed to process daily data: {e}")


def format_breakdowns_for_response(
    breakdowns_data: Dict[Frequency, List[Dict]], daily_results_df: pd.DataFrame, include_timeseries: bool
) -> PerformanceBreakdown:
    """
    Takes the pure breakdown dict from the engine and formats it into
    the Pydantic response models.
    """
    response_breakdowns = {}
    daily_records = daily_results_df.to_dict(orient="records")

    for freq, results in breakdowns_data.items():
        formatted_results = []
        for i, result_item in enumerate(results):
            summary_data = result_item["summary"]

            pydantic_summary_data = {
                "begin_mv": summary_data.get(PortfolioColumns.BEGIN_MV),
                "end_mv": summary_data.get(PortfolioColumns.END_MV),
                "net_cash_flow": summary_data.get("net_cash_flow"),
                "period_return_pct": summary_data.get("period_return_pct"),
                "cumulative_return_pct_to_date": summary_data.get("cumulative_return_pct_to_date"),
                "annualized_return_pct": summary_data.get("annualized_return_pct"),
            }

            summary_model = PerformanceSummary.model_validate(pydantic_summary_data)

            daily_data_for_period = None
            if freq == Frequency.DAILY and i < len(daily_records) and include_timeseries:
                daily_data_for_period = [daily_records[i]]

            formatted_results.append(
                PerformanceResultItem(
                    period=result_item["period"],
                    summary=summary_model,
                    daily_data=daily_data_for_period,
                )
            )
        response_breakdowns[freq] = formatted_results
    return response_breakdowns
