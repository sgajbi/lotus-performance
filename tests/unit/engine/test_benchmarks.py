from datetime import date

import pytest

from app.models.benchmark_requests import BenchmarkComponentObservation, BenchmarkReturnPoint
from engine.benchmarks import (
    _component_contributions_dataframe,
    _uses_local_fx_component_returns,
    benchmark_return_points_to_dataframe,
    calculate_benchmark_returns,
)


def test_calculate_benchmark_returns_aggregates_component_contributions():
    result = calculate_benchmark_returns(
        [
            BenchmarkComponentObservation(
                component_id="IDX_A",
                perf_date=date(2026, 1, 2),
                weight_bop=0.6,
                component_return=0.02,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_B",
                perf_date=date(2026, 1, 2),
                weight_bop=0.4,
                component_return=0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_A",
                perf_date=date(2026, 1, 3),
                weight_bop=0.6,
                component_return=0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_B",
                perf_date=date(2026, 1, 3),
                weight_bop=0.4,
                component_return=0.005,
            ),
        ]
    )

    daily_rows = result.daily_returns_df.to_dict(orient="records")
    assert float(daily_rows[0]["benchmark_return"]) == pytest.approx(0.016)
    assert float(daily_rows[1]["benchmark_return"]) == pytest.approx(0.008)
    assert float(daily_rows[1]["cumulative_return"]) == pytest.approx(0.024128)
    assert result.max_weight_sum_deviation == pytest.approx(0.0)
    assert result.notes == []

    contribution_rows = result.component_contributions_df.to_dict(orient="records")
    assert float(contribution_rows[0]["contribution"]) == pytest.approx(0.012)
    assert float(contribution_rows[1]["contribution"]) == pytest.approx(0.004)


def test_calculate_benchmark_returns_preserves_local_and_fx_components():
    result = calculate_benchmark_returns(
        [
            BenchmarkComponentObservation(
                component_id="IDX_A",
                component_currency="EUR",
                perf_date=date(2026, 1, 2),
                weight_bop=1.0,
                component_return=0.0302,
                component_return_local=0.02,
                component_return_fx=0.01,
            )
        ]
    )

    daily_row = result.daily_returns_df.to_dict(orient="records")[0]
    assert float(daily_row["benchmark_return_local"]) == pytest.approx(0.02)
    assert float(daily_row["benchmark_return_fx"]) == pytest.approx(0.01)

    contribution_row = result.component_contributions_df.to_dict(orient="records")[0]
    assert contribution_row["component_currency"] == "EUR"
    assert float(contribution_row["local_contribution"]) == pytest.approx(0.02)
    assert float(contribution_row["fx_contribution"]) == pytest.approx(0.01)


def test_component_contributions_dataframe_preserves_decimal_values_and_sort_order():
    contributions_df = _component_contributions_dataframe(
        [
            BenchmarkComponentObservation(
                component_id="IDX_B",
                component_currency="EUR",
                perf_date=date(2026, 1, 2),
                weight_bop=0.4,
                component_return=0.0201,
                component_return_local=0.01,
                component_return_fx=0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_A",
                component_currency="USD",
                perf_date=date(2026, 1, 2),
                weight_bop=0.6,
                component_return=0.02,
                component_return_local=0.02,
                component_return_fx=0.0,
            ),
        ],
        has_any_local=True,
    )

    rows = contributions_df.to_dict(orient="records")
    assert [row["component_id"] for row in rows] == ["IDX_A", "IDX_B"]
    assert str(rows[0]["weight_bop"]) == "0.6"
    assert str(rows[0]["contribution"]) == "0.012"
    assert str(rows[1]["local_contribution"]) == "0.004"
    assert str(rows[1]["fx_contribution"]) == "0.004"


def test_uses_local_fx_component_returns_detects_complete_and_absent_modes():
    assert not _uses_local_fx_component_returns(
        [
            BenchmarkComponentObservation(
                component_id="IDX_A",
                perf_date=date(2026, 1, 2),
                weight_bop=1.0,
                component_return=0.02,
            )
        ]
    )
    assert _uses_local_fx_component_returns(
        [
            BenchmarkComponentObservation(
                component_id="IDX_A",
                component_currency="EUR",
                perf_date=date(2026, 1, 2),
                weight_bop=1.0,
                component_return=0.0302,
                component_return_local=0.02,
                component_return_fx=0.01,
            )
        ]
    )


def test_uses_local_fx_component_returns_rejects_incomplete_mode():
    with pytest.raises(ValueError, match="must be supplied together"):
        _uses_local_fx_component_returns(
            [
                BenchmarkComponentObservation(
                    component_id="IDX_A",
                    perf_date=date(2026, 1, 2),
                    weight_bop=1.0,
                    component_return=0.02,
                    component_return_local=0.015,
                )
            ]
        )


def test_benchmark_return_points_to_dataframe_links_vendor_series():
    returns_df = benchmark_return_points_to_dataframe(
        [
            BenchmarkReturnPoint(perf_date=date(2026, 1, 2), benchmark_return=0.012),
            BenchmarkReturnPoint(perf_date=date(2026, 1, 3), benchmark_return=-0.002),
        ]
    )

    rows = returns_df.to_dict(orient="records")
    assert float(rows[0]["cumulative_return"]) == pytest.approx(0.012)
    assert float(rows[1]["cumulative_return"]) == pytest.approx(0.009976)


def test_calculate_benchmark_returns_rejects_duplicate_component_rows():
    with pytest.raises(ValueError, match="Duplicate component observation"):
        calculate_benchmark_returns(
            [
                BenchmarkComponentObservation(
                    component_id="IDX_A",
                    perf_date=date(2026, 1, 2),
                    weight_bop=1.0,
                    component_return=0.02,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX_A",
                    perf_date=date(2026, 1, 2),
                    weight_bop=1.0,
                    component_return=0.02,
                ),
            ]
        )


def test_calculate_benchmark_returns_rejects_empty_inputs_and_incomplete_local_fx_pairs():
    with pytest.raises(ValueError, match="must not be empty"):
        calculate_benchmark_returns([])

    with pytest.raises(ValueError, match="must be supplied together"):
        calculate_benchmark_returns(
            [
                BenchmarkComponentObservation(
                    component_id="IDX_A",
                    perf_date=date(2026, 1, 2),
                    weight_bop=1.0,
                    component_return=0.02,
                    component_return_local=0.015,
                )
            ]
        )

    with pytest.raises(ValueError, match="must be populated for every observation"):
        calculate_benchmark_returns(
            [
                BenchmarkComponentObservation(
                    component_id="IDX_A",
                    perf_date=date(2026, 1, 2),
                    weight_bop=0.5,
                    component_return=0.02,
                    component_return_local=0.015,
                    component_return_fx=0.005,
                ),
                BenchmarkComponentObservation(
                    component_id="IDX_B",
                    perf_date=date(2026, 1, 2),
                    weight_bop=0.5,
                    component_return=0.01,
                ),
            ]
        )


def test_calculate_benchmark_returns_notes_weight_sum_deviation_and_zero_weight_local_fx_rows():
    result = calculate_benchmark_returns(
        [
            BenchmarkComponentObservation(
                component_id="IDX_A",
                perf_date=date(2026, 1, 2),
                weight_bop=0.0,
                component_return=0.0,
                component_return_local=0.01,
                component_return_fx=-0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_B",
                perf_date=date(2026, 1, 2),
                weight_bop=0.8,
                component_return=0.016,
                component_return_local=0.02,
                component_return_fx=0.0,
            ),
        ]
    )

    daily_row = result.daily_returns_df.to_dict(orient="records")[0]
    assert float(daily_row["weight_sum"]) == pytest.approx(0.8)
    assert float(daily_row["benchmark_return"]) == pytest.approx(0.0128)
    assert float(daily_row["benchmark_return_local"]) == pytest.approx(0.02)
    assert float(daily_row["benchmark_return_fx"]) == pytest.approx(0.0)
    assert result.max_weight_sum_deviation == pytest.approx(0.2)
    assert result.notes == ["Benchmark component weights do not sum exactly to 1.0 on every date."]


def test_benchmark_return_points_to_dataframe_rejects_empty_and_duplicate_vendor_dates():
    with pytest.raises(ValueError, match="must not be empty"):
        benchmark_return_points_to_dataframe([])

    with pytest.raises(ValueError, match="Duplicate benchmark_return_points"):
        benchmark_return_points_to_dataframe(
            [
                BenchmarkReturnPoint(perf_date=date(2026, 1, 2), benchmark_return=0.012),
                BenchmarkReturnPoint(perf_date=date(2026, 1, 2), benchmark_return=-0.004),
            ]
        )
