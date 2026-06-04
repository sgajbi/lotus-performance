import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def create_engine_dataframe_from_valuation_points(valuation_points: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Create a normalized engine DataFrame from valuation-point records.

    The API contract already uses the engine's snake_case schema, so this helper only enforces
    deterministic date handling, duplicate-date resolution, sorting, and day numbering.
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
    except Exception as exc:
        logger.exception("Failed to create DataFrame from daily data.")
        raise ValueError(f"Failed to process daily data: {exc}") from exc
