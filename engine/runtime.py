from __future__ import annotations

from dataclasses import replace
from typing import Any

import pandas as pd

from adapters.api_adapter import create_engine_dataframe
from engine.compute import run_calculations
from engine.config import EngineConfig
from engine.schema import PortfolioColumns


def base_only_engine_config(config: EngineConfig) -> EngineConfig:
    """Return a BASE_ONLY variant while preserving the rest of the engine config."""
    return replace(config, currency_mode="BASE_ONLY")


def run_engine_for_valuation_points(
    valuation_points: list[dict[str, Any]],
    config: EngineConfig,
    *,
    force_base_only: bool = False,
) -> pd.DataFrame:
    """Run the engine over valuation points and normalize perf_date to pandas timestamps."""
    engine_df = create_engine_dataframe(valuation_points)
    effective_config = base_only_engine_config(config) if force_base_only else config
    results_df, _ = run_calculations(engine_df, effective_config)
    if PortfolioColumns.PERF_DATE.value in results_df.columns:
        results_df[PortfolioColumns.PERF_DATE.value] = pd.to_datetime(results_df[PortfolioColumns.PERF_DATE.value])
    return results_df
