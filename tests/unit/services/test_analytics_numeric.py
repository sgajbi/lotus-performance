import pandas as pd

from app.services.analytics_numeric import numeric_series, numeric_series_or_default, numeric_value


def test_numeric_value_returns_default_for_invalid_or_non_scalar_values():
    assert numeric_value("not-a-number", default=7) == 7
    assert numeric_value(["1"], default=7) == 7


def test_numeric_value_preserves_numeric_like_scalars():
    assert numeric_value("4.5") == 4.5
    assert numeric_value(3) == 3


def test_numeric_series_or_default_aligns_missing_column_to_frame_index():
    frame = pd.DataFrame({"present": ["1", None]}, index=["a", "b"])

    result = numeric_series_or_default(frame, "missing")

    assert result.index.tolist() == ["a", "b"]
    assert result.tolist() == [0, 0]


def test_numeric_series_preserves_index_and_coerces_invalid_values_to_default():
    series = pd.Series(["1.5", "bad"], index=["a", "b"])

    result = numeric_series(series, default=-1)

    assert result.index.tolist() == ["a", "b"]
    assert result.tolist() == [1.5, -1.0]


def test_numeric_series_or_default_coerces_invalid_values_to_default():
    frame = pd.DataFrame({"amount": ["1.5", "bad"]})

    result = numeric_series_or_default(frame, "amount", default=-1)

    assert result.tolist() == [1.5, -1.0]
