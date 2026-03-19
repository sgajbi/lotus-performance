from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input


class _StatefulInputServiceStub:
    async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
        return (
            200,
            {
                "benchmark_id": "BMK_1",
                "benchmark_currency": "USD",
                "components": [
                    {
                        "index_id": "IDX_USD",
                        "composition_weight": "0.6",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": "2026-01-31",
                    },
                    {
                        "index_id": "IDX_EUR",
                        "composition_weight": "0.4",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": "2026-01-31",
                    },
                ],
            },
        )

    async def get_index_price_series(self, **kwargs):  # noqa: ARG002
        index_id = kwargs["index_id"]
        if index_id == "IDX_USD":
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2026-01-02", "index_price": "102", "series_currency": "USD"},
                        {"series_date": "2026-01-03", "index_price": "103.02", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )
        if index_id == "IDX_EUR":
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "index_price": "100", "series_currency": "EUR"},
                        {"series_date": "2026-01-02", "index_price": "101", "series_currency": "EUR"},
                        {"series_date": "2026-01-03", "index_price": "101.505", "series_currency": "EUR"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )
        return 404, {"detail": "missing"}

    async def get_benchmark_market_series(self, **kwargs):  # noqa: ARG002
        return (
            200,
            {
                "component_series": [],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )

    async def get_fx_rates(self, **kwargs):  # noqa: ARG002
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-01-01", "fx_rate": "1.20"},
                    {"series_date": "2026-01-02", "fx_rate": "1.212"},
                    {"series_date": "2026-01-03", "fx_rate": "1.21806"},
                ],
                "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
            },
        )

    async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
        return (
            200,
            {
                "points": [
                    {"series_date": "2026-01-02", "benchmark_return": "0.0100"},
                    {"series_date": "2026-01-03", "benchmark_return": "0.0110"},
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            },
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_calculates_fx_normalized_component_returns():
    result = await build_stateful_benchmark_input(
        stateful_input_service=_StatefulInputServiceStub(),
        calculation_id=uuid4(),
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
        return_source=BenchmarkReturnSource.CALCULATED,
    )

    assert result.benchmark_currency == "USD"
    assert len(result.component_observations) == 4
    eur_day_one = next(
        observation
        for observation in result.component_observations
        if observation.component_id == "IDX_EUR" and observation.date == date(2026, 1, 2)
    )
    assert eur_day_one.component_return == pytest.approx(0.0201)
    assert eur_day_one.component_currency == "EUR"
    assert eur_day_one.component_return_local == pytest.approx(0.01)
    assert eur_day_one.component_return_fx == pytest.approx(0.01)
    assert result.source_details["benchmark_components"] == 2
    assert result.source_details["fx_pair_count"] == 1
    assert result.source_details["fx_chunk_count"] == 2
    assert result.source_details["fx_page_count"] == 3


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_supports_explicit_vendor_series_mode():
    result = await build_stateful_benchmark_input(
        stateful_input_service=_StatefulInputServiceStub(),
        calculation_id=uuid4(),
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
        return_source=BenchmarkReturnSource.VENDOR_SERIES,
    )

    assert result.component_observations == []
    assert [point.benchmark_return for point in result.benchmark_return_points] == [0.01, 0.011]


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_rejects_window_outside_effective_composition():
    class _InvalidDefinitionStub(_StatefulInputServiceStub):
        async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
            status_code, payload = await super().get_benchmark_definition()
            payload["components"][0]["composition_effective_from"] = "2026-01-03"
            return status_code, payload

    with pytest.raises(HTTPException, match="single effective lotus-core composition segment"):
        await build_stateful_benchmark_input(
            stateful_input_service=_InvalidDefinitionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_rejects_duplicate_component_ids():
    class _DuplicateComponentStub(_StatefulInputServiceStub):
        async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
            return (
                200,
                {
                    "benchmark_id": "BMK_1",
                    "benchmark_currency": "USD",
                    "components": [
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "0.6",
                            "composition_effective_from": "2026-01-01",
                            "composition_effective_to": "2026-01-31",
                        },
                        {
                            "index_id": "IDX_USD",
                            "composition_weight": "0.4",
                            "composition_effective_from": "2026-01-01",
                            "composition_effective_to": "2026-01-31",
                        },
                    ],
                },
            )

    with pytest.raises(HTTPException, match="duplicate component index_id=IDX_USD"):
        await build_stateful_benchmark_input(
            stateful_input_service=_DuplicateComponentStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )
