from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkComponentObservation, BenchmarkReturnPoint
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService


@dataclass(frozen=True)
class StatefulBenchmarkNormalizedInput:
    benchmark_currency: str
    component_observations: list[BenchmarkComponentObservation]
    benchmark_return_points: list[BenchmarkReturnPoint]
    source_details: dict[str, int]


async def build_stateful_benchmark_input(
    *,
    stateful_input_service: StatefulInputService,
    calculation_id: UUID,
    benchmark_id: str,
    as_of_date: date,
    start_date: date,
    end_date: date,
    return_source: BenchmarkReturnSource,
) -> StatefulBenchmarkNormalizedInput:
    definition_status, definition_payload = await stateful_input_service.get_benchmark_definition(
        benchmark_id=benchmark_id,
        as_of_date=as_of_date,
        calculation_id=calculation_id,
    )
    if definition_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No benchmark definition found for benchmark_id={benchmark_id}.",
        )
    if definition_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"benchmark definition source unavailable ({definition_status}).",
        )

    benchmark_currency_raw = definition_payload.get("benchmark_currency")
    if not isinstance(benchmark_currency_raw, str) or not benchmark_currency_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="benchmark definition payload missing benchmark_currency.",
        )
    benchmark_currency = benchmark_currency_raw

    if return_source == BenchmarkReturnSource.VENDOR_SERIES:
        return await _build_stateful_vendor_series_input(
            stateful_input_service=stateful_input_service,
            calculation_id=calculation_id,
            benchmark_id=benchmark_id,
            benchmark_currency=benchmark_currency,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
        )

    _validate_composition_covers_window(
        benchmark_id=benchmark_id,
        benchmark_definition=definition_payload,
        start_date=start_date,
        end_date=end_date,
    )

    component_weights = _parse_component_weights(
        benchmark_id=benchmark_id,
        benchmark_definition=definition_payload,
    )
    component_price_series, retrieval_metadata = await _load_component_price_series(
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
        benchmark_id=benchmark_id,
        component_ids=sorted(component_weights),
        as_of_date=as_of_date,
        start_date=start_date - timedelta(days=1),
        end_date=end_date,
    )
    fx_map_by_pair, fx_retrieval_metadata = await _load_fx_maps_for_components(
        component_price_series=component_price_series,
        benchmark_currency=benchmark_currency,
        start_date=start_date - timedelta(days=1),
        end_date=end_date,
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
    )

    component_observations = _build_component_observations(
        benchmark_id=benchmark_id,
        component_price_series=component_price_series,
        component_weights=component_weights,
        benchmark_currency=benchmark_currency,
        fx_map_by_pair=fx_map_by_pair,
        requested_start_date=start_date,
        requested_end_date=end_date,
    )

    return StatefulBenchmarkNormalizedInput(
        benchmark_currency=benchmark_currency,
        component_observations=component_observations,
        benchmark_return_points=[],
        source_details={
            "benchmark_components": len(component_price_series),
            "component_observations": len(component_observations),
            "benchmark_chunk_count": retrieval_metadata.chunk_count,
            "benchmark_page_count": retrieval_metadata.page_count,
            "fx_pair_count": len(fx_map_by_pair),
            "fx_chunk_count": fx_retrieval_metadata.chunk_count,
            "fx_page_count": fx_retrieval_metadata.page_count,
        },
    )


async def _build_stateful_vendor_series_input(
    *,
    stateful_input_service: StatefulInputService,
    calculation_id: UUID,
    benchmark_id: str,
    benchmark_currency: str,
    as_of_date: date,
    start_date: date,
    end_date: date,
) -> StatefulBenchmarkNormalizedInput:
    return_status, return_payload = await stateful_input_service.get_benchmark_return_series(
        benchmark_id=benchmark_id,
        as_of_date=as_of_date,
        start_date=start_date,
        end_date=end_date,
        frequency="daily",
        calculation_id=calculation_id,
    )
    if return_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No benchmark return series found for benchmark_id={benchmark_id}.",
        )
    if return_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"benchmark return-series source unavailable ({return_status}).",
        )

    points_raw = return_payload.get("points")
    if not isinstance(points_raw, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="benchmark return-series payload missing points list.",
        )
    benchmark_return_points = [
        BenchmarkReturnPoint(
            date=date.fromisoformat(point["series_date"]),
            benchmark_return=float(point["benchmark_return"]),
        )
        for point in points_raw
        if isinstance(point, dict)
        and isinstance(point.get("series_date"), str)
        and point.get("benchmark_return") is not None
    ]
    retrieval_metadata = _parse_retrieval_metadata(return_payload)
    return StatefulBenchmarkNormalizedInput(
        benchmark_currency=benchmark_currency,
        component_observations=[],
        benchmark_return_points=benchmark_return_points,
        source_details={
            "benchmark_return_points": len(benchmark_return_points),
            "benchmark_chunk_count": retrieval_metadata.chunk_count,
            "benchmark_page_count": retrieval_metadata.page_count,
        },
    )


def _validate_composition_covers_window(
    *,
    benchmark_id: str,
    benchmark_definition: dict[str, Any],
    start_date: date,
    end_date: date,
) -> None:
    components_raw = benchmark_definition.get("components")
    if not isinstance(components_raw, list) or not components_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Benchmark definition missing components for benchmark_id={benchmark_id}.",
        )
    for component in components_raw:
        if not isinstance(component, dict):
            continue
        effective_from_raw = component.get("composition_effective_from")
        effective_to_raw = component.get("composition_effective_to")
        if not isinstance(effective_from_raw, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="benchmark definition payload missing composition_effective_from.",
            )
        effective_from = date.fromisoformat(effective_from_raw)
        effective_to = date.fromisoformat(effective_to_raw) if isinstance(effective_to_raw, str) else None
        if effective_from > start_date or (effective_to is not None and effective_to < end_date):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Stateful calculated benchmark input currently requires the requested window to remain "
                    "within a single effective lotus-core composition segment."
                ),
            )


def _parse_component_weights(
    *,
    benchmark_id: str,
    benchmark_definition: dict[str, Any],
) -> dict[str, Decimal]:
    components_raw = benchmark_definition.get("components")
    if not isinstance(components_raw, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Benchmark definition missing components for benchmark_id={benchmark_id}.",
        )
    weights: dict[str, Decimal] = {}
    for component in components_raw:
        if not isinstance(component, dict):
            continue
        index_id = component.get("index_id")
        composition_weight = component.get("composition_weight")
        if not isinstance(index_id, str) or composition_weight is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="benchmark definition payload missing index_id or composition_weight.",
            )
        if index_id in weights:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"benchmark definition payload contains duplicate component index_id={index_id} "
                    f"for benchmark_id={benchmark_id}."
                ),
            )
        weights[index_id] = Decimal(str(composition_weight))
    if not weights:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Benchmark definition missing usable components for benchmark_id={benchmark_id}.",
        )
    return weights


async def _load_component_price_series(
    *,
    stateful_input_service: StatefulInputService,
    calculation_id: UUID,
    benchmark_id: str,
    component_ids: list[str],
    as_of_date: date,
    start_date: date,
    end_date: date,
) -> tuple[dict[str, dict[str, Any]], RetrievalMetadata]:
    responses = await asyncio.gather(
        *[
            stateful_input_service.get_index_price_series(
                index_id=index_id,
                as_of_date=as_of_date,
                start_date=start_date,
                end_date=end_date,
                frequency="daily",
                calculation_id=calculation_id,
            )
            for index_id in component_ids
        ]
    )
    component_price_series: dict[str, dict[str, Any]] = {}
    total_chunk_count = 0
    total_page_count = 0
    for index_id, (series_status, series_payload) in zip(component_ids, responses):
        if series_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No index price series found for benchmark component {index_id}.",
            )
        if series_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"index price-series source unavailable for benchmark component {index_id} ({series_status}).",
            )
        points_raw = series_payload.get("points")
        if not isinstance(points_raw, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"index price-series payload missing points for benchmark component {index_id}.",
            )
        series_points = [point for point in points_raw if isinstance(point, dict)]
        if not series_points:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"index price-series payload empty for benchmark component {index_id}.",
            )
        component_price_series[index_id] = {
            "points": series_points,
            "series_currency": _infer_series_currency(index_id=index_id, points=series_points),
        }
        retrieval_metadata = _parse_retrieval_metadata(series_payload)
        total_chunk_count += retrieval_metadata.chunk_count
        total_page_count += retrieval_metadata.page_count

    return component_price_series, RetrievalMetadata(
        chunk_count=total_chunk_count,
        page_count=total_page_count,
    )


def _infer_series_currency(*, index_id: str, points: list[dict[str, Any]]) -> str:
    currencies = {
        point["series_currency"]
        for point in points
        if isinstance(point.get("series_currency"), str) and point["series_currency"]
    }
    if len(currencies) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"index price-series payload must expose exactly one series_currency for component {index_id}.",
        )
    return next(iter(currencies))


async def _load_fx_maps_for_components(
    *,
    component_price_series: dict[str, dict[str, Any]],
    benchmark_currency: str,
    start_date: date,
    end_date: date,
    stateful_input_service: StatefulInputService,
    calculation_id: UUID,
) -> tuple[dict[tuple[str, str], dict[date, Decimal]], RetrievalMetadata]:
    pairs: set[tuple[str, str]] = set()
    for component_payload in component_price_series.values():
        component_currency = component_payload.get("series_currency")
        if component_currency and component_currency != benchmark_currency:
            pairs.add((component_currency, benchmark_currency))

    fx_maps: dict[tuple[str, str], dict[date, Decimal]] = {}
    total_chunk_count = 0
    total_page_count = 0
    for from_currency, to_currency in sorted(pairs):
        fx_status, fx_payload = await stateful_input_service.get_fx_rates(
            from_currency=from_currency,
            to_currency=to_currency,
            start_date=start_date,
            end_date=end_date,
            calculation_id=calculation_id,
        )
        if fx_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"fx rate source unavailable for {from_currency}/{to_currency} ({fx_status}).",
            )
        points_raw = fx_payload.get("points")
        if not isinstance(points_raw, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"fx rate payload missing points for {from_currency}/{to_currency}.",
            )
        fx_maps[(from_currency, to_currency)] = {
            date.fromisoformat(point["series_date"]): Decimal(str(point["fx_rate"]))
            for point in points_raw
            if isinstance(point, dict)
            and isinstance(point.get("series_date"), str)
            and point.get("fx_rate") is not None
        }
        retrieval_metadata = _parse_retrieval_metadata(fx_payload)
        total_chunk_count += retrieval_metadata.chunk_count
        total_page_count += retrieval_metadata.page_count
    return fx_maps, RetrievalMetadata(
        chunk_count=total_chunk_count,
        page_count=total_page_count,
    )


def _build_component_observations(
    *,
    benchmark_id: str,
    component_price_series: dict[str, dict[str, Any]],
    component_weights: dict[str, Decimal],
    benchmark_currency: str,
    fx_map_by_pair: dict[tuple[str, str], dict[date, Decimal]],
    requested_start_date: date,
    requested_end_date: date,
) -> list[BenchmarkComponentObservation]:
    observations: list[BenchmarkComponentObservation] = []
    expected_dates: set[date] = set()

    for index_id in sorted(component_weights):
        component_payload = component_price_series.get(index_id)
        if component_payload is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing index price-series payload for benchmark component {index_id}.",
            )
        points_raw = component_payload["points"]
        component_currency = component_payload["series_currency"]

        normalized_prices: dict[date, Decimal] = {}
        component_dates: set[date] = set()
        for point in points_raw:
            if not isinstance(point, dict):
                continue
            date_raw = point.get("series_date")
            index_price_raw = point.get("index_price")
            if not isinstance(date_raw, str):
                continue
            point_date = date.fromisoformat(date_raw)
            if point_date < requested_start_date - timedelta(days=1) or point_date > requested_end_date:
                continue
            if index_price_raw is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Index price-series payload missing index_price for {index_id} on {point_date}."
                    ),
                )
            normalized_prices[point_date] = _normalize_price_to_benchmark_currency(
                component_currency=component_currency,
                benchmark_currency=benchmark_currency,
                price=Decimal(str(index_price_raw)),
                price_date=point_date,
                fx_map_by_pair=fx_map_by_pair,
            )
            if requested_start_date <= point_date <= requested_end_date:
                component_dates.add(point_date)

        if not expected_dates:
            expected_dates = component_dates
        elif component_dates != expected_dates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Benchmark market-series coverage is incomplete for benchmark_id={benchmark_id}; "
                    f"component {index_id} does not cover the same date set as peer components."
                ),
            )

        ordered_dates = sorted(component_dates)
        for point_date in ordered_dates:
            previous_dates = [candidate for candidate in normalized_prices if candidate < point_date]
            if not previous_dates:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Benchmark calculated mode requires a prior normalized price before {point_date} "
                        f"for component {index_id}."
                    ),
                )
            previous_date = max(previous_dates)
            previous_price = normalized_prices[previous_date]
            current_price = normalized_prices[point_date]
            if previous_price == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Normalized benchmark price is zero for component {index_id} on {previous_date}.",
                )
            local_previous_price = Decimal(str(next(
                point["index_price"]
                for point in points_raw
                if isinstance(point, dict) and point.get("series_date") == previous_date.isoformat()
            )))
            local_current_price = Decimal(str(next(
                point["index_price"]
                for point in points_raw
                if isinstance(point, dict) and point.get("series_date") == point_date.isoformat()
            )))
            component_return_local = (local_current_price / local_previous_price) - Decimal("1")
            if component_currency == benchmark_currency:
                component_return_fx = Decimal("0")
            else:
                fx_map = fx_map_by_pair[(component_currency, benchmark_currency)]
                component_return_fx = (fx_map[point_date] / fx_map[previous_date]) - Decimal("1")
            component_return = (current_price / previous_price) - Decimal("1")
            observations.append(
                BenchmarkComponentObservation(
                    component_id=index_id,
                    date=point_date,
                    component_currency=component_currency,
                    weight_bop=float(component_weights[index_id]),
                    component_return=float(component_return),
                    component_return_local=float(component_return_local),
                    component_return_fx=float(component_return_fx),
                )
            )

    if not observations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No normalized benchmark observations available for benchmark_id={benchmark_id}.",
        )
    return sorted(observations, key=lambda item: (item.date, item.component_id))


def _normalize_price_to_benchmark_currency(
    *,
    component_currency: str,
    benchmark_currency: str,
    price: Decimal,
    price_date: date,
    fx_map_by_pair: dict[tuple[str, str], dict[date, Decimal]],
) -> Decimal:
    if component_currency == benchmark_currency:
        return price
    pair = (component_currency, benchmark_currency)
    fx_map = fx_map_by_pair.get(pair)
    if fx_map is None or price_date not in fx_map:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing FX rate for {component_currency}/{benchmark_currency} on {price_date}.",
        )
    return price * fx_map[price_date]


def _parse_retrieval_metadata(payload: dict[str, Any]) -> RetrievalMetadata:
    metadata = payload.get("retrieval_metadata")
    if not isinstance(metadata, dict):
        return RetrievalMetadata(chunk_count=0, page_count=0)
    chunk_count = metadata.get("chunk_count", 0)
    page_count = metadata.get("page_count", 0)
    return RetrievalMetadata(
        chunk_count=int(chunk_count) if isinstance(chunk_count, (int, float, str)) else 0,
        page_count=int(page_count) if isinstance(page_count, (int, float, str)) else 0,
    )
