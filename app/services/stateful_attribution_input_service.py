from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import pandas as pd
from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.attribution_requests import AttributionPortfolioData, BenchmarkGroup, InstrumentData
from app.models.benchmark_analytics_requests import BenchmarkReturnSource
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.models.stateful_position_inputs import StatefulDimensionName
from app.services.source_cashflow_taxonomy import classify_cashflow_type
from app.services.stateful_benchmark_input_service import build_stateful_benchmark_input
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_performance_input_service import (
    StatefulPortfolioInput,
    retrieve_stateful_portfolio_input,
)
from app.services.stateful_position_row_service import (
    PositionValueBasis,
    split_position_cash_flows_in_value_basis,
)
from app.services.stateful_retrieval_metadata import parse_retrieval_metadata
from app.services.stateful_upstream_errors import (
    raise_for_stateful_control_plane_unavailable,
    raise_for_stateful_source_unavailable,
)
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points
from engine.benchmarks import calculate_benchmark_returns

_SUPPORTED_ATTRIBUTION_GROUPS: set[str] = {"asset_class", "sector", "country", "currency"}
_UPSTREAM_DIMENSION_GROUPS: set[str] = {"asset_class", "sector", "country"}
_BenchmarkGroupDateBucket = dict[str, Decimal]
_BenchmarkGroupBuckets = dict[tuple[tuple[str, str], ...], dict[str, _BenchmarkGroupDateBucket]]


@dataclass(frozen=True)
class StatefulAttributionSourceInput:
    portfolio_input: StatefulPortfolioInput
    position_rows: list[dict[str, object]]
    position_retrieval_metadata: RetrievalMetadata
    benchmark_id: str
    benchmark_component_observations: list[BenchmarkComponentObservation]
    benchmark_source_details: dict[str, int]
    benchmark_retrieval_metadata: RetrievalMetadata
    index_records: list[dict[str, object]]
    index_retrieval_metadata: RetrievalMetadata


@dataclass(frozen=True)
class StatefulAttributionNormalizedInput:
    portfolio_data: AttributionPortfolioData
    instruments_data: list[InstrumentData]
    benchmark_groups_data: list[BenchmarkGroup]
    source_alignment_evidence: dict[str, object]


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
        {*dimensions, *[dimension for dimension in group_by if dimension in _UPSTREAM_DIMENSION_GROUPS]}
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
    raise_for_stateful_control_plane_unavailable(
        source_label="stateful position timeseries source",
        upstream_status=upstream_status,
    )
    position_rows = _parse_position_rows(upstream_payload)

    benchmark_id = await _resolve_stateful_attribution_benchmark_id(
        stateful_input_service=stateful_input_service,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        reporting_currency=reporting_currency,
        calculation_id=calculation_id,
        benchmark_id_override=benchmark_id_override,
    )

    benchmark_input = await build_stateful_benchmark_input(
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
        benchmark_id=benchmark_id,
        as_of_date=as_of_date,
        start_date=report_start_date,
        end_date=report_end_date,
        return_source=BenchmarkReturnSource.CALCULATED,
    )
    benchmark_component_index_ids = sorted(
        {observation.component_id for observation in benchmark_input.component_observations if observation.component_id}
    )

    index_status, index_payload = await stateful_input_service.get_index_catalog(
        as_of_date=as_of_date,
        index_ids=benchmark_component_index_ids,
        calculation_id=calculation_id,
    )
    if index_status >= status.HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(source_label="index catalog", upstream_status=index_status)
    index_records = _parse_index_catalog(index_payload)

    return StatefulAttributionSourceInput(
        portfolio_input=portfolio_input,
        position_rows=position_rows,
        position_retrieval_metadata=parse_retrieval_metadata(upstream_payload),
        benchmark_id=benchmark_id,
        benchmark_component_observations=benchmark_input.component_observations,
        benchmark_source_details=benchmark_input.source_details,
        benchmark_retrieval_metadata=RetrievalMetadata(
            chunk_count=benchmark_input.source_details.get("benchmark_chunk_count", 0),
            page_count=benchmark_input.source_details.get("benchmark_page_count", 0),
        ),
        index_records=index_records,
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )


async def _resolve_stateful_attribution_benchmark_id(
    *,
    stateful_input_service: StatefulInputService,
    portfolio_id: str,
    as_of_date,
    reporting_currency: str | None,
    calculation_id,
    benchmark_id_override: str | None,
) -> str:
    if benchmark_id_override is not None:
        return benchmark_id_override

    assignment_status, assignment_payload = await stateful_input_service.get_benchmark_assignment(
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        reporting_currency=reporting_currency,
        calculation_id=calculation_id,
    )
    if assignment_status == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Stateful attribution input requires a benchmark assignment or explicit stateful_input.benchmark_id.",
        )
    if assignment_status >= status.HTTP_400_BAD_REQUEST:
        raise_for_stateful_source_unavailable(
            source_label="benchmark assignment",
            upstream_status=assignment_status,
        )
    benchmark_id_raw = assignment_payload.get("benchmark_id")
    if not isinstance(benchmark_id_raw, str) or not benchmark_id_raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="benchmark assignment payload missing benchmark_id.",
        )
    return benchmark_id_raw


def build_stateful_attribution_input(
    *,
    source_input: StatefulAttributionSourceInput,
    mode: str,
    group_by: list[str],
    metric_basis: str,
    currency_mode: str | None,
    fx: object,
    reporting_currency: str | None,
) -> StatefulAttributionNormalizedInput:
    if mode != "by_instrument":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Stateful attribution currently supports mode=by_instrument only.",
        )

    _validate_stateful_position_inception_support(rows=source_input.position_rows)
    _validate_stateful_portfolio_position_alignment(
        portfolio_observations=source_input.portfolio_input.observations,
        position_rows=source_input.position_rows,
        reporting_currency=reporting_currency,
    )

    normalized_currency_mode = currency_mode or "BASE_ONLY"
    if normalized_currency_mode == "BOTH":
        _validate_stateful_both_currency_support(
            rows=source_input.position_rows,
            reporting_currency=reporting_currency,
            fx=fx,
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
        currency_mode=normalized_currency_mode,
        reporting_currency=reporting_currency,
    )
    benchmark_groups_data = _build_benchmark_groups(
        group_by=group_by,
        component_observations=source_input.benchmark_component_observations,
        index_records=source_input.index_records,
    )
    source_alignment_evidence = build_stateful_attribution_source_alignment_evidence(
        source_input=source_input,
        group_by=group_by,
        currency_mode=normalized_currency_mode,
        fx=fx,
        reporting_currency=reporting_currency,
    )

    return StatefulAttributionNormalizedInput(
        portfolio_data=portfolio_data,
        instruments_data=instruments_data,
        benchmark_groups_data=benchmark_groups_data,
        source_alignment_evidence=source_alignment_evidence,
    )


def build_stateful_attribution_source_alignment_evidence(
    *,
    source_input: StatefulAttributionSourceInput,
    group_by: list[str],
    currency_mode: str,
    fx: object,
    reporting_currency: str | None,
) -> dict[str, object]:
    classification_dimensions = sorted({dimension for dimension in group_by if dimension in _UPSTREAM_DIMENSION_GROUPS})
    return {
        "portfolio_observation_count": len(source_input.portfolio_input.observations),
        "position_row_count": len(source_input.position_rows),
        "benchmark_id": source_input.benchmark_id,
        "benchmark_component_observation_count": len(source_input.benchmark_component_observations),
        "index_record_count": len(source_input.index_records),
        "classification_dimensions": classification_dimensions,
        "position_classification": _summarize_position_classification(
            rows=source_input.position_rows,
            dimensions=classification_dimensions,
        ),
        "benchmark_classification": _summarize_benchmark_classification(
            component_observations=source_input.benchmark_component_observations,
            index_records=source_input.index_records,
            dimensions=classification_dimensions,
        ),
        "currency_source": _summarize_currency_source(
            rows=source_input.position_rows,
            component_observations=source_input.benchmark_component_observations,
            currency_mode=currency_mode,
            fx=fx,
            reporting_currency=reporting_currency,
        ),
        "source_contract_limitations": {
            "benchmark_version": "not_available_from_current_lotus_core_contract",
            "classification_version": "not_available_from_current_lotus_core_contract",
            "calendar_policy": "not_available_from_current_lotus_core_contract",
            "off_benchmark_policy": "derived_by_lotus_performance_from_portfolio_and_benchmark_exposure",
            "derivative_or_short_flags": "not_available_from_current_lotus_core_contract",
            "fee_tax_income_breakout": "not_available_from_current_lotus_core_contract",
        },
    }


def _validate_stateful_portfolio_position_alignment(
    *,
    portfolio_observations: list[dict[str, object]],
    position_rows: list[dict[str, object]],
    reporting_currency: str | None,
) -> None:
    mismatched_dates = _stateful_portfolio_position_alignment_mismatches(
        portfolio_by_date=_portfolio_market_values_by_date(portfolio_observations),
        position_totals_by_date=_position_market_value_totals_by_date(
            position_rows=position_rows,
            reporting_currency=reporting_currency,
        ),
    )
    if mismatched_dates:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Stateful attribution source inputs are inconsistent: lotus-core portfolio timeseries does not align "
                "with summed position timeseries for one or more dates. "
                f"Sample mismatches: {'; '.join(mismatched_dates[:3])}."
            ),
        )


def _portfolio_market_values_by_date(
    portfolio_observations: list[dict[str, object]],
) -> dict[str, tuple[Decimal, Decimal]]:
    portfolio_by_date: dict[str, tuple[Decimal, Decimal]] = {}
    for observation in portfolio_observations:
        valuation_date = observation.get("valuation_date")
        begin_value = observation.get("beginning_market_value")
        end_value = observation.get("ending_market_value")
        if not isinstance(valuation_date, str) or begin_value is None or end_value is None:
            continue
        portfolio_by_date[valuation_date] = (Decimal(str(begin_value)), Decimal(str(end_value)))
    return portfolio_by_date


def _position_market_value_totals_by_date(
    *,
    position_rows: list[dict[str, object]],
    reporting_currency: str | None,
) -> dict[str, dict[str, Decimal]]:
    position_totals_by_date: dict[str, dict[str, Decimal]] = {}
    for row in position_rows:
        valuation_date = row.get("valuation_date")
        if not isinstance(valuation_date, str):
            continue
        market_values = _position_market_value_pair(row=row, reporting_currency=reporting_currency)
        if market_values is None:
            continue
        begin_value, end_value = market_values
        totals = position_totals_by_date.setdefault(
            valuation_date,
            {"begin": Decimal("0"), "end": Decimal("0"), "internal_flow_abs": Decimal("0")},
        )
        totals["begin"] += Decimal(str(begin_value))
        totals["end"] += Decimal(str(end_value))
        totals["internal_flow_abs"] += _sum_internal_cash_flow_abs_in_alignment_basis(
            row=row,
            reporting_currency=reporting_currency,
        )
    return position_totals_by_date


def _position_market_value_pair(
    *,
    row: dict[str, object],
    reporting_currency: str | None,
) -> tuple[object, object] | None:
    if reporting_currency is not None:
        reporting_values = _row_value_pair(
            row,
            begin_key="beginning_market_value_reporting_currency",
            end_key="ending_market_value_reporting_currency",
        )
        if reporting_values is not None:
            return reporting_values
    return _row_value_pair(
        row,
        begin_key="beginning_market_value_portfolio_currency",
        end_key="ending_market_value_portfolio_currency",
    )


def _row_value_pair(
    row: dict[str, object],
    *,
    begin_key: str,
    end_key: str,
) -> tuple[object, object] | None:
    begin_value = row.get(begin_key)
    end_value = row.get(end_key)
    if begin_value is None or end_value is None:
        return None
    return begin_value, end_value


def _stateful_portfolio_position_alignment_mismatches(
    *,
    portfolio_by_date: dict[str, tuple[Decimal, Decimal]],
    position_totals_by_date: dict[str, dict[str, Decimal]],
) -> list[str]:
    tolerance = Decimal("0.01")
    mismatched_dates: list[str] = []
    for valuation_date in sorted(set(portfolio_by_date) & set(position_totals_by_date)):
        portfolio_begin, portfolio_end = portfolio_by_date[valuation_date]
        position_begin = position_totals_by_date[valuation_date]["begin"]
        position_end = position_totals_by_date[valuation_date]["end"]
        begin_mismatch = abs(portfolio_begin - position_begin)
        end_mismatch = abs(portfolio_end - position_end)
        internal_flow_abs = position_totals_by_date[valuation_date]["internal_flow_abs"]
        mismatch_explained_by_internal_transfer_timing = (
            max(begin_mismatch, end_mismatch) <= internal_flow_abs + tolerance
        )
        if (
            begin_mismatch > tolerance or end_mismatch > tolerance
        ) and not mismatch_explained_by_internal_transfer_timing:
            mismatched_dates.append(
                f"{valuation_date} (portfolio begin/end={portfolio_begin}/{portfolio_end}, "
                f"positions begin/end={position_begin}/{position_end})"
            )
    return mismatched_dates


def _sum_internal_cash_flow_abs_in_alignment_basis(
    *,
    row: dict[str, object],
    reporting_currency: str | None,
) -> Decimal:
    cash_flows_raw = row.get("cash_flows")
    if not isinstance(cash_flows_raw, list):
        return Decimal("0")

    conversion_factor = _alignment_cash_flow_conversion_factor(
        row=row,
        reporting_currency=reporting_currency,
    )
    total = Decimal("0")
    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            continue
        amount = flow.get("amount")
        if amount is None:
            continue
        if classify_cashflow_type(flow.get("cash_flow_type")).economics_role != "internal":
            continue
        total += abs(Decimal(str(amount)) * conversion_factor)
    return total


def _alignment_cash_flow_conversion_factor(
    *,
    row: dict[str, object],
    reporting_currency: str | None,
) -> Decimal:
    position_to_portfolio_rate = _decimal_or_one(row.get("position_to_portfolio_fx_rate"))
    if reporting_currency is None:
        return position_to_portfolio_rate
    return position_to_portfolio_rate * _decimal_or_one(row.get("portfolio_to_reporting_fx_rate"))


def _decimal_or_one(value: object) -> Decimal:
    if value is None:
        return Decimal("1")
    return Decimal(str(value))


def _summarize_position_classification(
    *,
    rows: list[dict[str, object]],
    dimensions: list[str],
) -> dict[str, int | str]:
    if not dimensions:
        return {"status": "not_required", "classified_row_count": len(rows), "unclassified_row_count": 0}

    classified_count = 0
    for row in rows:
        if _row_has_required_position_dimensions(row=row, dimensions=dimensions):
            classified_count += 1

    unclassified_count = len(rows) - classified_count
    return {
        "status": "complete" if unclassified_count == 0 else "partial",
        "classified_row_count": classified_count,
        "unclassified_row_count": unclassified_count,
    }


def _row_has_required_position_dimensions(
    *,
    row: dict[str, object],
    dimensions: list[str],
) -> bool:
    labels = row.get("dimensions")
    if not isinstance(labels, dict):
        return False
    return all(
        isinstance(labels.get(dimension), str) and str(labels.get(dimension)).strip() for dimension in dimensions
    )


def _classification_labels_by_index(index_records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    labels_by_index: dict[str, dict[str, object]] = {}
    for record in index_records:
        index_id = record.get("index_id")
        labels = record.get("classification_labels")
        if isinstance(index_id, str) and isinstance(labels, dict):
            labels_by_index[index_id] = labels
    return labels_by_index


def _classified_component_count(
    *,
    component_ids: list[str],
    labels_by_index: dict[str, dict[str, object]],
    dimensions: list[str],
) -> int:
    classified_count = 0
    for component_id in component_ids:
        labels = labels_by_index.get(component_id)
        if labels is None:
            continue
        if all(
            isinstance(labels.get(dimension), str) and str(labels.get(dimension)).strip() for dimension in dimensions
        ):
            classified_count += 1
    return classified_count


def _summarize_benchmark_classification(
    *,
    component_observations: list[BenchmarkComponentObservation],
    index_records: list[dict[str, object]],
    dimensions: list[str],
) -> dict[str, int | str]:
    component_ids = sorted(
        {observation.component_id for observation in component_observations if observation.component_id}
    )
    if not dimensions:
        return {
            "status": "not_required",
            "classified_component_count": len(component_ids),
            "unclassified_component_count": 0,
        }

    labels_by_index = _classification_labels_by_index(index_records)
    classified_count = _classified_component_count(
        component_ids=component_ids,
        labels_by_index=labels_by_index,
        dimensions=dimensions,
    )
    unclassified_count = len(component_ids) - classified_count
    return {
        "status": "complete" if unclassified_count == 0 else "partial",
        "classified_component_count": classified_count,
        "unclassified_component_count": unclassified_count,
    }


def _summarize_currency_source(
    *,
    rows: list[dict[str, object]],
    component_observations: list[BenchmarkComponentObservation],
    currency_mode: str,
    fx: object,
    reporting_currency: str | None,
) -> dict[str, int | bool | str | None]:
    position_currencies = _distinct_source_currencies(row.get("position_currency") for row in rows)
    benchmark_component_currencies = _distinct_source_currencies(
        observation.component_currency for observation in component_observations
    )
    fx_required = _stateful_attribution_fx_required(
        currency_mode=currency_mode,
        reporting_currency=reporting_currency,
        position_currencies=position_currencies,
    )

    return {
        "status": "required" if currency_mode == "BOTH" else "not_required",
        "reporting_currency": reporting_currency,
        "position_currency_count": len(position_currencies),
        "benchmark_component_currency_count": len(benchmark_component_currencies),
        "fx_required": fx_required,
        "fx_supplied": fx is not None,
    }


def _stateful_attribution_fx_required(
    *,
    currency_mode: str,
    reporting_currency: str | None,
    position_currencies: list[str],
) -> bool:
    return (
        currency_mode == "BOTH"
        and reporting_currency is not None
        and any(position_currency != reporting_currency for position_currency in position_currencies)
    )


def _distinct_source_currencies(values: Iterable[object]) -> list[str]:
    return sorted({value for value in values if isinstance(value, str) and value})


def _validate_stateful_position_inception_support(*, rows: list[dict[str, object]]) -> None:
    unsupported_positions: list[str] = []
    for position_id, row in _first_rows_by_position(rows).items():
        if _has_unsupported_position_inception_row(row):
            unsupported_positions.append(position_id)

    if unsupported_positions:
        sample_positions = ", ".join(unsupported_positions[:5])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Stateful attribution cannot safely compute acquisition-day position returns when the requested window "
                "starts a sourced position with zero beginning market value, positive ending market value, and no usable "
                "beginning-of-day cash-flow semantics. "
                f"Affected positions: {sample_positions}."
            ),
        )


def _has_unsupported_position_inception_row(row: dict[str, object]) -> bool:
    begin_value_raw = row.get("beginning_market_value_portfolio_currency")
    end_value_raw = row.get("ending_market_value_portfolio_currency")
    begin_value = Decimal(str(begin_value_raw)) if begin_value_raw is not None else Decimal("0")
    end_value = Decimal(str(end_value_raw)) if end_value_raw is not None else Decimal("0")
    bod_cf, _ = _split_position_cash_flows(row.get("cash_flows"))
    return begin_value == 0 and end_value > 0 and (begin_value + bod_cf) <= 0


def _first_rows_by_position(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    first_rows_by_position: dict[str, dict[str, object]] = {}
    for row in sorted(rows, key=lambda item: (str(item.get("position_id", "")), str(item.get("valuation_date", "")))):
        position_id = row.get("position_id")
        if not isinstance(position_id, str) or position_id in first_rows_by_position:
            continue
        first_rows_by_position[position_id] = row
    return first_rows_by_position


def _validate_stateful_group_by(group_by: list[str]) -> None:
    unsupported = sorted({dimension for dimension in group_by if dimension not in _SUPPORTED_ATTRIBUTION_GROUPS})
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Stateful attribution supports group_by only for canonical lotus-core attribution dimensions plus currency: "
                f"{', '.join(sorted(_SUPPORTED_ATTRIBUTION_GROUPS))}. Unsupported: {', '.join(unsupported)}."
            ),
        )


def _build_instruments_data(
    *,
    rows: list[dict[str, object]],
    currency_mode: str,
    reporting_currency: str | None,
) -> list[InstrumentData]:
    positions_by_id: dict[str, list[dict[str, object]]] = {}
    instrument_meta: dict[str, dict[str, object]] = {}
    for row in rows:
        _record_instrument_position_row(
            row=row,
            positions_by_id=positions_by_id,
            instrument_meta=instrument_meta,
            currency_mode=currency_mode,
            reporting_currency=reporting_currency,
        )

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


def _record_instrument_position_row(
    *,
    row: dict[str, object],
    positions_by_id: dict[str, list[dict[str, object]]],
    instrument_meta: dict[str, dict[str, object]],
    currency_mode: str,
    reporting_currency: str | None,
) -> bool:
    position_id = row.get("position_id")
    valuation_date = row.get("valuation_date")
    if not isinstance(position_id, str) or not isinstance(valuation_date, str):
        return False
    point = _position_row_to_daily_point(
        row=row,
        currency_mode=currency_mode,
        reporting_currency=reporting_currency,
    )
    if point is None:
        return False
    positions_by_id.setdefault(position_id, []).append(point)
    meta = instrument_meta.setdefault(position_id, _position_meta_from_row(row))
    base_weight_point = _position_row_to_base_weight_point(
        row=row,
        reporting_currency=reporting_currency,
    )
    if base_weight_point is not None:
        base_weight_points = cast(list[dict[str, object]], meta.setdefault("base_weight_points", []))
        base_weight_points.append(base_weight_point)
    return True


def _build_benchmark_groups(
    *,
    group_by: list[str],
    component_observations: list[BenchmarkComponentObservation],
    index_records: list[dict[str, object]],
) -> list[BenchmarkGroup]:
    if not component_observations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No normalized benchmark component observations are available for stateful attribution.",
        )

    labels_by_index = _benchmark_labels_by_index(index_records)
    engine_result = calculate_benchmark_returns(component_observations)
    grouped: _BenchmarkGroupBuckets = {}
    for _, row in engine_result.component_contributions_df.iterrows():
        _add_benchmark_group_row(
            grouped=grouped,
            labels_by_index=labels_by_index,
            group_by=group_by,
            row=row,
        )

    benchmark_groups: list[BenchmarkGroup] = []
    for key_tuple in sorted(grouped):
        observations = []
        for series_date in sorted(grouped[key_tuple]):
            observations.append(
                _benchmark_group_observation(
                    series_date=series_date,
                    date_bucket=grouped[key_tuple][series_date],
                )
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


def _benchmark_labels_by_index(index_records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    labels_by_index: dict[str, dict[str, object]] = {}
    for record in index_records:
        index_id = record.get("index_id")
        labels = record.get("classification_labels")
        if isinstance(index_id, str) and isinstance(labels, dict):
            labels_by_index[index_id] = labels
    return labels_by_index


def _empty_benchmark_group_date_bucket() -> _BenchmarkGroupDateBucket:
    return {
        "weight_sum": Decimal("0"),
        "weighted_return_sum": Decimal("0"),
        "weighted_local_return_sum": Decimal("0"),
        "weighted_fx_return_sum": Decimal("0"),
    }


def _add_benchmark_group_row(
    *,
    grouped: _BenchmarkGroupBuckets,
    labels_by_index: dict[str, dict[str, object]],
    group_by: list[str],
    row: pd.Series,
) -> None:
    group_key = _benchmark_group_key_from_row(
        row=row,
        labels_by_index=labels_by_index,
        group_by=group_by,
    )
    series_date = row["date"].isoformat()
    date_bucket = grouped.setdefault(group_key, {}).setdefault(series_date, _empty_benchmark_group_date_bucket())
    weight = Decimal(str(row["weight_bop"]))
    date_bucket["weight_sum"] += weight
    date_bucket["weighted_return_sum"] += Decimal(str(row["contribution"]))

    component_return_local = row.get("component_return_local")
    component_return_fx = row.get("component_return_fx")
    if pd.notna(component_return_local):
        date_bucket["weighted_local_return_sum"] += weight * Decimal(str(component_return_local))
    if pd.notna(component_return_fx):
        date_bucket["weighted_fx_return_sum"] += weight * Decimal(str(component_return_fx))


def _benchmark_group_key_from_row(
    *,
    row: pd.Series,
    labels_by_index: dict[str, dict[str, object]],
    group_by: list[str],
) -> tuple[tuple[str, str], ...]:
    index_id = row["component_id"]
    labels = labels_by_index.get(index_id)
    component_currency = row.get("component_currency")
    if labels is None and "currency" not in group_by:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Index catalog missing classification labels for benchmark component {index_id}.",
        )
    return _build_group_key(
        labels=labels or {},
        group_by=group_by,
        index_id=index_id,
        component_currency=str(component_currency) if component_currency is not None else None,
    )


def _benchmark_group_observation(
    *,
    series_date: str,
    date_bucket: _BenchmarkGroupDateBucket,
) -> dict[str, object]:
    weight_sum = date_bucket["weight_sum"]
    if weight_sum == 0:
        return {
            "date": series_date,
            "weight_bop": weight_sum,
            "return_base": Decimal("0"),
            "return_local": Decimal("0"),
            "return_fx": Decimal("0"),
        }
    return {
        "date": series_date,
        "weight_bop": weight_sum,
        "return_base": date_bucket["weighted_return_sum"] / weight_sum,
        "return_local": date_bucket["weighted_local_return_sum"] / weight_sum,
        "return_fx": date_bucket["weighted_fx_return_sum"] / weight_sum,
    }


def _build_group_key(
    *,
    labels: dict[str, object],
    group_by: list[str],
    index_id: str,
    component_currency: str | None = None,
) -> tuple[tuple[str, str], ...]:
    key_parts: list[tuple[str, str]] = []
    for dimension in group_by:
        key_parts.append(
            (
                dimension,
                _benchmark_group_dimension_value(
                    dimension=dimension,
                    labels=labels,
                    index_id=index_id,
                    component_currency=component_currency,
                ),
            )
        )
    return tuple(key_parts)


def _benchmark_group_dimension_value(
    *,
    dimension: str,
    labels: dict[str, object],
    index_id: str,
    component_currency: str | None = None,
) -> str:
    if dimension == "currency":
        return _benchmark_currency_group_value(
            index_id=index_id,
            component_currency=component_currency,
        )
    raw_value = labels.get(dimension)
    return _normalize_group_value(raw_value) if isinstance(raw_value, str) and raw_value else "unknown"


def _benchmark_currency_group_value(
    *,
    index_id: str,
    component_currency: str | None,
) -> str:
    if not isinstance(component_currency, str) or not component_currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Benchmark component {index_id} missing classification label for currency.",
        )
    return _normalize_group_value(component_currency)


def _position_row_to_daily_point(
    *,
    row: dict[str, object],
    currency_mode: str,
    reporting_currency: str | None,
) -> dict[str, object] | None:
    valuation_date = row.get("valuation_date")
    if not isinstance(valuation_date, str):
        return None

    market_values = _position_daily_point_market_values(
        row=row,
        currency_mode=currency_mode,
        reporting_currency=reporting_currency,
    )
    if market_values is None:
        return None
    begin_value, end_value, value_basis = market_values

    bod_cf, eod_cf, _ = split_position_cash_flows_in_value_basis(
        cash_flows_raw=row.get("cash_flows"),
        row=row,
        value_basis=value_basis,
    )
    return {
        "perf_date": valuation_date,
        "begin_mv": Decimal(str(begin_value)),
        "end_mv": Decimal(str(end_value)),
        "bod_cf": bod_cf,
        "eod_cf": eod_cf,
    }


def _position_daily_point_market_values(
    *,
    row: dict[str, object],
    currency_mode: str,
    reporting_currency: str | None,
) -> tuple[object, object, PositionValueBasis] | None:
    if currency_mode in {"LOCAL_ONLY", "BOTH"}:
        begin_value = row.get("beginning_market_value_position_currency")
        end_value = row.get("ending_market_value_position_currency")
        value_basis: PositionValueBasis = "position"
    elif reporting_currency is not None:
        begin_value = row.get("beginning_market_value_reporting_currency")
        end_value = row.get("ending_market_value_reporting_currency")
        if begin_value is None or end_value is None:
            begin_value = row.get("beginning_market_value_portfolio_currency")
            end_value = row.get("ending_market_value_portfolio_currency")
        value_basis = "reporting"
    else:
        begin_value = row.get("beginning_market_value_portfolio_currency")
        end_value = row.get("ending_market_value_portfolio_currency")
        value_basis = "portfolio"

    if begin_value is None or end_value is None:
        return None
    return begin_value, end_value, value_basis


def _position_row_to_base_weight_point(
    *,
    row: dict[str, object],
    reporting_currency: str | None,
) -> dict[str, object] | None:
    valuation_date = row.get("valuation_date")
    if not isinstance(valuation_date, str):
        return None
    value_basis: PositionValueBasis

    if reporting_currency is not None:
        begin_value = row.get("beginning_market_value_reporting_currency")
    else:
        begin_value = row.get("beginning_market_value_portfolio_currency")
    if begin_value is None:
        begin_value = row.get("beginning_market_value_portfolio_currency")
    if begin_value is None:
        return None

    if reporting_currency is not None:
        value_basis = "reporting"
    else:
        value_basis = "portfolio"
    bod_cf, _, _ = split_position_cash_flows_in_value_basis(
        cash_flows_raw=row.get("cash_flows"),
        row=row,
        value_basis=value_basis,
    )
    return {
        "perf_date": valuation_date,
        "begin_mv": Decimal(str(begin_value)),
        "bod_cf": bod_cf,
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
    position_currency = row.get("position_currency")
    if isinstance(position_currency, str) and position_currency:
        meta["currency"] = _normalize_group_value(position_currency)
    cash_flow_currency = row.get("cash_flow_currency")
    if isinstance(cash_flow_currency, str) and cash_flow_currency:
        meta["cash_flow_currency"] = _normalize_group_value(cash_flow_currency)

    meta.update(_position_meta_fx_rate_fields(row))
    meta.update(_normalized_position_dimensions(row.get("dimensions")))
    return meta


def _position_meta_fx_rate_fields(row: dict[str, object]) -> dict[str, object]:
    fx_rates: dict[str, object] = {}
    position_to_portfolio_fx_rate = row.get("position_to_portfolio_fx_rate")
    if position_to_portfolio_fx_rate is not None:
        fx_rates["position_to_portfolio_fx_rate"] = Decimal(str(position_to_portfolio_fx_rate))
    portfolio_to_reporting_fx_rate = row.get("portfolio_to_reporting_fx_rate")
    if portfolio_to_reporting_fx_rate is not None:
        fx_rates["portfolio_to_reporting_fx_rate"] = Decimal(str(portfolio_to_reporting_fx_rate))
    return fx_rates


def _normalized_position_dimensions(dimensions_raw: object) -> dict[str, object]:
    dimensions: dict[str, object] = {}
    if not isinstance(dimensions_raw, dict):
        return dimensions
    for key, value in dimensions_raw.items():
        if not isinstance(key, str):
            continue
        dimension_value = _normalized_position_dimension_value(value)
        if dimension_value is not None:
            dimensions[key] = dimension_value
    return dimensions


def _normalized_position_dimension_value(value: object) -> object | None:
    if isinstance(value, str) and value:
        return _normalize_group_value(value)
    if value is not None:
        return value
    return None


def _normalize_group_value(value: str) -> str:
    return value.strip().replace(" ", "_").lower()


def _parse_position_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    rows_raw = payload.get("rows")
    return [row for row in rows_raw if isinstance(row, dict)] if isinstance(rows_raw, list) else []


def _parse_index_catalog(payload: dict[str, object]) -> list[dict[str, object]]:
    records_raw = payload.get("records")
    return [record for record in records_raw if isinstance(record, dict)] if isinstance(records_raw, list) else []


def _validate_stateful_both_currency_support(
    *,
    rows: list[dict[str, object]],
    reporting_currency: str | None,
    fx: object,
) -> None:
    if not reporting_currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Stateful attribution input requires report_ccy when currency_mode=BOTH.",
        )

    position_currencies = _stateful_position_currencies(rows)
    if not position_currencies:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Stateful attribution input requires position_currency on lotus-core position-timeseries rows "
                "when currency_mode=BOTH."
            ),
        )

    if any(position_currency != reporting_currency for position_currency in position_currencies) and fx is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Stateful attribution input requires fx.rates when currency_mode=BOTH and sourced positions "
                "include currencies different from report_ccy."
            ),
        )


def _stateful_position_currencies(rows: list[dict[str, object]]) -> set[str]:
    return {
        position_currency
        for row in rows
        for position_currency in [row.get("position_currency")]
        if isinstance(position_currency, str) and position_currency
    }
