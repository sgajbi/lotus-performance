from datetime import date

import pytest

from app.models.benchmark_analytics_requests import BenchmarkComponentPricePointInput, BenchmarkStatelessInput
from app.services.stateless_benchmark_input_service import (
    _aligned_component_return_dates,
    _build_price_point_observation,
    _component_observations_from_price_points,
    _cross_currency_price_point_return_components,
    _price_point_return_components,
    normalize_stateless_component_observations,
)
from core.errors import APIUnprocessableEntityError


def test_normalize_stateless_component_observations_accepts_existing_component_observations():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-02",
                    "weight_bop": 1.0,
                    "component_return": 0.01,
                }
            ],
        }
    )

    observations = normalize_stateless_component_observations(
        benchmark_currency="USD",
        stateless_input=stateless_input,
    )

    assert observations[0]["component_id"] == "IDX_A"
    assert observations[0]["component_return"] == pytest.approx(0.01)


def test_normalize_stateless_component_observations_builds_returns_from_price_points():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.6,
                    "index_price": 100.0,
                },
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.6,
                    "index_price": 102.0,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.4,
                    "index_price": 100.0,
                    "component_currency": "EUR",
                    "fx_rate_to_benchmark": 1.2,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.4,
                    "index_price": 101.0,
                    "component_currency": "EUR",
                    "fx_rate_to_benchmark": 1.212,
                },
            ],
        }
    )

    observations = normalize_stateless_component_observations(
        benchmark_currency="USD",
        stateless_input=stateless_input,
    )

    assert len(observations) == 2
    usd_observation = next(item for item in observations if item["component_id"] == "IDX_A")
    eur_observation = next(item for item in observations if item["component_id"] == "IDX_B")
    assert usd_observation["perf_date"] == date(2026, 1, 2)
    assert usd_observation["component_return"] == pytest.approx(0.02)
    assert usd_observation["component_return_fx"] == pytest.approx(0.0)
    assert eur_observation["component_return_local"] == pytest.approx(0.01)
    assert eur_observation["component_return_fx"] == pytest.approx(0.01)
    assert eur_observation["component_return"] == pytest.approx(0.0201)


def test_build_price_point_observation_projects_cross_currency_returns():
    observation = _build_price_point_observation(
        component_id="IDX_EUR",
        benchmark_currency="USD",
        previous_point=BenchmarkComponentPricePointInput(
            component_id="IDX_EUR",
            perf_date=date(2026, 1, 1),
            weight_bop=0.4,
            index_price=100.0,
            component_currency="EUR",
            fx_rate_to_benchmark=1.2,
        ),
        current_point=BenchmarkComponentPricePointInput(
            component_id="IDX_EUR",
            perf_date=date(2026, 1, 2),
            weight_bop=0.4,
            index_price=101.0,
            component_currency="EUR",
            fx_rate_to_benchmark=1.212,
        ),
    )

    assert observation.component_id == "IDX_EUR"
    assert observation.perf_date == date(2026, 1, 2)
    assert observation.component_currency == "EUR"
    assert observation.weight_bop == pytest.approx(0.4)
    assert observation.component_return_local == pytest.approx(0.01)
    assert observation.component_return_fx == pytest.approx(0.01)
    assert observation.component_return == pytest.approx(0.0201)


def test_component_observations_from_price_points_sorts_and_tracks_return_dates():
    observations, component_dates = _component_observations_from_price_points(
        component_id="IDX_A",
        benchmark_currency="USD",
        price_points=[
            BenchmarkComponentPricePointInput(
                component_id="IDX_A",
                perf_date=date(2026, 1, 3),
                weight_bop=0.6,
                index_price=103.0,
            ),
            BenchmarkComponentPricePointInput(
                component_id="IDX_A",
                perf_date=date(2026, 1, 1),
                weight_bop=0.6,
                index_price=100.0,
            ),
            BenchmarkComponentPricePointInput(
                component_id="IDX_A",
                perf_date=date(2026, 1, 2),
                weight_bop=0.6,
                index_price=102.0,
            ),
        ],
    )

    assert [observation.perf_date for observation in observations] == [
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert component_dates == {date(2026, 1, 2), date(2026, 1, 3)}
    assert [observation.component_return for observation in observations] == [
        pytest.approx(0.02),
        pytest.approx(103.0 / 102.0 - 1.0),
    ]


def test_aligned_component_return_dates_sets_and_preserves_expected_coverage():
    component_dates = {date(2026, 1, 2), date(2026, 1, 3)}

    expected_dates = _aligned_component_return_dates(
        component_id="IDX_A",
        component_dates=component_dates,
        expected_component_dates=None,
    )
    matched_dates = _aligned_component_return_dates(
        component_id="IDX_B",
        component_dates={date(2026, 1, 2), date(2026, 1, 3)},
        expected_component_dates=expected_dates,
    )

    assert expected_dates == component_dates
    assert matched_dates == expected_dates


def test_aligned_component_return_dates_rejects_peer_coverage_mismatch():
    with pytest.raises(APIUnprocessableEntityError, match="same derived return-date set"):
        _aligned_component_return_dates(
            component_id="IDX_B",
            component_dates={date(2026, 1, 3)},
            expected_component_dates={date(2026, 1, 2)},
        )


def test_price_point_return_components_resolve_same_and_cross_currency_returns():
    previous_usd = BenchmarkComponentPricePointInput(
        component_id="IDX_USD",
        perf_date=date(2026, 1, 1),
        weight_bop=0.6,
        index_price=100.0,
    )
    current_usd = BenchmarkComponentPricePointInput(
        component_id="IDX_USD",
        perf_date=date(2026, 1, 2),
        weight_bop=0.6,
        index_price=102.0,
    )
    same_currency = _price_point_return_components(
        component_id="IDX_USD",
        benchmark_currency="USD",
        previous_level=100.0,
        current_level=102.0,
        previous_point=previous_usd,
        current_point=current_usd,
    )

    assert same_currency.currency == "USD"
    assert same_currency.total == pytest.approx(0.02)
    assert same_currency.local == pytest.approx(0.02)
    assert same_currency.fx == pytest.approx(0.0)

    previous_eur = BenchmarkComponentPricePointInput(
        component_id="IDX_EUR",
        perf_date=date(2026, 1, 1),
        weight_bop=0.4,
        index_price=100.0,
        component_currency="EUR",
        fx_rate_to_benchmark=1.2,
    )
    current_eur = BenchmarkComponentPricePointInput(
        component_id="IDX_EUR",
        perf_date=date(2026, 1, 2),
        weight_bop=0.4,
        index_price=101.0,
        component_currency="EUR",
        fx_rate_to_benchmark=1.212,
    )
    cross_currency = _price_point_return_components(
        component_id="IDX_EUR",
        benchmark_currency="USD",
        previous_level=100.0,
        current_level=101.0,
        previous_point=previous_eur,
        current_point=current_eur,
    )

    assert cross_currency.currency == "EUR"
    assert cross_currency.local == pytest.approx(0.01)
    assert cross_currency.fx == pytest.approx(0.01)
    assert cross_currency.total == pytest.approx(0.0201)


def test_cross_currency_price_point_return_components_project_fx_decomposition():
    projection = _cross_currency_price_point_return_components(
        component_id="IDX_EUR",
        component_currency="EUR",
        local_return=0.01,
        previous_level=100.0,
        current_level=101.0,
        previous_point=BenchmarkComponentPricePointInput(
            component_id="IDX_EUR",
            perf_date=date(2026, 1, 1),
            weight_bop=0.4,
            index_price=100.0,
            component_currency="EUR",
            fx_rate_to_benchmark=1.2,
        ),
        current_point=BenchmarkComponentPricePointInput(
            component_id="IDX_EUR",
            perf_date=date(2026, 1, 2),
            weight_bop=0.4,
            index_price=101.0,
            component_currency="EUR",
            fx_rate_to_benchmark=1.212,
        ),
    )

    assert projection.currency == "EUR"
    assert projection.local == pytest.approx(0.01)
    assert projection.fx == pytest.approx(0.01)
    assert projection.total == pytest.approx(0.0201)


def test_cross_currency_price_point_return_components_requires_fx_rates():
    with pytest.raises(APIUnprocessableEntityError, match="require fx_rate_to_benchmark"):
        _cross_currency_price_point_return_components(
            component_id="IDX_EUR",
            component_currency="EUR",
            local_return=0.01,
            previous_level=100.0,
            current_level=101.0,
            previous_point=BenchmarkComponentPricePointInput(
                component_id="IDX_EUR",
                perf_date=date(2026, 1, 1),
                weight_bop=0.4,
                index_price=100.0,
                component_currency="EUR",
            ),
            current_point=BenchmarkComponentPricePointInput(
                component_id="IDX_EUR",
                perf_date=date(2026, 1, 2),
                weight_bop=0.4,
                index_price=101.0,
                component_currency="EUR",
                fx_rate_to_benchmark=1.212,
            ),
        )


def test_normalize_stateless_component_observations_rejects_cross_currency_price_points_without_fx():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-01",
                    "weight_bop": 1.0,
                    "index_price": 100.0,
                    "component_currency": "EUR",
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-02",
                    "weight_bop": 1.0,
                    "index_price": 101.0,
                    "component_currency": "EUR",
                },
            ],
        }
    )

    with pytest.raises(APIUnprocessableEntityError, match="require fx_rate_to_benchmark"):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=stateless_input,
        )


def test_normalize_stateless_component_observations_rejects_misaligned_component_return_dates():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.6,
                    "index_price": 100.0,
                },
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.6,
                    "index_price": 102.0,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.4,
                    "index_price": 100.0,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-03",
                    "weight_bop": 0.4,
                    "index_price": 101.0,
                },
            ],
        }
    )

    with pytest.raises(APIUnprocessableEntityError, match="same derived return-date set"):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=stateless_input,
        )


def test_normalize_stateless_component_observations_rejects_duplicate_component_price_point_dates():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.6,
                    "index_price": 100.0,
                },
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.6,
                    "index_price": 101.0,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-01",
                    "weight_bop": 0.4,
                    "index_price": 100.0,
                },
                {
                    "component_id": "IDX_B",
                    "perf_date": "2026-01-02",
                    "weight_bop": 0.4,
                    "index_price": 101.0,
                },
            ],
        }
    )

    with pytest.raises(APIUnprocessableEntityError, match="strictly increasing unique dates"):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=stateless_input,
        )


def test_normalize_stateless_component_observations_requires_any_calculated_input():
    stateless_input = BenchmarkStatelessInput.model_validate({"benchmark_currency": "USD"})

    with pytest.raises(
        APIUnprocessableEntityError,
        match="requires either component_observations or component_price_points",
    ):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=stateless_input,
        )


def test_normalize_stateless_component_observations_rejects_zero_prior_price_and_single_point_series():
    zero_price_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-01",
                    "weight_bop": 1.0,
                    "index_price": 0.0,
                },
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-02",
                    "weight_bop": 1.0,
                    "index_price": 101.0,
                },
            ],
        }
    )
    single_point_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_A",
                    "perf_date": "2026-01-01",
                    "weight_bop": 1.0,
                    "index_price": 100.0,
                }
            ],
        }
    )

    with pytest.raises(APIUnprocessableEntityError, match="require non-zero prior price"):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=zero_price_input,
        )

    with pytest.raises(APIUnprocessableEntityError, match="at least two price points per component are required"):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=single_point_input,
        )
