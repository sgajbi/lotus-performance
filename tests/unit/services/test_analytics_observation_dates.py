from datetime import date

import pandas as pd
import pytest

from app.services.analytics_observation_dates import (
    latest_observation_date,
    normalize_observation_date,
    observation_date_series,
    observation_date_set,
    observation_timestamp_series,
)


def test_latest_observation_date_normalizes_mixed_date_values():
    assert latest_observation_date(["2026-03-29", date(2026, 3, 31), None, "2026-03-30T12:00:00Z"]) == date(
        2026,
        3,
        31,
    )


def test_latest_observation_date_returns_none_when_no_values_exist():
    assert latest_observation_date([None]) is None


def test_observation_date_set_normalizes_unique_date_values():
    assert observation_date_set(["2026-03-31T09:00:00Z", date(2026, 3, 31), None, "2026-04-01"]) == {
        date(2026, 3, 31),
        date(2026, 4, 1),
    }


def test_observation_date_series_normalizes_ordered_date_values():
    assert list(observation_date_series(["2026-03-31T09:00:00Z", date(2026, 4, 1)])) == [
        date(2026, 3, 31),
        date(2026, 4, 1),
    ]


def test_observation_timestamp_series_preserves_index_and_normalizes_mixed_timezones():
    series = observation_timestamp_series(pd.Series(["2026-03-31", "2026-04-01T10:00:00Z"], index=["a", "b"]))

    assert series.index.tolist() == ["a", "b"]
    assert [value.isoformat() for value in series] == ["2026-03-31T00:00:00", "2026-04-01T10:00:00"]


def test_normalize_observation_date_rejects_invalid_date_values():
    with pytest.raises(ValueError):
        normalize_observation_date("not-a-date")
