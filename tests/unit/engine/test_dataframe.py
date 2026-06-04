import pytest

from engine.dataframe import create_engine_dataframe_from_valuation_points


def test_create_engine_dataframe_from_valuation_points_normalizes_dates_and_day_numbers():
    df = create_engine_dataframe_from_valuation_points(
        [
            {"perf_date": "2025-01-02", "begin_mv": 101.0, "end_mv": 102.0},
            {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 101.0},
            {"perf_date": "2025-01-01", "begin_mv": 100.5, "end_mv": 101.5},
        ]
    )

    assert [str(item) for item in df["perf_date"].tolist()] == ["2025-01-01", "2025-01-02"]
    assert df["begin_mv"].tolist() == [100.5, 101.0]
    assert df["day"].tolist() == [1, 2]


def test_create_engine_dataframe_from_valuation_points_preserves_existing_day_values():
    df = create_engine_dataframe_from_valuation_points(
        [{"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 101.0, "day": 7}]
    )

    assert df["day"].tolist() == [7]


def test_create_engine_dataframe_from_valuation_points_wraps_malformed_input():
    with pytest.raises(ValueError, match="Failed to process daily data"):
        create_engine_dataframe_from_valuation_points("not-records")  # type: ignore[arg-type]
