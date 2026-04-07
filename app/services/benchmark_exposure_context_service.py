from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status

from app.models.benchmark_exposure_context import (
    BenchmarkExposureContextRequest,
    BenchmarkExposureContextResponse,
    BenchmarkExposureGroupingDimension,
    BenchmarkExposureMetadata,
    BenchmarkExposurePageResponse,
    BenchmarkExposureRow,
)
from app.services.stateful_input_service import StatefulInputService
from core.errors import HTTP_422_UNPROCESSABLE


def _as_decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=f"benchmark exposure context payload has invalid {field_name}: {value}",
        ) from exc


async def build_benchmark_exposure_context(
    *,
    request: BenchmarkExposureContextRequest,
    stateful_input_service: StatefulInputService,
) -> BenchmarkExposureContextResponse:
    benchmark_id = await _resolve_benchmark_id(request=request, stateful_input_service=stateful_input_service)
    classification_map = await _classification_map_for_request(
        request=request,
        stateful_input_service=stateful_input_service,
    )
    market_status, market_payload = await stateful_input_service.get_benchmark_market_series(
        calculation_id=request.calculation_id,
        benchmark_id=benchmark_id,
        as_of_date=request.as_of_date,
        start_date=request.window.start_date,
        end_date=request.window.end_date,
        frequency=request.frequency.value.lower(),
        target_currency=request.reporting_currency,
        series_fields=["component_weight"],
    )
    if market_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No benchmark market-series found for benchmark_id={benchmark_id}.",
        )
    if market_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"benchmark market-series source unavailable ({market_status}).",
        )

    rows = _build_exposure_rows(
        component_series=_parse_component_series(market_payload),
        grouping_dimensions=request.grouping_dimensions,
        classification_map=classification_map,
    )
    if not rows:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail=f"No usable benchmark exposure rows returned for benchmark_id={benchmark_id}.",
        )

    paged_rows, next_page_token = _page_rows(
        rows=rows,
        page_size=request.page.page_size,
        page_token=request.page.page_token,
    )
    market_retrieval = _parse_retrieval_metadata(market_payload)
    index_catalog_count = 1 if classification_map else 0

    return BenchmarkExposureContextResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        benchmark_id=benchmark_id,
        benchmark_version=str(request.as_of_date),
        as_of_date=request.as_of_date,
        window=request.window,
        frequency=request.frequency,
        reporting_currency=request.reporting_currency,
        rows=paged_rows,
        page=BenchmarkExposurePageResponse(next_page_token=next_page_token),
        metadata=BenchmarkExposureMetadata(
            calculation_run_id=request.calculation_id,
            generated_at=datetime.now(UTC),
            retrieval_metadata={
                "benchmark_market_series_chunk_count": market_retrieval.get("chunk_count", 0),
                "benchmark_market_series_page_count": market_retrieval.get("page_count", 0),
                "index_catalog_page_count": index_catalog_count,
            },
        ),
    )


async def _resolve_benchmark_id(
    *,
    request: BenchmarkExposureContextRequest,
    stateful_input_service: StatefulInputService,
) -> str:
    if request.benchmark_id:
        return request.benchmark_id
    assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        as_of_date=request.as_of_date,
        reporting_currency=request.reporting_currency,
    )
    if assignment_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="benchmark exposure context requires a benchmark assignment or explicit benchmark_id.",
        )
    if assignment_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"benchmark assignment source unavailable ({assignment_status}).",
        )
    benchmark_id = assignment_payload.get("benchmark_id")
    if not isinstance(benchmark_id, str) or not benchmark_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="benchmark assignment payload missing benchmark_id.",
        )
    return benchmark_id


async def _classification_map_for_request(
    *,
    request: BenchmarkExposureContextRequest,
    stateful_input_service: StatefulInputService,
) -> dict[str, dict[str, str]]:
    if not any(
        dimension in {BenchmarkExposureGroupingDimension.SECTOR, BenchmarkExposureGroupingDimension.ASSET_CLASS}
        for dimension in request.grouping_dimensions
    ):
        return {}
    catalog_status, catalog_payload = await stateful_input_service.get_index_catalog(
        calculation_id=request.calculation_id,
        as_of_date=request.as_of_date,
    )
    if catalog_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"index catalog source unavailable ({catalog_status}).",
        )
    records = catalog_payload.get("records")
    if not isinstance(records, list):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="index catalog payload missing records list.",
        )
    classification_map: dict[str, dict[str, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        index_id = record.get("index_id")
        labels = record.get("classification_labels")
        if isinstance(index_id, str) and isinstance(labels, dict):
            classification_map[index_id] = {str(key): str(value) for key, value in labels.items() if value is not None}
    return classification_map


def _parse_component_series(payload: dict[str, Any]) -> list[dict[str, Any]]:
    component_series = payload.get("component_series")
    if not isinstance(component_series, list):
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="benchmark market-series payload missing component_series list.",
        )
    return [component for component in component_series if isinstance(component, dict)]


def _build_exposure_rows(
    *,
    component_series: list[dict[str, Any]],
    grouping_dimensions: list[BenchmarkExposureGroupingDimension],
    classification_map: dict[str, dict[str, str]],
) -> list[BenchmarkExposureRow]:
    grouped_weights: dict[tuple[str, BenchmarkExposureGroupingDimension, str], Decimal] = {}
    labels: dict[tuple[BenchmarkExposureGroupingDimension, str], str] = {}
    component_ids: dict[tuple[BenchmarkExposureGroupingDimension, str], str | None] = {}

    for component in component_series:
        index_id_raw = component.get("index_id")
        if not isinstance(index_id_raw, str) or not index_id_raw:
            continue
        points = component.get("points")
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            series_date = point.get("series_date")
            if not isinstance(series_date, str):
                continue
            component_weight = point.get("component_weight")
            if component_weight is None:
                continue
            weight = _as_decimal(component_weight, field_name="component_weight")
            for dimension in grouping_dimensions:
                group_key, group_label, component_id = _group_identity(
                    index_id=index_id_raw,
                    grouping_dimension=dimension,
                    classification_map=classification_map,
                )
                grouped_key = (series_date, dimension, group_key)
                grouped_weights[grouped_key] = grouped_weights.get(grouped_key, Decimal("0")) + weight
                labels[(dimension, group_key)] = group_label
                component_ids[(dimension, group_key)] = component_id

    return [
        BenchmarkExposureRow(
            valuation_date=series_date,
            component_id=component_ids.get((dimension, group_key)),
            grouping_dimension=dimension,
            group_key=group_key,
            group_label=labels[(dimension, group_key)],
            weight=weight,
        )
        for (series_date, dimension, group_key), weight in sorted(grouped_weights.items())
    ]


def _group_identity(
    *,
    index_id: str,
    grouping_dimension: BenchmarkExposureGroupingDimension,
    classification_map: dict[str, dict[str, str]],
) -> tuple[str, str, str | None]:
    if grouping_dimension == BenchmarkExposureGroupingDimension.POSITION:
        return index_id, index_id, index_id
    if grouping_dimension == BenchmarkExposureGroupingDimension.SECTOR:
        label = classification_map.get(index_id, {}).get("sector") or "UNKNOWN"
        return f"SECTOR_{label}", label, None
    if grouping_dimension == BenchmarkExposureGroupingDimension.ASSET_CLASS:
        label = classification_map.get(index_id, {}).get("asset_class") or "UNKNOWN"
        return f"ASSET_CLASS_{label}", label, None
    raise HTTPException(
        status_code=HTTP_422_UNPROCESSABLE,
        detail=f"benchmark exposure context does not yet support grouping_dimension={grouping_dimension.value}",
    )


def _page_rows(
    *,
    rows: list[BenchmarkExposureRow],
    page_size: int,
    page_token: str | None,
) -> tuple[list[BenchmarkExposureRow], str | None]:
    try:
        start = int(page_token) if page_token else 0
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="page.page_token must be a numeric offset token returned by lotus-performance.",
        ) from exc
    if start < 0:
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail="page.page_token must be non-negative.",
        )
    end = start + page_size
    next_page_token = str(end) if end < len(rows) else None
    return rows[start:end], next_page_token


def _parse_retrieval_metadata(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("retrieval_metadata")
    if not isinstance(raw, dict):
        return {"chunk_count": 0, "page_count": 0}
    return {
        "chunk_count": int(raw.get("chunk_count", 0) or 0),
        "page_count": int(raw.get("page_count", 0) or 0),
    }
