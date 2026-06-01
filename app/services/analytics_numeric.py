from __future__ import annotations

from typing import Any

import pandas as pd
from pandas.api.types import is_scalar


def numeric_value(value: Any, default: Any = 0) -> Any:
    """Coerce a scalar numeric-like value, returning the default for invalid inputs."""
    try:
        numeric = pd.to_numeric(value, errors="coerce")
    except (TypeError, ValueError):
        return default
    if not is_scalar(numeric) or pd.isna(numeric):
        return default
    return numeric


def numeric_series(values: pd.Series, default: Any = 0) -> pd.Series:
    """Coerce a Series to numeric values, filling invalid values with the default."""
    return pd.to_numeric(values, errors="coerce").fillna(default)


def valid_numeric_series(values: pd.Series) -> pd.Series:
    """Coerce a Series to numeric values and discard invalid observations."""
    return pd.to_numeric(values, errors="coerce").dropna()


def numeric_series_or_default(df: pd.DataFrame, column_name: str, default: Any = 0) -> pd.Series:
    """Return a numeric Series for a column, or a default-filled fallback aligned to the frame index."""
    if column_name not in df.columns:
        return pd.Series(default, index=df.index)
    return numeric_series(df[column_name], default=default)
