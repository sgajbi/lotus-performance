from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

import pandas as pd


def latest_observation_date(values: Iterable[Any]) -> date | None:
    normalized_dates = [pd.Timestamp(value).date() for value in values if value is not None]
    return max(normalized_dates) if normalized_dates else None
