from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.benchmark_exposure_context import (
    BenchmarkExposureContextRequest,
    BenchmarkExposureContextResponse,
    BenchmarkExposureGroupingDimension,
    BenchmarkExposureMetadata,
    BenchmarkExposurePageResponse,
    BenchmarkExposureRow,
)
from app.observability import source_product_correlation_id
from app.services.offset_pagination import slice_offset_page
from app.services.stateful_input_service import StatefulInputService
from app.services.stateful_retrieval_metadata import parse_zero_default_retrieval_metadata
from app.services.stateful_upstream_errors import raise_for_stateful_source_unavailable
from core.errors import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    APINotFoundError,
    APIServiceUnavailableError,
    APIUnprocessableEntityError,
)

_INVALID_OFFSET_PAGE_DETAIL = "page.page_token must be a numeric offset token returned by lotus-performance."
_NEGATIVE_OFFSET_PAGE_DETAIL = "page.page_token must be non-negative."


def _as_decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise APIUnprocessableEntityError(
            f"benchmark exposure context payload has invalid {field_name}: {value}"
        ) from exc


async def build_benchmark_exposure_context(
    *,
    request: BenchmarkExposureContextRequest,
    stateful_input_service: StatefulInputService,
) -> BenchmarkExposureContextResponse:
    benchmark_id = await _resolve_benchmark_id(request=request, stateful_input_service=stateful_input_service)
    component_series, market_payload = await _retrieve_benchmark_component_series(
        request=request,
        benchmark_id=benchmark_id,
        stateful_input_service=stateful_input_service,
    )
    classification_map = await _classification_map_for_request(
        request=request,
        stateful_input_service=stateful_input_service,
        component_series=component_series,
    )
    rows = _build_exposure_rows(
        component_series=component_series,
        grouping_dimensions=request.grouping_dimensions,
        classification_map=classification_map,
    )
    if not rows:
        raise APIUnprocessableEntityError(
            f"No usable benchmark exposure rows returned for benchmark_id={benchmark_id}."
        )

    paged_rows, next_page_token = _page_rows(
        rows=rows,
        page_size=request.page.page_size,
        page_token=request.page.page_token,
    )
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
        metadata=_benchmark_exposure_metadata(
            request=request,
            market_payload=market_payload,
            index_catalog_count=index_catalog_count,
        ),
    )


async def _retrieve_benchmark_component_series(
    *,
    request: BenchmarkExposureContextRequest,
    benchmark_id: str,
    stateful_input_service: StatefulInputService,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    component_series = _component_series_from_market_response(
        benchmark_id=benchmark_id,
        market_status=market_status,
        market_payload=market_payload,
    )
    return component_series, market_payload


def _benchmark_exposure_metadata(
    *,
    request: BenchmarkExposureContextRequest,
    market_payload: dict[str, Any],
    index_catalog_count: int,
) -> BenchmarkExposureMetadata:
    market_retrieval = parse_zero_default_retrieval_metadata(market_payload)
    return BenchmarkExposureMetadata(
        calculation_run_id=request.calculation_id,
        correlation_id=source_product_correlation_id(),
        generated_at=datetime.now(UTC),
        retrieval_metadata={
            "benchmark_market_series_chunk_count": market_retrieval.chunk_count,
            "benchmark_market_series_page_count": market_retrieval.page_count,
            "index_catalog_page_count": index_catalog_count,
        },
    )


def _component_series_from_market_response(
    *,
    benchmark_id: str,
    market_status: int,
    market_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if market_status == HTTP_404_NOT_FOUND:
        raise APINotFoundError(f"No benchmark market-series found for benchmark_id={benchmark_id}.")
    if market_status >= HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(source_label="benchmark market-series", upstream_status=market_status)
    return _parse_component_series(market_payload)


def _benchmark_id_from_assignment_response(*, assignment_status: int, assignment_payload: dict[str, Any]) -> str:
    _raise_for_unusable_assignment_response_status(assignment_status)
    return _benchmark_id_from_assignment_payload(assignment_payload)


def _raise_for_unusable_assignment_response_status(assignment_status: int) -> None:
    if assignment_status == HTTP_404_NOT_FOUND:
        raise APIUnprocessableEntityError(
            "benchmark exposure context requires a benchmark assignment or explicit benchmark_id."
        )
    if assignment_status >= HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(source_label="benchmark assignment", upstream_status=assignment_status)


def _benchmark_id_from_assignment_payload(assignment_payload: dict[str, Any]) -> str:
    benchmark_id = assignment_payload.get("benchmark_id")
    if not isinstance(benchmark_id, str) or not benchmark_id:
        raise APIServiceUnavailableError("benchmark assignment payload missing benchmark_id.")
    return benchmark_id


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
    return _benchmark_id_from_assignment_response(
        assignment_status=assignment_status,
        assignment_payload=assignment_payload,
    )


async def _classification_map_for_request(
    *,
    request: BenchmarkExposureContextRequest,
    stateful_input_service: StatefulInputService,
    component_series: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    if not _requires_index_catalog(request.grouping_dimensions):
        return {}
    index_ids = _index_ids_for_component_series(component_series)
    if not index_ids:
        return {}
    catalog_status, catalog_payload = await stateful_input_service.get_index_catalog(
        calculation_id=request.calculation_id,
        as_of_date=request.as_of_date,
        index_ids=index_ids,
    )
    if catalog_status >= HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(source_label="index catalog", upstream_status=catalog_status)
    return _classification_map_from_catalog_payload(catalog_payload)


def _classification_map_from_catalog_payload(catalog_payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    records = catalog_payload.get("records")
    if not isinstance(records, list):
        raise APIUnprocessableEntityError("index catalog payload missing records list.")
    return _classification_map_from_catalog_records(records)


def _requires_index_catalog(grouping_dimensions: list[BenchmarkExposureGroupingDimension]) -> bool:
    return any(dimension != BenchmarkExposureGroupingDimension.POSITION for dimension in grouping_dimensions)


def _index_ids_for_component_series(component_series: list[dict[str, Any]]) -> list[str]:
    return sorted(set(_iter_component_index_ids(component_series)))


def _iter_component_index_ids(component_series: list[dict[str, Any]]) -> Iterator[str]:
    for component in component_series:
        index_id = component.get("index_id")
        if isinstance(index_id, str) and index_id:
            yield index_id


def _classification_map_from_catalog_records(records: list[Any]) -> dict[str, dict[str, str]]:
    classification_map: dict[str, dict[str, str]] = {}
    for record in records:
        classification = _classification_labels_from_catalog_record(record)
        if classification is None:
            continue
        index_id, labels = classification
        classification_map[index_id] = labels
    return classification_map


def _normalized_classification_labels(labels: dict[Any, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in labels.items() if value is not None}


def _classification_labels_from_catalog_record(record: Any) -> tuple[str, dict[str, str]] | None:
    if not isinstance(record, dict):
        return None
    index_id = record.get("index_id")
    labels = record.get("classification_labels")
    if not isinstance(index_id, str) or not isinstance(labels, dict):
        return None
    return index_id, _normalized_classification_labels(labels)


def _parse_component_series(payload: dict[str, Any]) -> list[dict[str, Any]]:
    component_series = payload.get("component_series")
    if not isinstance(component_series, list):
        raise APIUnprocessableEntityError("benchmark market-series payload missing component_series list.")
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

    for index_id, points in _iter_component_exposure_points(component_series):
        for point in points:
            _accumulate_exposure_point(
                index_id=index_id,
                point=point,
                grouping_dimensions=grouping_dimensions,
                classification_map=classification_map,
                grouped_weights=grouped_weights,
                labels=labels,
                component_ids=component_ids,
            )

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


def _iter_component_exposure_points(component_series: list[dict[str, Any]]) -> Iterator[tuple[str, list[Any]]]:
    for component in component_series:
        exposure_points = _component_exposure_points(component)
        if exposure_points is not None:
            yield exposure_points


def _component_exposure_points(component: dict[str, Any]) -> tuple[str, list[Any]] | None:
    index_id = component.get("index_id")
    if not isinstance(index_id, str) or not index_id:
        return None
    points = component.get("points")
    if not isinstance(points, list):
        return None
    return index_id, points


def _accumulate_exposure_point(
    *,
    index_id: str,
    point: Any,
    grouping_dimensions: list[BenchmarkExposureGroupingDimension],
    classification_map: dict[str, dict[str, str]],
    grouped_weights: dict[tuple[str, BenchmarkExposureGroupingDimension, str], Decimal],
    labels: dict[tuple[BenchmarkExposureGroupingDimension, str], str],
    component_ids: dict[tuple[BenchmarkExposureGroupingDimension, str], str | None],
) -> None:
    point_facts = _exposure_point_series_date_and_weight(point)
    if point_facts is None:
        return
    series_date, weight = point_facts
    for dimension in grouping_dimensions:
        group_key, group_label, component_id = _group_identity(
            index_id=index_id,
            grouping_dimension=dimension,
            classification_map=classification_map,
        )
        grouped_key = (series_date, dimension, group_key)
        grouped_weights[grouped_key] = grouped_weights.get(grouped_key, Decimal("0")) + weight
        labels[(dimension, group_key)] = group_label
        component_ids[(dimension, group_key)] = component_id


def _exposure_point_series_date_and_weight(point: Any) -> tuple[str, Decimal] | None:
    if not isinstance(point, dict):
        return None
    series_date = point.get("series_date")
    if not isinstance(series_date, str):
        return None
    component_weight = point.get("component_weight")
    if component_weight is None:
        return None
    return series_date, _as_decimal(component_weight, field_name="component_weight")


def _group_identity(
    *,
    index_id: str,
    grouping_dimension: BenchmarkExposureGroupingDimension,
    classification_map: dict[str, dict[str, str]],
) -> tuple[str, str, str | None]:
    if grouping_dimension == BenchmarkExposureGroupingDimension.POSITION:
        return index_id, index_id, index_id
    classification_group = _classification_group_for_dimension(grouping_dimension)
    if classification_group is not None:
        label_key, group_prefix = classification_group
        return _classification_group_identity(
            index_id=index_id,
            classification_map=classification_map,
            label_key=label_key,
            group_prefix=group_prefix,
        )
    if grouping_dimension == BenchmarkExposureGroupingDimension.ISSUER:
        return _issuer_group_identity(index_id=index_id, classification_map=classification_map)
    raise APIUnprocessableEntityError(
        f"benchmark exposure context does not yet support grouping_dimension={grouping_dimension.value}"
    )


def _classification_group_for_dimension(
    grouping_dimension: BenchmarkExposureGroupingDimension,
) -> tuple[str, str] | None:
    if grouping_dimension == BenchmarkExposureGroupingDimension.SECTOR:
        return "sector", "SECTOR"
    if grouping_dimension == BenchmarkExposureGroupingDimension.ASSET_CLASS:
        return "asset_class", "ASSET_CLASS"
    return None


def _classification_group_identity(
    *,
    index_id: str,
    classification_map: dict[str, dict[str, str]],
    label_key: str,
    group_prefix: str,
) -> tuple[str, str, None]:
    label = classification_map.get(index_id, {}).get(label_key) or "UNKNOWN"
    return f"{group_prefix}_{label}", label, None


def _issuer_group_identity(
    *,
    index_id: str,
    classification_map: dict[str, dict[str, str]],
) -> tuple[str, str, None]:
    labels = classification_map.get(index_id, {})
    issuer_id = labels.get("issuer_id") or "UNKNOWN"
    issuer_name = labels.get("issuer_name") or issuer_id
    return f"ISSUER_{issuer_id}", issuer_name, None


def _page_rows(
    *,
    rows: list[BenchmarkExposureRow],
    page_size: int,
    page_token: str | None,
) -> tuple[list[BenchmarkExposureRow], str | None]:
    page = slice_offset_page(
        rows,
        page_size=page_size,
        page_token=page_token,
        invalid_token_detail=_INVALID_OFFSET_PAGE_DETAIL,
        negative_token_detail=_NEGATIVE_OFFSET_PAGE_DETAIL,
    )
    return page.items, page.next_page_token
