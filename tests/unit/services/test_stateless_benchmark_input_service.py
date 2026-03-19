from datetime import date

import pytest
from fastapi import HTTPException

from app.models.benchmark_analytics_requests import BenchmarkStatelessInput
from app.services.stateless_benchmark_input_service import normalize_stateless_component_observations


def test_normalize_stateless_component_observations_accepts_existing_component_observations():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_observations": [
                {
                    "component_id": "IDX_A",
                    "date": "2026-01-02",
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
                    "date": "2026-01-01",
                    "weight_bop": 0.6,
                    "index_price": 100.0,
                },
                {
                    "component_id": "IDX_A",
                    "date": "2026-01-02",
                    "weight_bop": 0.6,
                    "index_price": 102.0,
                },
                {
                    "component_id": "IDX_B",
                    "date": "2026-01-01",
                    "weight_bop": 0.4,
                    "index_price": 100.0,
                    "component_currency": "EUR",
                    "fx_rate_to_benchmark": 1.2,
                },
                {
                    "component_id": "IDX_B",
                    "date": "2026-01-02",
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
    assert usd_observation["date"] == date(2026, 1, 2)
    assert usd_observation["component_return"] == pytest.approx(0.02)
    assert usd_observation["component_return_fx"] == pytest.approx(0.0)
    assert eur_observation["component_return_local"] == pytest.approx(0.01)
    assert eur_observation["component_return_fx"] == pytest.approx(0.01)
    assert eur_observation["component_return"] == pytest.approx(0.0201)


def test_normalize_stateless_component_observations_rejects_cross_currency_price_points_without_fx():
    stateless_input = BenchmarkStatelessInput.model_validate(
        {
            "benchmark_currency": "USD",
            "component_price_points": [
                {
                    "component_id": "IDX_B",
                    "date": "2026-01-01",
                    "weight_bop": 1.0,
                    "index_price": 100.0,
                    "component_currency": "EUR",
                },
                {
                    "component_id": "IDX_B",
                    "date": "2026-01-02",
                    "weight_bop": 1.0,
                    "index_price": 101.0,
                    "component_currency": "EUR",
                },
            ],
        }
    )

    with pytest.raises(HTTPException, match="require fx_rate_to_benchmark"):
        normalize_stateless_component_observations(
            benchmark_currency="USD",
            stateless_input=stateless_input,
        )
