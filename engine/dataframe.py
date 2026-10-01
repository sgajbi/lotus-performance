import logging
from typing import Any

import pandas as pd

from core.valuation_observation_admission import (
    ValuationObservationAdmissionError,
    admit_valuation_observations,
    normalize_valuation_observation_date,
)
from engine.exceptions import InvalidEngineInputError

logger = logging.getLogger(__name__)


def create_engine_dataframe_from_valuation_points(valuation_points: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Create a normalized engine DataFrame from valuation-point records.

    The API contract already uses the engine's snake_case schema, so this helper enforces
    deterministic date handling, admitted duplicate-date policy, sorting, and day numbering.
    """
    if not valuation_points:
        return pd.DataFrame()
    try:
        try:
            admitted_points = admit_valuation_observations(valuation_points)
        except ValuationObservationAdmissionError as exc:
            raise InvalidEngineInputError(str(exc)) from exc
        df = pd.DataFrame(admitted_points)
        if "perf_date" in df.columns:
            df["perf_date"] = df["perf_date"].map(normalize_valuation_observation_date)
            df.sort_values("perf_date", inplace=True)
            df.reset_index(drop=True, inplace=True)
        if "day" not in df.columns:
            df["day"] = range(1, len(df) + 1)
        return df
    except InvalidEngineInputError:
        raise
    except Exception as exc:
        logger.exception("Failed to create DataFrame from daily data.")
        raise ValueError(f"Failed to process daily data: {exc}") from exc
