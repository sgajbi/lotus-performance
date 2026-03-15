from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.attribution_requests import AttributionPortfolioData, BenchmarkGroup, InstrumentData
from app.models.stateful_position_inputs import StatefulDimensionName
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_performance_input_service import (
    StatefulPortfolioInput,
    retrieve_stateful_portfolio_input,
)
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points

_SUPPORTED_ATTRIBUTION_GROUPS: set[str] = {"asset_class", "sector", "country"}


@dataclass(frozen=True)
class StatefulAttributionSourceInput:
    portfolio_input: StatefulPortfolioInput
    position_rows: list[dict[str, object]]
    position_retrieval_metadata: RetrievalMetadata
    benchmark_id: str
    benchmark_component_series: list[dict[str, object]]
    benchmark_retrieval_metadata: RetrievalMetadata
    index_records: list[dict[str, object]]
    index_retrieval_metadata: RetrievalMetadata


@dataclass(frozen=True)
class StatefulAttributionNormalizedInput:
    portfolio_data: AttributionPortfolioData
    instruments_data: list[InstrumentData]
    benchmark_groups_data: list[BenchmarkGroup]


async def retrieve_stateful_attribution_source_input(
    *,
    settings: Settings,
    stateful_input_service: StatefulInputService,
    calculation_id,
    portfolio_id: str,
    as_of_date,
    report_start_date,
    report_end_date,
    reporting_currency: str | None,
    consumer_system: str,
    group_by: list[str],
    dimensions: list[StatefulDimensionName],
    include_cash_flows: bool,
    filters: dict[str, object],
    benchmark_id_override: str | None,
) -> StatefulAttributionSourceInput:
    _validate_stateful_group_by(group_by)
    requested_dimensions = sorted(
        {*dimensions, *[dimension for dimension in group_by if dimension in _SUPPORTED_ATTRIBUTION_GROUPS]}
    )

    portfolio_input = await retrieve_stateful_portfolio_input(
        settings=settings,
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        start_date=report_start_date,
        end_date=report_end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
    )

    upstream_status, upstream_payload = await stateful_input_service.get_position_timeseries(
        calculation_id=calculation_id,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        start_date=report_start_date,
        end_date=report_end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
        dimensions=requested_dimensions,
        include_cash_flows=include_cash_flows,
        filters=filters,
    )
    if upstream_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"stateful position timeseries source unavailable ({upstream_status}).",
        )
    position_rows = _parse_position_rows(upstream_payload)

    benchmark_id = benchmark_id_override
    if benchmark_id is None:
        assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            reporting_currency=reporting_currency,
            calculation_id=calculation_id,
        )
        if assignment_status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Stateful attribution input requires a benchmark assignment or explicit stateful_input.benchmark_id.",
            )
        if assignment_status >= status.HTTP_400_BAD_REQUEST:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"benchmark assignment source unavailable ({assignment_status}).",
            )
        benchmark_id_raw = assignment_payload.get("benchmark_id")
        if not isinstance(benchmark_id_raw, str) or not benchmark_id_raw:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="benchmark assignment payload missing benchmark_id.",
            )
        benchmark_id = benchmark_id_raw

    market_status, market_payload = await stateful_input_service.get_benchmark_market_series(
        benchmark_id=benchmark_id,
        as_of_date=as_of_date,
        start_date=report_start_date,
        end_date=report_end_date,
        frequency="daily",
        target_currency=reporting_currency,
        calculation_id=calculation_id,
    )
    if market_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No benchmark market series found for benchmark_id={benchmark_id}.",
        )
    if market_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"benchmark market-series source unavailable ({market_status}).",
        )
    benchmark_component_series = _parse_component_series(market_payload)

    index_status, index_payload = await stateful_input_service.get_index_catalog(
        as_of_date=as_of_date,
        calculation_id=calculation_id,
    )
    if index_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"index catalog source unavailable ({index_status}).",
        )
    index_records = _parse_index_catalog(index_payload)

    return StatefulAttributionSourceInput(
        portfolio_input=portfolio_input,
        position_rows=position_rows,
        position_retrieval_metadata=_parse_retrieval_metadata(upstream_payload),
        benchmark_id=benchmark_id,
        benchmark_component_series=benchmark_component_series,
        benchmark_retrieval_metadata=_parse_retrieval_metadata(market_payload),
        index_records=index_records,
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )


def build_stateful_attribution_input(
    *,
    source_input: StatefulAttributionSourceInput,
    mode: str,
    group_by: list[str],
    metric_basis: str,
    currency_mode: str | None,
    reporting_currency: str | None,
) -> StatefulAttributionNormalizedInput:
    if mode != "by_instrument":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stateful attribution currently supports mode=by_instrument only.",
        )

    normalized_currency_mode = currency_mode or "BASE_ONLY"
    if normalized_currency_mode != "BASE_ONLY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Stateful attribution currently supports currency_mode=BASE_ONLY only until lotus-core exposes "
                "benchmark-local and FX decomposition contracts."
            ),
        )

    portfolio_data = AttributionPortfolioData.model_validate(
        {
            "metric_basis": metric_basis,
            "valuation_points": portfolio_timeseries_to_valuation_points(
                observations=source_input.portfolio_input.observations
            ),
        }
    )
    instruments_data = _build_instruments_data(
        rows=source_input.position_rows,
        reporting_currency=reporting_currency,
    )
    benchmark_groups_data = _build_benchmark_groups(
        group_by=group_by,
        component_series=source_input.benchmark_component_series,
        index_records=source_input.index_records,
    )

    return StatefulAttributionNormalizedInput(
        portfolio_data=portfolio_data,
        instruments_data=instruments_data,
        benchmark_groups_data=benchmark_groups_data,
    )


def _validate_stateful_group_by(group_by: list[str]) -> None:
    unsupported = sorted({dimension for dimension in group_by if dimension not in _SUPPORTED_ATTRIBUTION_GROUPS})
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Stateful attribution supports group_by only for canonical lotus-core attribution dimensions: "
                f"{', '.join(sorted(_SUPPORTED_ATTRIBUTION_GROUPS))}. Unsupported: {', '.join(unsupported)}."
            ),
        )


def _build_instruments_data(
    *,
    rows: list[dict[str, object]],
    reporting_currency: str | None,
) -> list[InstrumentData]:
    positions_by_id: dict[str, list[dict[str, object]]] = {}
    instrument_meta: dict[str, dict[str, object]] = {}
    for row in rows:
        position_id = row.get("position_id")
        valuation_date = row.get("valuation_date")
        if not isinstance(position_id, str) or not isinstance(valuation_date, str):
            continue
        point = _position_row_to_daily_point(row=row, reporting_currency=reporting_currency)
        if point is None:
            continue
        positions_by_id.setdefault(position_id, []).append(point)
        instrument_meta[position_id] = _position_meta_from_row(row)

    return [
        InstrumentData.model_validate(
            {
                "instrument_id": position_id,
                "meta": instrument_meta.get(position_id, {}),
                "valuation_points": positions_by_id[position_id],
            }
        )
        for position_id in sorted(positions_by_id)
    ]


def _build_benchmark_groups(
    *,
    group_by: list[str],
    component_series: list[dict[str, object]],
    index_records: list[dict[str, object]],
) -> list[BenchmarkGroup]:
    labels_by_index: dict[str, dict[str, object]] = {}
    for record in index_records:
        index_id = record.get("index_id")
        labels = record.get("classification_labels")
        if isinstance(index_id, str) and isinstance(labels, dict):
            labels_by_index[index_id] = labels

    grouped: dict[tuple[tuple[str, str], ...], dict[str, dict[str, Decimal]]] = {}
    for component in component_series:
        index_id = component.get("index_id")
        points_raw = component.get("points")
        if not isinstance(index_id, str) or not isinstance(points_raw, list):
            continue
        labels = labels_by_index.get(index_id)
        if labels is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Index catalog missing classification labels for benchmark component {index_id}.",
            )
        group_key = _build_group_key(labels=labels, group_by=group_by, index_id=index_id)
        group_bucket = grouped.setdefault(group_key, {})
        for point in points_raw:
            if not isinstance(point, dict):
                continue
            series_date = point.get("series_date")
            component_weight = point.get("component_weight")
            index_return = point.get("index_return")
            if not isinstance(series_date, str) or component_weight is None or index_return is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Benchmark market-series payload missing index_return or component_weight for {index_id} "
                        f"on {series_date}."
                    ),
                )
            date_bucket = group_bucket.setdefault(
                series_date,
                {
                    "weight_sum": Decimal("0"),
                    "weighted_return_sum": Decimal("0"),
                },
            )
            weight = Decimal(str(component_weight))
            benchmark_return = Decimal(str(index_return))
            date_bucket["weight_sum"] += weight
            date_bucket["weighted_return_sum"] += weight * benchmark_return

    benchmark_groups: list[BenchmarkGroup] = []
    for key_tuple in sorted(grouped):
        observations = []
        for series_date in sorted(grouped[key_tuple]):
            weight_sum = grouped[key_tuple][series_date]["weight_sum"]
            weighted_return_sum = grouped[key_tuple][series_date]["weighted_return_sum"]
            group_return = Decimal("0") if weight_sum == 0 else (weighted_return_sum / weight_sum)
            observations.append(
                {
                    "date": series_date,
                    "weight_bop": weight_sum,
                    "return_base": group_return,
                }
            )
        benchmark_groups.append(
            BenchmarkGroup.model_validate(
                {
                    "key": {dimension: value for dimension, value in key_tuple},
                    "observations": observations,
                }
            )
        )
    return benchmark_groups


def _build_group_key(
    *,
    labels: dict[str, object],
    group_by: list[str],
    index_id: str,
) -> tuple[tuple[str, str], ...]:
    key_parts: list[tuple[str, str]] = []
    for dimension in group_by:
        raw_value = labels.get(dimension)
        if not isinstance(raw_value, str) or not raw_value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Benchmark component {index_id} missing classification label for {dimension}.",
            )
        key_parts.append((dimension, raw_value))
    return tuple(key_parts)


def _position_row_to_daily_point(
    *,
    row: dict[str, object],
    reporting_currency: str | None,
) -> dict[str, object] | None:
    valuation_date = row.get("valuation_date")
    if not isinstance(valuation_date, str):
        return None

    if reporting_currency is not None:
        begin_value = row.get("beginning_market_value_reporting_currency")
        end_value = row.get("ending_market_value_reporting_currency")
    else:
        begin_value = row.get("beginning_market_value_portfolio_currency")
        end_value = row.get("ending_market_value_portfolio_currency")

    if begin_value is None or end_value is None:
        return None

    bod_cf, eod_cf = _split_position_cash_flows(row.get("cash_flows"))
    return {
        "day": 0,
        "perf_date": valuation_date,
        "begin_mv": Decimal(str(begin_value)),
        "end_mv": Decimal(str(end_value)),
        "bod_cf": bod_cf,
        "eod_cf": eod_cf,
    }


def _split_position_cash_flows(cash_flows_raw: object) -> tuple[Decimal, Decimal]:
    bod_cf = Decimal("0")
    eod_cf = Decimal("0")
    if not isinstance(cash_flows_raw, list):
        return bod_cf, eod_cf

    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            continue
        amount = flow.get("amount")
        timing = flow.get("timing")
        if amount is None or timing not in {"bod", "eod"}:
            continue
        decimal_amount = Decimal(str(amount))
        if timing == "bod":
            bod_cf += decimal_amount
        else:
            eod_cf += decimal_amount
    return bod_cf, eod_cf


def _position_meta_from_row(row: dict[str, object]) -> dict[str, object]:
    meta: dict[str, object] = {}
    security_id = row.get("security_id")
    if isinstance(security_id, str):
        meta["security_id"] = security_id

    dimensions_raw = row.get("dimensions")
    if isinstance(dimensions_raw, dict):
        for key, value in dimensions_raw.items():
            if isinstance(key, str) and value is not None:
                meta[key] = value
    return meta


def _parse_position_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows_raw = payload.get("rows")
    return [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []


def _parse_component_series(payload: dict[str, object]) -> list[dict[str, object]]:
    component_series_raw = payload.get("component_series")
    return (
        [component for component in component_series_raw if isinstance(component, dict)]
        if isinstance(component_series_raw, list)
        else []
    )


def _parse_index_catalog(payload: dict[str, object]) -> list[dict[str, object]]:
    records_raw = payload.get("records")
    return [record for record in records_raw if isinstance(record, dict)] if isinstance(records_raw, list) else []


def _parse_retrieval_metadata(payload: dict[str, object]) -> RetrievalMetadata:
    metadata_raw = payload.get("retrieval_metadata")
    if not isinstance(metadata_raw, dict):
        return RetrievalMetadata(chunk_count=1, page_count=1)
    chunk_count = metadata_raw.get("chunk_count")
    page_count = metadata_raw.get("page_count")
    return RetrievalMetadata(
        chunk_count=int(chunk_count) if isinstance(chunk_count, int) and chunk_count > 0 else 1,
        page_count=int(page_count) if isinstance(page_count, int) and page_count > 0 else 1,
    )
