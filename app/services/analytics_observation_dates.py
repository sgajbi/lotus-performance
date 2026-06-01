from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

import pandas as pd


def latest_observation_date(values: Iterable[Any]) -> date | None:
    normalized_dates = [normalize_observation_date(value) for value in values if value is not None]
    return max(normalized_dates) if normalized_dates else None


def normalize_observation_date(value: Any) -> date:
    return pd.Timestamp(value).date()
