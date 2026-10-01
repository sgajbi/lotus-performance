import pytest

from engine.dataframe import create_engine_dataframe_from_valuation_points
from engine.exceptions import InvalidEngineInputError


def test_create_engine_dataframe_from_valuation_points_normalizes_dates_and_day_numbers():
    df = create_engine_dataframe_from_valuation_points(
        [
            {"perf_date": "2025-01-02", "begin_mv": 101.0, "end_mv": 102.0},
            {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 101.0},
            {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 101.0},
        ]
    )

    assert [str(item) for item in df["perf_date"].tolist()] == ["2025-01-01", "2025-01-02"]
    assert df["begin_mv"].tolist() == [100.0, 101.0]
    assert df["day"].tolist() == [1, 2]


@pytest.mark.parametrize("reverse", [False, True])
def test_create_engine_dataframe_from_valuation_points_rejects_order_dependent_conflicts(reverse):
    points = [
        {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 110.0},
        {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 120.0},
    ]

    with pytest.raises(InvalidEngineInputError, match="conflicting valuation observations.*end_mv"):
        create_engine_dataframe_from_valuation_points(list(reversed(points)) if reverse else points)


def test_create_engine_dataframe_from_valuation_points_deduplicates_normalized_identical_dates():
    df = create_engine_dataframe_from_valuation_points(
        [
            {"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 110.0},
            {"perf_date": "2025-01-01T00:00:00Z", "begin_mv": 100.0, "end_mv": 110.0},
        ]
    )

    assert len(df) == 1
    assert df.iloc[0]["end_mv"] == 110.0


@pytest.mark.parametrize("field_name", ["begin_mv", "bod_cf", "eod_cf", "mgmt_fees", "end_mv"])
def test_create_engine_dataframe_from_valuation_points_rejects_non_finite_economics(field_name):
    point = {
        "perf_date": "2025-01-01",
        "begin_mv": 100.0,
        "bod_cf": 0.0,
        "eod_cf": 0.0,
        "mgmt_fees": 0.0,
        "end_mv": 110.0,
    }
    point[field_name] = float("nan")

    with pytest.raises(InvalidEngineInputError, match=f"{field_name} must be a finite number"):
        create_engine_dataframe_from_valuation_points([point])


def test_create_engine_dataframe_from_valuation_points_preserves_existing_day_values():
    df = create_engine_dataframe_from_valuation_points(
        [{"perf_date": "2025-01-01", "begin_mv": 100.0, "end_mv": 101.0, "day": 7}]
    )

    assert df["day"].tolist() == [7]


def test_create_engine_dataframe_from_valuation_points_wraps_malformed_input():
    with pytest.raises(ValueError, match="Failed to process daily data"):
        create_engine_dataframe_from_valuation_points("not-records")  # type: ignore[arg-type]
