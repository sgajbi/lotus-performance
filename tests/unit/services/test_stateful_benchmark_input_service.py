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
                    }
                ],
            },
        )

    async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
        return (
            200,
            {
                "benchmark_id": "BMK_1",
                "benchmark_currency": "USD",
                "resolved_window": {"start_date": "2026-01-02", "end_date": "2026-01-03"},
                "segments": [
                    {
                        "index_id": "IDX_USD",
                        "composition_weight": "0.6",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": "2026-01-02",
                    },
                    {
                        "index_id": "IDX_EUR",
                        "composition_weight": "0.4",
                        "composition_effective_from": "2026-01-01",
                        "composition_effective_to": "2026-01-02",
                    },
                    {
                        "index_id": "IDX_USD",
                        "composition_weight": "0.5",
                        "composition_effective_from": "2026-01-03",
                        "composition_effective_to": "2026-01-31",
                    },
                    {
                        "index_id": "IDX_EUR",
                        "composition_weight": "0.3",
                        "composition_effective_from": "2026-01-03",
                        "composition_effective_to": "2026-01-31",
                    },
                    {
                        "index_id": "IDX_GBP",
                        "composition_weight": "0.2",
                        "composition_effective_from": "2026-01-03",
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
        if index_id == "IDX_GBP":
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "index_price": "100", "series_currency": "GBP"},
                        {"series_date": "2026-01-02", "index_price": "100.5", "series_currency": "GBP"},
                        {"series_date": "2026-01-03", "index_price": "101.505", "series_currency": "GBP"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )
        return 404, {"detail": "missing"}

    async def get_fx_rates(self, **kwargs):  # noqa: ARG002
        if kwargs["from_currency"] == "GBP":
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "fx_rate": "1.35"},
                        {"series_date": "2026-01-02", "fx_rate": "1.3635"},
                        {"series_date": "2026-01-03", "fx_rate": "1.3703175"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 2},
                },
            )
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
    assert len(result.component_observations) == 5
    eur_day_one = next(
        observation
        for observation in result.component_observations
        if observation.component_id == "IDX_EUR" and observation.perf_date == date(2026, 1, 2)
    )
    assert eur_day_one.component_return == pytest.approx(0.0201)
    assert eur_day_one.component_currency == "EUR"
    assert eur_day_one.component_return_local == pytest.approx(0.01)
    assert eur_day_one.component_return_fx == pytest.approx(0.01)
    gbp_day_two = next(
        observation
        for observation in result.component_observations
        if observation.component_id == "IDX_GBP" and observation.perf_date == date(2026, 1, 3)
    )
    assert gbp_day_two.weight_bop == pytest.approx(0.2)
    assert result.source_details["benchmark_components"] == 3
    assert result.source_details["benchmark_segments"] == 5
    assert result.source_details["fx_pair_count"] == 2
    assert result.source_details["fx_chunk_count"] == 3
    assert result.source_details["fx_page_count"] == 5


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
async def test_build_stateful_benchmark_input_rejects_uncovered_composition_dates():
    class _InvalidCompositionStub(_StatefulInputServiceStub):
        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            status_code, payload = await super().get_benchmark_composition_window(**kwargs)
            payload["segments"] = [
                segment
                for segment in payload["segments"]
                if segment["composition_effective_from"] != "2026-01-03"
            ]
            return status_code, payload

    with pytest.raises(HTTPException, match="does not cover requested date 2026-01-03"):
        await build_stateful_benchmark_input(
            stateful_input_service=_InvalidCompositionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_supports_multi_segment_composition_window():
    result = await build_stateful_benchmark_input(
        stateful_input_service=_StatefulInputServiceStub(),
        calculation_id=uuid4(),
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
        return_source=BenchmarkReturnSource.CALCULATED,
    )

    day_one_weights = {
        observation.component_id: observation.weight_bop
        for observation in result.component_observations
        if observation.perf_date == date(2026, 1, 2)
    }
    day_two_weights = {
        observation.component_id: observation.weight_bop
        for observation in result.component_observations
        if observation.perf_date == date(2026, 1, 3)
    }

    assert day_one_weights == {"IDX_EUR": pytest.approx(0.4), "IDX_USD": pytest.approx(0.6)}
    assert day_two_weights == {
        "IDX_EUR": pytest.approx(0.3),
        "IDX_GBP": pytest.approx(0.2),
        "IDX_USD": pytest.approx(0.5),
    }
