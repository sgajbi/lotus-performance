from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.services.stateful_benchmark_input_service import (
    BenchmarkCompositionSegment,
    _active_component_segments_for_date,
    _benchmark_return_point_from_payload_point,
    _benchmark_return_points_from_payload,
    _build_component_observation,
    _build_component_observations,
    _build_normalized_component_series,
    _component_price_series_points,
    _composition_segment_overlaps_window,
    _composition_segment_required_fields,
    _fx_rate_map_from_payload,
    _load_benchmark_definition_currency,
    _load_component_price_series,
    _load_fx_maps_for_components,
    _normalize_price_to_benchmark_currency,
    _normalized_component_price_point_from_payload,
    _normalized_price_maps_for_component,
    _parse_composition_window,
    _previous_normalized_component_price,
    _required_fx_pairs_for_components,
    build_stateful_benchmark_input,
)
from app.services.stateful_input_service import RetrievalMetadata


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


def test_benchmark_return_points_from_payload_projects_valid_points_only():
    points = _benchmark_return_points_from_payload(
        {
            "points": [
                {"series_date": "2026-01-02", "benchmark_return": "0.0100"},
                {"series_date": "2026-01-03", "benchmark_return": Decimal("0.0110")},
                {"series_date": "2026-01-04"},
                {"benchmark_return": "0.0120"},
                "ignored",
            ]
        }
    )

    assert [(point.perf_date, point.benchmark_return) for point in points] == [
        (date(2026, 1, 2), 0.01),
        (date(2026, 1, 3), 0.011),
    ]


def test_benchmark_return_point_from_payload_point_projects_valid_point_only():
    point = _benchmark_return_point_from_payload_point(
        {"series_date": "2026-01-02", "benchmark_return": Decimal("0.0100")}
    )

    assert point is not None
    assert point.perf_date == date(2026, 1, 2)
    assert point.benchmark_return == 0.01
    assert _benchmark_return_point_from_payload_point("ignored") is None
    assert _benchmark_return_point_from_payload_point({"series_date": "2026-01-02"}) is None
    assert _benchmark_return_point_from_payload_point({"benchmark_return": "0.0100"}) is None


def test_benchmark_return_points_from_payload_requires_points_list():
    with pytest.raises(HTTPException, match="missing points list"):
        _benchmark_return_points_from_payload({"points": None})


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_rejects_uncovered_composition_dates():
    class _InvalidCompositionStub(_StatefulInputServiceStub):
        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            status_code, payload = await super().get_benchmark_composition_window(**kwargs)
            payload["segments"] = [
                segment for segment in payload["segments"] if segment["composition_effective_from"] != "2026-01-03"
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


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_requires_benchmark_currency_for_vendor_series():
    class _MissingCurrencyDefinitionStub(_StatefulInputServiceStub):
        async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": "BMK_1", "benchmark_currency": ""}

    with pytest.raises(HTTPException, match="missing benchmark_currency"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingCurrencyDefinitionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )


@pytest.mark.asyncio
async def test_load_benchmark_definition_currency_maps_upstream_failure_to_source_unavailable():
    class _UnavailableDefinitionStub(_StatefulInputServiceStub):
        async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "unavailable"}

    with pytest.raises(HTTPException) as exc:
        await _load_benchmark_definition_currency(
            stateful_input_service=_UnavailableDefinitionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "benchmark definition source unavailable (503)."


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_requires_consistent_component_currency_series():
    class _MixedCurrencyIndexStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            if kwargs["index_id"] != "IDX_EUR":
                return await super().get_index_price_series(**kwargs)
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "index_price": "100", "series_currency": "EUR"},
                        {"series_date": "2026-01-02", "index_price": "101", "series_currency": "USD"},
                        {"series_date": "2026-01-03", "index_price": "101.505", "series_currency": "EUR"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )

    with pytest.raises(HTTPException, match="exactly one series_currency"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MixedCurrencyIndexStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_requires_fx_for_non_benchmark_currency_components():
    class _MissingFxPointStub(_StatefulInputServiceStub):
        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            status_code, payload = await super().get_fx_rates(**kwargs)
            payload["points"] = [point for point in payload["points"] if point["series_date"] != "2026-01-03"]
            return status_code, payload

    with pytest.raises(HTTPException, match="Missing FX rate for EUR/USD on 2026-01-03"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingFxPointStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_requires_non_zero_previous_normalized_price():
    class _ZeroPreviousPriceStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            if kwargs["index_id"] != "IDX_USD":
                return await super().get_index_price_series(**kwargs)
            return (
                200,
                {
                    "points": [
                        {"series_date": "2026-01-01", "index_price": "0", "series_currency": "USD"},
                        {"series_date": "2026-01-02", "index_price": "102", "series_currency": "USD"},
                        {"series_date": "2026-01-03", "index_price": "103.02", "series_currency": "USD"},
                    ],
                    "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
                },
            )

    with pytest.raises(HTTPException, match="Normalized benchmark price is zero for component IDX_USD"):
        await build_stateful_benchmark_input(
            stateful_input_service=_ZeroPreviousPriceStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_surfaces_missing_vendor_definition_and_series_payloads():
    class _MissingVendorDefinitionStub(_StatefulInputServiceStub):
        async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "missing"}

    class _UnavailableVendorDefinitionStub(_StatefulInputServiceStub):
        async def get_benchmark_definition(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "unavailable"}

    class _MissingVendorSeriesStub(_StatefulInputServiceStub):
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "missing"}

    class _UnavailableVendorSeriesStub(_StatefulInputServiceStub):
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "unavailable"}

    class _MissingVendorPointsStub(_StatefulInputServiceStub):
        async def get_benchmark_return_series(self, **kwargs):  # noqa: ARG002
            return 200, {"retrieval_metadata": {"chunk_count": 1, "page_count": 1}}

    with pytest.raises(HTTPException, match="No benchmark definition found"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingVendorDefinitionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )

    with pytest.raises(HTTPException, match="definition source unavailable"):
        await build_stateful_benchmark_input(
            stateful_input_service=_UnavailableVendorDefinitionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )

    with pytest.raises(HTTPException, match="No benchmark return series found"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingVendorSeriesStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )

    with pytest.raises(HTTPException, match="return-series source unavailable"):
        await build_stateful_benchmark_input(
            stateful_input_service=_UnavailableVendorSeriesStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )

    with pytest.raises(HTTPException, match="missing points list"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingVendorPointsStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.VENDOR_SERIES,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_surfaces_missing_composition_and_index_series_payloads():
    class _MissingCompositionStub(_StatefulInputServiceStub):
        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "missing"}

    class _UnavailableCompositionStub(_StatefulInputServiceStub):
        async def get_benchmark_composition_window(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "unavailable"}

    class _MissingIndexPayloadStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return 200, {"retrieval_metadata": {"chunk_count": 1, "page_count": 1}}

    with pytest.raises(HTTPException, match="No benchmark composition window found"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingCompositionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )

    with pytest.raises(HTTPException, match="composition-window source unavailable"):
        await build_stateful_benchmark_input(
            stateful_input_service=_UnavailableCompositionStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )

    with pytest.raises(HTTPException, match="payload missing points for benchmark component IDX_EUR"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingIndexPayloadStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


@pytest.mark.asyncio
async def test_build_stateful_benchmark_input_rejects_component_series_without_prior_or_matching_dates():
    class _MissingPriorDateStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            status_code, payload = await super().get_index_price_series(**kwargs)
            payload["points"] = [point for point in payload["points"] if point["series_date"] != "2026-01-01"]
            return status_code, payload

    class _MismatchedCoverageStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            status_code, payload = await super().get_index_price_series(**kwargs)
            if kwargs["index_id"] == "IDX_GBP":
                payload["points"] = [point for point in payload["points"] if point["series_date"] != "2026-01-03"]
            return status_code, payload

    with pytest.raises(HTTPException, match="requires a prior normalized price before 2026-01-02"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MissingPriorDateStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )

    with pytest.raises(HTTPException, match="does not cover the same date set as peer components"):
        await build_stateful_benchmark_input(
            stateful_input_service=_MismatchedCoverageStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
            return_source=BenchmarkReturnSource.CALCULATED,
        )


def test_parse_composition_window_requires_currency_and_usable_segments():
    with pytest.raises(HTTPException, match="missing benchmark_currency"):
        _parse_composition_window(
            benchmark_id="BMK_1",
            composition_window={"benchmark_currency": "", "segments": []},
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="missing segments"):
        _parse_composition_window(
            benchmark_id="BMK_1",
            composition_window={"benchmark_currency": "USD", "segments": []},
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="missing index_id, composition_weight, or composition_effective_from"):
        _parse_composition_window(
            benchmark_id="BMK_1",
            composition_window={
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX_BAD",
                        "composition_effective_from": "2026-01-01",
                    }
                ],
            },
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="missing usable segments"):
        _parse_composition_window(
            benchmark_id="BMK_1",
            composition_window={
                "benchmark_currency": "USD",
                "segments": [
                    "skip-me",
                    {
                        "index_id": "IDX_OLD",
                        "composition_weight": "1.0",
                        "composition_effective_from": "2025-01-01",
                        "composition_effective_to": "2025-01-31",
                    },
                ],
            },
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 3),
        )


def test_parse_composition_window_filters_and_sorts_usable_segments():
    benchmark_currency, segments = _parse_composition_window(
        benchmark_id="BMK_1",
        composition_window={
            "benchmark_currency": "USD",
            "segments": [
                {
                    "index_id": "IDX_OLD",
                    "composition_weight": "1.0",
                    "composition_effective_from": "2025-01-01",
                    "composition_effective_to": "2025-12-31",
                },
                {
                    "index_id": "IDX_B",
                    "composition_weight": "0.4",
                    "composition_effective_from": "2026-01-02",
                    "composition_effective_to": "2026-01-03",
                },
                {
                    "index_id": "IDX_A",
                    "composition_weight": "0.6",
                    "composition_effective_from": "2026-01-01",
                    "composition_effective_to": None,
                },
            ],
        },
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
    )

    assert benchmark_currency == "USD"
    assert [segment.index_id for segment in segments] == ["IDX_A", "IDX_B"]
    assert segments[0].composition_weight == Decimal("0.6")
    assert segments[1].composition_effective_to == date(2026, 1, 3)


def test_composition_segment_required_fields_project_values_and_reject_missing_fields():
    assert _composition_segment_required_fields(
        {
            "index_id": "IDX_A",
            "composition_weight": "0.6",
            "composition_effective_from": "2026-01-01",
        }
    ) == ("IDX_A", "0.6", "2026-01-01")

    with pytest.raises(HTTPException, match="missing index_id, composition_weight, or composition_effective_from"):
        _composition_segment_required_fields(
            {
                "index_id": "IDX_A",
                "composition_effective_from": "2026-01-01",
            }
        )
    with pytest.raises(HTTPException, match="missing index_id, composition_weight, or composition_effective_from"):
        _composition_segment_required_fields(
            {
                "index_id": 123,
                "composition_weight": "0.6",
                "composition_effective_from": "2026-01-01",
            }
        )


def test_composition_segment_overlaps_window_policy():
    assert _composition_segment_overlaps_window(
        effective_from=date(2026, 1, 1),
        effective_to=None,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
    )
    assert _composition_segment_overlaps_window(
        effective_from=date(2026, 1, 3),
        effective_to=date(2026, 1, 3),
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
    )
    assert not _composition_segment_overlaps_window(
        effective_from=date(2026, 1, 4),
        effective_to=None,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
    )
    assert not _composition_segment_overlaps_window(
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 1, 1),
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 3),
    )


def test_required_fx_pairs_for_components_dedupes_non_benchmark_currencies():
    pairs = _required_fx_pairs_for_components(
        component_price_series={
            "IDX_USD": {"series_currency": "USD"},
            "IDX_EUR": {"series_currency": "EUR"},
            "IDX_EUR_2": {"series_currency": "EUR"},
            "IDX_GBP": {"series_currency": "GBP"},
            "IDX_MISSING": {},
        },
        benchmark_currency="USD",
    )

    assert pairs == {("EUR", "USD"), ("GBP", "USD")}


def test_component_price_series_points_filters_dict_points_and_rejects_missing_or_empty_payloads():
    assert _component_price_series_points(
        index_id="IDX_USD",
        series_payload={"points": [{"series_date": "2026-01-01"}, "bad"]},
    ) == [{"series_date": "2026-01-01"}]

    with pytest.raises(HTTPException, match="payload missing points"):
        _component_price_series_points(index_id="IDX_USD", series_payload={})

    with pytest.raises(HTTPException, match="payload empty"):
        _component_price_series_points(index_id="IDX_USD", series_payload={"points": ["bad"]})


@pytest.mark.asyncio
async def test_load_component_price_series_surfaces_404_503_and_empty_payloads():
    class _MissingSeriesStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return 404, {"detail": "missing"}

    class _UnavailableSeriesStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "down"}

    class _EmptySeriesStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return 200, {"points": [], "retrieval_metadata": {"chunk_count": 1, "page_count": 1}}

    class _MissingPointsSeriesStub(_StatefulInputServiceStub):
        async def get_index_price_series(self, **kwargs):  # noqa: ARG002
            return 200, {"retrieval_metadata": {"chunk_count": 1, "page_count": 1}}

    with pytest.raises(HTTPException, match="No index price series found"):
        await _load_component_price_series(
            stateful_input_service=_MissingSeriesStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            component_ids=["IDX_USD"],
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="source unavailable"):
        await _load_component_price_series(
            stateful_input_service=_UnavailableSeriesStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            component_ids=["IDX_USD"],
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="payload empty"):
        await _load_component_price_series(
            stateful_input_service=_EmptySeriesStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            component_ids=["IDX_USD"],
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="payload missing points"):
        await _load_component_price_series(
            stateful_input_service=_MissingPointsSeriesStub(),
            calculation_id=uuid4(),
            benchmark_id="BMK_1",
            component_ids=["IDX_USD"],
            as_of_date=date(2026, 1, 3),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )


@pytest.mark.asyncio
async def test_load_fx_maps_for_components_handles_empty_pairs_and_payload_errors():
    component_price_series = {
        "IDX_USD": {
            "points": [{"series_date": "2026-01-01", "index_price": "100", "series_currency": "USD"}],
            "series_currency": "USD",
        }
    }

    fx_maps, retrieval_metadata = await _load_fx_maps_for_components(
        stateful_input_service=_StatefulInputServiceStub(),
        calculation_id=uuid4(),
        component_price_series=component_price_series,
        benchmark_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    )

    assert fx_maps == {}
    assert retrieval_metadata == RetrievalMetadata(chunk_count=0, page_count=0)

    class _UnavailableFxStub(_StatefulInputServiceStub):
        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "down"}

    class _MissingFxPointsStub(_StatefulInputServiceStub):
        async def get_fx_rates(self, **kwargs):  # noqa: ARG002
            return 200, {"retrieval_metadata": {"chunk_count": 1, "page_count": 1}}

    non_benchmark_component_series = {
        "IDX_EUR": {
            "points": [{"series_date": "2026-01-01", "index_price": "100", "series_currency": "EUR"}],
            "series_currency": "EUR",
        }
    }

    with pytest.raises(HTTPException, match="fx rate source unavailable"):
        await _load_fx_maps_for_components(
            stateful_input_service=_UnavailableFxStub(),
            calculation_id=uuid4(),
            component_price_series=non_benchmark_component_series,
            benchmark_currency="USD",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="fx rate payload missing points"):
        await _load_fx_maps_for_components(
            stateful_input_service=_MissingFxPointsStub(),
            calculation_id=uuid4(),
            component_price_series=non_benchmark_component_series,
            benchmark_currency="USD",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
        )


def test_fx_rate_map_from_payload_projects_valid_rates_only():
    assert _fx_rate_map_from_payload(
        fx_payload={
            "points": [
                {"series_date": "2026-01-02", "fx_rate": "1.20"},
                {"series_date": "2026-01-03", "fx_rate": Decimal("1.21")},
                {"series_date": "2026-01-04"},
                {"fx_rate": "1.22"},
                "ignored",
            ]
        },
        from_currency="EUR",
        to_currency="USD",
    ) == {
        date(2026, 1, 2): Decimal("1.20"),
        date(2026, 1, 3): Decimal("1.21"),
    }


def test_fx_rate_map_from_payload_requires_points_list():
    with pytest.raises(HTTPException, match="fx rate payload missing points for EUR/USD"):
        _fx_rate_map_from_payload(
            fx_payload={"points": None},
            from_currency="EUR",
            to_currency="USD",
        )


def test_active_component_segments_for_date_sorts_active_segments_and_rejects_gaps():
    segments = [
        BenchmarkCompositionSegment(
            index_id="IDX_B",
            composition_weight=Decimal("0.4"),
            composition_effective_from=date(2026, 1, 1),
            composition_effective_to=None,
        ),
        BenchmarkCompositionSegment(
            index_id="IDX_A",
            composition_weight=Decimal("0.6"),
            composition_effective_from=date(2026, 1, 2),
            composition_effective_to=date(2026, 1, 5),
        ),
    ]

    assert [
        segment.index_id
        for segment in _active_component_segments_for_date(
            component_segments=segments,
            point_date=date(2026, 1, 3),
        )
    ] == ["IDX_A", "IDX_B"]

    with pytest.raises(HTTPException, match="missing active segments for 2025-12-31"):
        _active_component_segments_for_date(
            component_segments=segments,
            point_date=date(2025, 12, 31),
        )


def test_build_component_observations_surfaces_missing_active_segments_and_payloads():
    normalized_component_series = {
        "IDX_USD": {
            "points": [
                {"series_date": "2026-01-01", "index_price": "100", "series_currency": "USD"},
                {"series_date": "2026-01-02", "index_price": "101", "series_currency": "USD"},
            ],
            "series_currency": "USD",
        }
    }

    with pytest.raises(HTTPException, match="missing active segments"):
        _build_component_observations(
            benchmark_id="BMK_1",
            component_price_series=normalized_component_series,
            component_segments=[],
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 2),
            requested_end_date=date(2026, 1, 2),
        )

    with pytest.raises(HTTPException, match="Missing index price-series payload"):
        _build_component_observations(
            benchmark_id="BMK_1",
            component_price_series=normalized_component_series,
            component_segments=[
                BenchmarkCompositionSegment(
                    index_id="IDX_EUR",
                    composition_weight=1,
                    composition_effective_from=date(2026, 1, 1),
                    composition_effective_to=None,
                )
            ],
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 2),
            requested_end_date=date(2026, 1, 2),
        )


def test_build_component_observations_detects_incomplete_market_coverage_and_empty_requested_window():
    component_price_series = {
        "IDX_USD": {
            "points": [
                {"series_date": "2026-01-01", "index_price": "100", "series_currency": "USD"},
                {"series_date": "2026-01-02", "index_price": "101", "series_currency": "USD"},
            ],
            "series_currency": "USD",
        }
    }

    with pytest.raises(HTTPException, match="missing 2026-01-03"):
        _build_component_observations(
            benchmark_id="BMK_1",
            component_price_series=component_price_series,
            component_segments=[
                BenchmarkCompositionSegment(
                    index_id="IDX_USD",
                    composition_weight=Decimal("1"),
                    composition_effective_from=date(2026, 1, 1),
                    composition_effective_to=None,
                )
            ],
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 3),
            requested_end_date=date(2026, 1, 3),
        )

    with pytest.raises(HTTPException, match="No normalized benchmark observations available"):
        _build_component_observations(
            benchmark_id="BMK_1",
            component_price_series=component_price_series,
            component_segments=[
                BenchmarkCompositionSegment(
                    index_id="IDX_USD",
                    composition_weight=Decimal("1"),
                    composition_effective_from=date(2026, 1, 1),
                    composition_effective_to=None,
                )
            ],
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 4),
            requested_end_date=date(2026, 1, 3),
        )


def test_build_component_observation_projects_local_fx_and_total_returns():
    observation = _build_component_observation(
        benchmark_id="BMK_1",
        segment=BenchmarkCompositionSegment(
            index_id="IDX_EUR",
            composition_weight=Decimal("0.4"),
            composition_effective_from=date(2026, 1, 1),
            composition_effective_to=None,
        ),
        point_date=date(2026, 1, 2),
        normalized_component_series={
            "IDX_EUR": {
                "normalized_prices": {
                    date(2026, 1, 1): Decimal("110"),
                    date(2026, 1, 2): Decimal("113.322"),
                },
                "local_prices": {
                    date(2026, 1, 1): Decimal("100"),
                    date(2026, 1, 2): Decimal("101"),
                },
                "series_currency": "EUR",
            }
        },
        benchmark_currency="USD",
        fx_map_by_pair={
            ("EUR", "USD"): {
                date(2026, 1, 1): Decimal("1.10"),
                date(2026, 1, 2): Decimal("1.122"),
            }
        },
    )

    assert observation.component_id == "IDX_EUR"
    assert observation.perf_date == date(2026, 1, 2)
    assert observation.component_currency == "EUR"
    assert observation.weight_bop == pytest.approx(0.4)
    assert observation.component_return == pytest.approx(0.0302)
    assert observation.component_return_local == pytest.approx(0.01)
    assert observation.component_return_fx == pytest.approx(0.02)


def test_build_component_observation_projects_zero_fx_for_benchmark_currency_component():
    observation = _build_component_observation(
        benchmark_id="BMK_1",
        segment=BenchmarkCompositionSegment(
            index_id="IDX_USD",
            composition_weight=Decimal("1"),
            composition_effective_from=date(2026, 1, 1),
            composition_effective_to=None,
        ),
        point_date=date(2026, 1, 2),
        normalized_component_series={
            "IDX_USD": {
                "normalized_prices": {
                    date(2026, 1, 1): Decimal("100"),
                    date(2026, 1, 2): Decimal("101"),
                },
                "local_prices": {
                    date(2026, 1, 1): Decimal("100"),
                    date(2026, 1, 2): Decimal("101"),
                },
                "series_currency": "USD",
            }
        },
        benchmark_currency="USD",
        fx_map_by_pair={},
    )

    assert observation.component_return == pytest.approx(0.01)
    assert observation.component_return_local == pytest.approx(0.01)
    assert observation.component_return_fx == 0


def test_previous_normalized_component_price_selects_latest_prior_price():
    assert _previous_normalized_component_price(
        component_id="IDX_USD",
        point_date=date(2026, 1, 3),
        normalized_prices={
            date(2026, 1, 1): Decimal("100"),
            date(2026, 1, 2): Decimal("101"),
            date(2026, 1, 3): Decimal("102"),
        },
    ) == (date(2026, 1, 2), Decimal("101"))


def test_previous_normalized_component_price_rejects_missing_or_zero_prior_price():
    with pytest.raises(HTTPException, match="requires a prior normalized price"):
        _previous_normalized_component_price(
            component_id="IDX_USD",
            point_date=date(2026, 1, 2),
            normalized_prices={date(2026, 1, 2): Decimal("101")},
        )

    with pytest.raises(HTTPException, match="Normalized benchmark price is zero"):
        _previous_normalized_component_price(
            component_id="IDX_USD",
            point_date=date(2026, 1, 2),
            normalized_prices={
                date(2026, 1, 1): Decimal("0"),
                date(2026, 1, 2): Decimal("101"),
            },
        )


def test_build_normalized_component_series_skips_invalid_points_and_rejects_missing_prices():
    with pytest.raises(HTTPException, match="missing index_price"):
        _build_normalized_component_series(
            benchmark_id="BMK_1",
            component_price_series={
                "IDX_USD": {
                    "points": [
                        "skip-me",
                        {"series_date": 123, "index_price": "100", "series_currency": "USD"},
                        {"series_date": "2025-12-31", "index_price": "99", "series_currency": "USD"},
                        {"series_date": "2026-01-02", "index_price": None, "series_currency": "USD"},
                    ],
                    "series_currency": "USD",
                }
            },
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 2),
            requested_end_date=date(2026, 1, 3),
        )


def test_normalized_price_maps_for_component_filters_and_normalizes_requested_dates():
    normalized_prices, local_prices, component_dates = _normalized_price_maps_for_component(
        index_id="IDX_EUR",
        points_raw=[
            "skip-me",
            {"series_date": 123, "index_price": "100"},
            {"series_date": "2026-01-01", "index_price": "100"},
            {"series_date": "2026-01-02", "index_price": "101"},
            {"series_date": "2026-01-04", "index_price": "104"},
        ],
        component_currency="EUR",
        benchmark_currency="USD",
        fx_map_by_pair={
            ("EUR", "USD"): {
                date(2026, 1, 1): Decimal("1.10"),
                date(2026, 1, 2): Decimal("1.12"),
            }
        },
        requested_start_date=date(2026, 1, 2),
        requested_end_date=date(2026, 1, 3),
    )

    assert local_prices == {
        date(2026, 1, 1): Decimal("100"),
        date(2026, 1, 2): Decimal("101"),
    }
    assert normalized_prices == {
        date(2026, 1, 1): Decimal("110.00"),
        date(2026, 1, 2): Decimal("113.12"),
    }
    assert component_dates == {date(2026, 1, 2)}


def test_normalized_component_price_point_from_payload_projects_normalized_point_scope():
    prior_point = _normalized_component_price_point_from_payload(
        index_id="IDX_EUR",
        point={"series_date": "2026-01-01", "index_price": "100"},
        component_currency="EUR",
        benchmark_currency="USD",
        fx_map_by_pair={("EUR", "USD"): {date(2026, 1, 1): Decimal("1.10")}},
        requested_start_date=date(2026, 1, 2),
        requested_end_date=date(2026, 1, 3),
    )
    requested_point = _normalized_component_price_point_from_payload(
        index_id="IDX_EUR",
        point={"series_date": "2026-01-02", "index_price": Decimal("101")},
        component_currency="EUR",
        benchmark_currency="USD",
        fx_map_by_pair={("EUR", "USD"): {date(2026, 1, 2): Decimal("1.12")}},
        requested_start_date=date(2026, 1, 2),
        requested_end_date=date(2026, 1, 3),
    )

    assert prior_point is not None
    assert prior_point.point_date == date(2026, 1, 1)
    assert prior_point.local_price == Decimal("100")
    assert prior_point.normalized_price == Decimal("110.00")
    assert not prior_point.is_requested_date
    assert requested_point is not None
    assert requested_point.normalized_price == Decimal("113.12")
    assert requested_point.is_requested_date


def test_normalized_component_price_point_from_payload_skips_invalid_or_out_of_window_points():
    assert (
        _normalized_component_price_point_from_payload(
            index_id="IDX_EUR",
            point="ignored",
            component_currency="EUR",
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 2),
            requested_end_date=date(2026, 1, 3),
        )
        is None
    )
    assert (
        _normalized_component_price_point_from_payload(
            index_id="IDX_EUR",
            point={"series_date": "2026-01-04", "index_price": "104"},
            component_currency="EUR",
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 2),
            requested_end_date=date(2026, 1, 3),
        )
        is None
    )


def test_normalized_component_price_point_from_payload_rejects_missing_index_price():
    with pytest.raises(HTTPException, match="missing index_price"):
        _normalized_component_price_point_from_payload(
            index_id="IDX_EUR",
            point={"series_date": "2026-01-02", "index_price": None},
            component_currency="EUR",
            benchmark_currency="USD",
            fx_map_by_pair={},
            requested_start_date=date(2026, 1, 2),
            requested_end_date=date(2026, 1, 3),
        )


def test_normalization_and_metadata_helpers_cover_direct_contracts():
    assert (
        _normalize_price_to_benchmark_currency(
            component_currency="USD",
            benchmark_currency="USD",
            price=10,
            price_date=date(2026, 1, 2),
            fx_map_by_pair={},
        )
        == 10
    )

    with pytest.raises(HTTPException, match="Missing FX rate for EUR/USD"):
        _normalize_price_to_benchmark_currency(
            component_currency="EUR",
            benchmark_currency="USD",
            price=10,
            price_date=date(2026, 1, 2),
            fx_map_by_pair={},
        )
