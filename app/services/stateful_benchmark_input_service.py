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
from app.services.stateful_retrieval_metadata import parse_retrieval_metadata
from app.services.stateful_upstream_errors import raise_for_stateful_source_unavailable
from core.errors import HTTP_422_UNPROCESSABLE


@dataclass(frozen=True)
class StatefulBenchmarkNormalizedInput:
    benchmark_currency: str
    component_observations: list[BenchmarkComponentObservation]
    benchmark_return_points: list[BenchmarkReturnPoint]
    source_details: dict[str, int]


@dataclass(frozen=True)
class BenchmarkCompositionSegment:
    index_id: str
    composition_weight: Decimal
    composition_effective_from: date
    composition_effective_to: date | None


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
    if return_source == BenchmarkReturnSource.VENDOR_SERIES:
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
            raise_for_stateful_source_unavailable(
                source_label="benchmark definition",
                upstream_status=definition_status,
            )

        benchmark_currency_raw = definition_payload.get("benchmark_currency")
        if not isinstance(benchmark_currency_raw, str) or not benchmark_currency_raw:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail="benchmark definition payload missing benchmark_currency.",
            )
        benchmark_currency = benchmark_currency_raw
        return await _build_stateful_vendor_series_input(
            stateful_input_service=stateful_input_service,
            calculation_id=calculation_id,
            benchmark_id=benchmark_id,
            benchmark_currency=benchmark_currency,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
        )

    composition_status, composition_payload = await stateful_input_service.get_benchmark_composition_window(
        benchmark_id=benchmark_id,
        start_date=start_date,
        end_date=end_date,
        calculation_id=calculation_id,
    )
    if composition_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No benchmark composition window found for benchmark_id={benchmark_id}.",
        )
    if composition_status >= status.HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(
            source_label="benchmark composition-window",
            upstream_status=composition_status,
        )

    benchmark_currency, component_segments = _parse_composition_window(
        benchmark_id=benchmark_id,
        composition_window=composition_payload,
        start_date=start_date,
        end_date=end_date,
    )
    component_price_series, retrieval_metadata = await _load_component_price_series(
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
        benchmark_id=benchmark_id,
        component_ids=sorted({segment.index_id for segment in component_segments}),
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
        component_segments=component_segments,
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
            "benchmark_segments": len(component_segments),
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
        raise_for_stateful_source_unavailable(
            source_label="benchmark return-series",
            upstream_status=return_status,
        )

    points_raw = return_payload.get("points")
    if not isinstance(points_raw, list):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="benchmark return-series payload missing points list.",
        )
    benchmark_return_points = [
        BenchmarkReturnPoint(
            perf_date=date.fromisoformat(point["series_date"]),
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


def _parse_composition_window(
    *,
    benchmark_id: str,
    composition_window: dict[str, Any],
    start_date: date,
    end_date: date,
) -> tuple[str, list[BenchmarkCompositionSegment]]:
    benchmark_currency_raw = composition_window.get("benchmark_currency")
    if not isinstance(benchmark_currency_raw, str) or not benchmark_currency_raw:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="benchmark composition-window payload missing benchmark_currency.",
        )

    segments_raw = composition_window.get("segments")
    if not isinstance(segments_raw, list) or not segments_raw:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=f"Benchmark composition window missing segments for benchmark_id={benchmark_id}.",
        )

    segments: list[BenchmarkCompositionSegment] = []
    for segment in segments_raw:
        if not isinstance(segment, dict):
            continue
        index_id = segment.get("index_id")
        composition_weight = segment.get("composition_weight")
        effective_from_raw = segment.get("composition_effective_from")
        effective_to_raw = segment.get("composition_effective_to")
        if not isinstance(index_id, str) or composition_weight is None or not isinstance(effective_from_raw, str):
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=(
                    "benchmark composition-window payload missing index_id, "
                    "composition_weight, or composition_effective_from."
                ),
            )
        effective_from = date.fromisoformat(effective_from_raw)
        effective_to = date.fromisoformat(effective_to_raw) if isinstance(effective_to_raw, str) else None
        if effective_from > end_date or (effective_to is not None and effective_to < start_date):
            continue
        segments.append(
            BenchmarkCompositionSegment(
                index_id=index_id,
                composition_weight=Decimal(str(composition_weight)),
                composition_effective_from=effective_from,
                composition_effective_to=effective_to,
            )
        )

    if not segments:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=f"Benchmark composition window missing usable segments for benchmark_id={benchmark_id}.",
        )

    for point_date in _iter_requested_dates(start_date=start_date, end_date=end_date):
        if not any(_segment_is_active(segment, point_date) for segment in segments):
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=(
                    f"Benchmark composition window does not cover requested date {point_date} "
                    f"for benchmark_id={benchmark_id}."
                ),
            )
    return benchmark_currency_raw, sorted(
        segments,
        key=lambda item: (item.composition_effective_from, item.index_id),
    )


def _iter_requested_dates(*, start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def _segment_is_active(segment: BenchmarkCompositionSegment, point_date: date) -> bool:
    if segment.composition_effective_from > point_date:
        return False
    if segment.composition_effective_to is not None and segment.composition_effective_to < point_date:
        return False
    return True


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
    retrieval_metadata_total = RetrievalMetadata(chunk_count=0, page_count=0)
    for index_id, (series_status, series_payload) in zip(component_ids, responses):
        if series_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No index price series found for benchmark component {index_id}.",
            )
        if series_status >= status.HTTP_400_BAD_REQUEST:
            raise_for_stateful_source_unavailable(
                source_label="index price-series",
                upstream_status=series_status,
                context=f"for benchmark component {index_id}",
            )
        points_raw = series_payload.get("points")
        if not isinstance(points_raw, list):
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=f"index price-series payload missing points for benchmark component {index_id}.",
            )
        series_points = [point for point in points_raw if isinstance(point, dict)]
        if not series_points:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=f"index price-series payload empty for benchmark component {index_id}.",
            )
        component_price_series[index_id] = {
            "points": series_points,
            "series_currency": _infer_series_currency(index_id=index_id, points=series_points),
        }
        retrieval_metadata_total = _add_retrieval_metadata(retrieval_metadata_total, series_payload)

    return component_price_series, retrieval_metadata_total


def _infer_series_currency(*, index_id: str, points: list[dict[str, Any]]) -> str:
    currencies = {
        point["series_currency"]
        for point in points
        if isinstance(point.get("series_currency"), str) and point["series_currency"]
    }
    if len(currencies) != 1:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
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
    retrieval_metadata_total = RetrievalMetadata(chunk_count=0, page_count=0)
    for from_currency, to_currency in sorted(pairs):
        fx_status, fx_payload = await stateful_input_service.get_fx_rates(
            from_currency=from_currency,
            to_currency=to_currency,
            start_date=start_date,
            end_date=end_date,
            calculation_id=calculation_id,
        )
        if fx_status >= status.HTTP_400_BAD_REQUEST:
            raise_for_stateful_source_unavailable(
                source_label="fx rate",
                upstream_status=fx_status,
                context=f"for {from_currency}/{to_currency}",
            )
        points_raw = fx_payload.get("points")
        if not isinstance(points_raw, list):
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=f"fx rate payload missing points for {from_currency}/{to_currency}.",
            )
        fx_maps[(from_currency, to_currency)] = {
            date.fromisoformat(point["series_date"]): Decimal(str(point["fx_rate"]))
            for point in points_raw
            if isinstance(point, dict)
            and isinstance(point.get("series_date"), str)
            and point.get("fx_rate") is not None
        }
        retrieval_metadata_total = _add_retrieval_metadata(retrieval_metadata_total, fx_payload)
    return fx_maps, retrieval_metadata_total


def _build_component_observations(
    *,
    benchmark_id: str,
    component_price_series: dict[str, dict[str, Any]],
    component_segments: list[BenchmarkCompositionSegment],
    benchmark_currency: str,
    fx_map_by_pair: dict[tuple[str, str], dict[date, Decimal]],
    requested_start_date: date,
    requested_end_date: date,
) -> list[BenchmarkComponentObservation]:
    observations: list[BenchmarkComponentObservation] = []
    normalized_component_series = _build_normalized_component_series(
        benchmark_id=benchmark_id,
        component_price_series=component_price_series,
        benchmark_currency=benchmark_currency,
        fx_map_by_pair=fx_map_by_pair,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
    )

    for point_date in _iter_requested_dates(start_date=requested_start_date, end_date=requested_end_date):
        active_segments = [segment for segment in component_segments if _segment_is_active(segment, point_date)]
        if not active_segments:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=f"Benchmark composition window missing active segments for {point_date}.",
            )
        for segment in sorted(active_segments, key=lambda item: item.index_id):
            series_payload = normalized_component_series.get(segment.index_id)
            if series_payload is None:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE,
                    detail=f"Missing index price-series payload for benchmark component {segment.index_id}.",
                )
            normalized_prices = series_payload["normalized_prices"]
            local_prices = series_payload["local_prices"]
            component_currency = series_payload["series_currency"]
            if point_date not in normalized_prices or point_date not in local_prices:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE,
                    detail=(
                        f"Benchmark market-series coverage is incomplete for benchmark_id={benchmark_id}; "
                        f"component {segment.index_id} is missing {point_date}."
                    ),
                )
            previous_dates = [candidate for candidate in normalized_prices if candidate < point_date]
            if not previous_dates:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE,
                    detail=(
                        f"Benchmark calculated mode requires a prior normalized price before {point_date} "
                        f"for component {segment.index_id}."
                    ),
                )
            previous_date = max(previous_dates)
            previous_price = normalized_prices[previous_date]
            current_price = normalized_prices[point_date]
            if previous_price == 0:
                raise HTTPException(
                    status_code=HTTP_422_UNPROCESSABLE,
                    detail=(f"Normalized benchmark price is zero for component {segment.index_id} on {previous_date}."),
                )
            local_previous_price = local_prices[previous_date]
            local_current_price = local_prices[point_date]
            component_return_local = (local_current_price / local_previous_price) - Decimal("1")
            if component_currency == benchmark_currency:
                component_return_fx = Decimal("0")
            else:
                fx_map = fx_map_by_pair[(component_currency, benchmark_currency)]
                component_return_fx = (fx_map[point_date] / fx_map[previous_date]) - Decimal("1")
            component_return = (current_price / previous_price) - Decimal("1")
            observations.append(
                BenchmarkComponentObservation(
                    component_id=segment.index_id,
                    perf_date=point_date,
                    component_currency=component_currency,
                    weight_bop=float(segment.composition_weight),
                    component_return=float(component_return),
                    component_return_local=float(component_return_local),
                    component_return_fx=float(component_return_fx),
                )
            )

    if not observations:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=f"No normalized benchmark observations available for benchmark_id={benchmark_id}.",
        )
    return sorted(observations, key=lambda item: (item.perf_date, item.component_id))


def _build_normalized_component_series(
    *,
    benchmark_id: str,
    component_price_series: dict[str, dict[str, Any]],
    benchmark_currency: str,
    fx_map_by_pair: dict[tuple[str, str], dict[date, Decimal]],
    requested_start_date: date,
    requested_end_date: date,
) -> dict[str, dict[str, Any]]:
    normalized_by_component: dict[str, dict[str, Any]] = {}
    expected_dates: set[date] | None = None
    for index_id, component_payload in component_price_series.items():
        points_raw = component_payload["points"]
        component_currency = component_payload["series_currency"]
        normalized_prices: dict[date, Decimal] = {}
        local_prices: dict[date, Decimal] = {}
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
                    status_code=HTTP_422_UNPROCESSABLE,
                    detail=(
                        f"Index price-series payload missing index_price for benchmark component "
                        f"{index_id} on {point_date}."
                    ),
                )
            local_price = Decimal(str(index_price_raw))
            local_prices[point_date] = local_price
            normalized_prices[point_date] = _normalize_price_to_benchmark_currency(
                component_currency=component_currency,
                benchmark_currency=benchmark_currency,
                price=local_price,
                price_date=point_date,
                fx_map_by_pair=fx_map_by_pair,
            )
            if requested_start_date <= point_date <= requested_end_date:
                component_dates.add(point_date)
        if expected_dates is None:
            expected_dates = component_dates
        elif component_dates != expected_dates:
            raise HTTPException(
                status_code=HTTP_422_UNPROCESSABLE,
                detail=(
                    f"Benchmark market-series coverage is incomplete for benchmark_id={benchmark_id}; "
                    f"component {index_id} does not cover the same date set as peer components."
                ),
            )
        normalized_by_component[index_id] = {
            "normalized_prices": normalized_prices,
            "local_prices": local_prices,
            "series_currency": component_currency,
        }
    return normalized_by_component


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
            status_code=HTTP_422_UNPROCESSABLE,
            detail=f"Missing FX rate for {component_currency}/{benchmark_currency} on {price_date}.",
        )
    return price * fx_map[price_date]


def _parse_retrieval_metadata(payload: dict[str, Any]) -> RetrievalMetadata:
    return parse_retrieval_metadata(
        payload,
        default_chunk_count=0,
        default_page_count=0,
        coerce_numeric_counts=True,
    )


def _add_retrieval_metadata(total: RetrievalMetadata, payload: dict[str, Any]) -> RetrievalMetadata:
    metadata = _parse_retrieval_metadata(payload)
    return RetrievalMetadata(
        chunk_count=total.chunk_count + metadata.chunk_count,
        page_count=total.page_count + metadata.page_count,
    )
