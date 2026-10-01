"""Build source-owned portfolio/benchmark group-return evidence without performing risk attribution."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final, Iterable, Literal

from app.models.benchmark_requests import BenchmarkComponentObservation
from app.models.group_return_evidence import (
    GroupReturnEvidenceAggregateReturn,
    GroupReturnEvidenceCoverage,
    GroupReturnEvidenceGrouping,
    GroupReturnEvidenceRequest,
    GroupReturnEvidenceResponse,
    GroupReturnEvidenceRow,
    GroupReturnEvidenceSourceLineage,
    GroupReturnEvidenceSourceSnapshot,
)
from app.services.stateful_performance_input_service import StatefulPortfolioInput
from app.services.stateful_position_row_service import (
    position_cash_flows_are_losslessly_normalizable,
    split_position_cash_flows_in_value_basis,
)
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points

_MONEY_RECONCILIATION_TOLERANCE = Decimal("0.01")
_WEIGHT_RECONCILIATION_TOLERANCE = Decimal("0.000000000001")
_GROUP_RECONCILIATION_TOLERANCE = Decimal("0.000001")
_RETURN_BASIS: Final[Literal["SOURCE_POSITION_AND_BENCHMARK_COMPONENT_GROSS_TWR"]] = (
    "SOURCE_POSITION_AND_BENCHMARK_COMPONENT_GROSS_TWR"
)
_VALUATION_BASIS: Final[Literal["SOURCE_REPORTED_BEGINNING_AND_ENDING_MARKET_VALUES"]] = (
    "SOURCE_REPORTED_BEGINNING_AND_ENDING_MARKET_VALUES"
)
_WEIGHT_BASIS: Final[Literal["SIGNED_BEGINNING_CAPITAL_AND_BENCHMARK_BOP_WEIGHT"]] = (
    "SIGNED_BEGINNING_CAPITAL_AND_BENCHMARK_BOP_WEIGHT"
)

_GROUP_SOURCE_FIELDS: dict[GroupReturnEvidenceGrouping, str] = {
    GroupReturnEvidenceGrouping.ASSET_CLASS: "asset_class",
    GroupReturnEvidenceGrouping.COUNTRY: "country",
    GroupReturnEvidenceGrouping.CURRENCY: "currency",
    GroupReturnEvidenceGrouping.SECTOR: "sector",
}


@dataclass(frozen=True)
class GroupReturnEvidenceSourceInput:
    """Normalized stateful source facts consumed by the v1 producer contract."""

    portfolio_input: StatefulPortfolioInput
    position_rows: list[dict[str, object]]
    position_source_rows_complete: bool
    benchmark_id: str
    benchmark_currency: str | None
    benchmark_component_observations: list[BenchmarkComponentObservation]
    index_records: list[dict[str, object]]


@dataclass(frozen=True)
class _DailyPortfolioGroup:
    beginning_capital: Decimal
    ending_value: Decimal
    bod_cash_flow: Decimal
    eod_cash_flow: Decimal


@dataclass(frozen=True)
class _DailyBenchmarkGroup:
    weight: Decimal
    contribution: Decimal


def build_group_return_evidence_response(
    *,
    request: GroupReturnEvidenceRequest,
    source_input: GroupReturnEvidenceSourceInput,
    source_snapshots: Iterable[object],
) -> GroupReturnEvidenceResponse:
    """Return aligned group evidence or refuse a source condition that would make it incomplete."""
    _validate_common_currency(request=request, source_input=source_input)
    _validate_requested_benchmark_identity(request=request, source_input=source_input)
    portfolio_groups, portfolio_dates, portfolio_labels = _portfolio_groups_by_date(
        request=request,
        source_input=source_input,
    )
    benchmark_groups, benchmark_labels = _benchmark_groups_by_date(request=request, source_input=source_input)
    source_portfolio_returns = _portfolio_source_returns(
        portfolio_input=source_input.portfolio_input,
        portfolio_dates=portfolio_dates,
    )
    _validate_observation_calendars(portfolio_dates=portfolio_dates, benchmark_groups=benchmark_groups)

    rows, aggregate_returns = _aligned_rows_and_aggregates(
        portfolio_groups=portfolio_groups,
        benchmark_groups=benchmark_groups,
        portfolio_dates=portfolio_dates,
        group_labels=_merged_group_labels(benchmark_labels=benchmark_labels, portfolio_labels=portfolio_labels),
        source_portfolio_returns=source_portfolio_returns,
    )
    snapshots = _normalized_snapshots(source_snapshots)
    source_lineage = GroupReturnEvidenceSourceLineage(
        execution_id=request.calculation_id,
        source_cut_id=_source_cut_id(
            request=request,
            benchmark_id=source_input.benchmark_id,
            rows=rows,
            aggregate_returns=aggregate_returns,
            source_snapshots=snapshots,
        ),
        snapshots=snapshots,
    )
    return GroupReturnEvidenceResponse(
        calculation_id=request.calculation_id,
        portfolio_id=request.portfolio_id,
        benchmark_id=source_input.benchmark_id,
        as_of_date=request.as_of_date,
        window=request.window,
        grouping_dimension=request.grouping_dimension,
        reporting_currency=request.reporting_currency,
        return_basis=_RETURN_BASIS,
        valuation_basis=_VALUATION_BASIS,
        weight_basis=_WEIGHT_BASIS,
        coverage=GroupReturnEvidenceCoverage(
            observed_dates=sorted(portfolio_dates),
            reconciliation_tolerance=_GROUP_RECONCILIATION_TOLERANCE,
        ),
        aggregate_returns=aggregate_returns,
        rows=rows,
        source_lineage=source_lineage,
    )


def _validate_common_currency(
    *,
    request: GroupReturnEvidenceRequest,
    source_input: GroupReturnEvidenceSourceInput,
) -> None:
    source_reporting_currency = _uppercase_currency(source_input.portfolio_input.reporting_currency)
    benchmark_currency = _uppercase_currency(source_input.benchmark_currency)
    if source_reporting_currency != request.reporting_currency or benchmark_currency != request.reporting_currency:
        raise ValueError(
            "group return evidence currency mismatch: portfolio and benchmark source economics must both match "
            "the requested reporting_currency; no FX conversion is invented by this endpoint."
        )
    if not source_input.position_source_rows_complete:
        raise ValueError("group return evidence requires complete retained position source rows.")


def _validate_requested_benchmark_identity(
    *,
    request: GroupReturnEvidenceRequest,
    source_input: GroupReturnEvidenceSourceInput,
) -> None:
    if request.benchmark_id is not None and request.benchmark_id != source_input.benchmark_id:
        raise ValueError("resolved benchmark source identity does not match the requested benchmark_id.")


def _portfolio_groups_by_date(
    *,
    request: GroupReturnEvidenceRequest,
    source_input: GroupReturnEvidenceSourceInput,
) -> tuple[dict[date, dict[str, _DailyPortfolioGroup]], set[date], dict[str, str]]:
    portfolio_dates = _portfolio_observation_dates(request=request, portfolio_input=source_input.portfolio_input)
    grouped_totals: dict[date, dict[str, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: _empty_portfolio_totals())
    )
    labels: dict[str, str] = {}
    seen_position_dates: set[tuple[str, date]] = set()

    for row in source_input.position_rows:
        position_id, observation_date = _position_identity_and_date(row)
        _validate_window_date(request=request, observation_date=observation_date, source_name="position")
        if observation_date not in portfolio_dates:
            raise ValueError("position source observation is not present in the portfolio source calendar.")
        identity = (position_id, observation_date)
        if identity in seen_position_dates:
            raise ValueError("duplicate position source observation prevents deterministic group-return evidence.")
        seen_position_dates.add(identity)

        group_id, label = _portfolio_group_identity(request=request, row=row)
        _register_group_label(labels=labels, group_id=group_id, label=label)
        beginning, ending, bod_cash_flow, eod_cash_flow = _portfolio_row_economics(
            row=row,
            portfolio_currency=source_input.portfolio_input.portfolio_currency,
            reporting_currency=request.reporting_currency,
        )
        totals = grouped_totals[observation_date][group_id]
        totals["beginning_capital"] += beginning
        totals["ending_value"] += ending
        totals["bod_cash_flow"] += bod_cash_flow
        totals["eod_cash_flow"] += eod_cash_flow

    if not seen_position_dates:
        raise ValueError("group return evidence requires at least one complete position source observation.")
    _validate_portfolio_source_reconciliation(
        portfolio_input=source_input.portfolio_input,
        portfolio_dates=portfolio_dates,
        grouped_totals=grouped_totals,
    )
    return (
        {
            observation_date: {group_id: _DailyPortfolioGroup(**totals) for group_id, totals in by_group.items()}
            for observation_date, by_group in grouped_totals.items()
        },
        portfolio_dates,
        labels,
    )


def _portfolio_observation_dates(
    *,
    request: GroupReturnEvidenceRequest,
    portfolio_input: StatefulPortfolioInput,
) -> set[date]:
    dates: set[date] = set()
    seen: set[date] = set()
    for observation in portfolio_input.observations:
        raw_date = observation.get("valuation_date")
        observation_date = _source_date(raw_date, source_name="portfolio")
        _validate_window_date(request=request, observation_date=observation_date, source_name="portfolio")
        if observation_date in seen:
            raise ValueError("duplicate portfolio source observation prevents deterministic group-return evidence.")
        seen.add(observation_date)
        _finite_decimal(observation.get("beginning_market_value"), field_name="portfolio beginning_market_value")
        _finite_decimal(observation.get("ending_market_value"), field_name="portfolio ending_market_value")
        dates.add(observation_date)
    if not dates:
        raise ValueError("group return evidence requires portfolio source observations.")
    return dates


def _position_identity_and_date(row: dict[str, object]) -> tuple[str, date]:
    position_id = row.get("source_position_key") or row.get("position_id")
    if not isinstance(position_id, str) or not position_id.strip():
        raise ValueError("position source observation is missing a stable position identity.")
    return position_id, _source_date(row.get("valuation_date"), source_name="position")


def _portfolio_group_identity(
    *,
    request: GroupReturnEvidenceRequest,
    row: dict[str, object],
) -> tuple[str, str]:
    source_field = _GROUP_SOURCE_FIELDS[request.grouping_dimension]
    raw_label: object
    if request.grouping_dimension is GroupReturnEvidenceGrouping.CURRENCY:
        raw_label = row.get("position_currency")
    else:
        dimensions = row.get("dimensions")
        raw_label = dimensions.get(source_field) if isinstance(dimensions, dict) else None
    return _group_identity(grouping=request.grouping_dimension, raw_label=raw_label, source_name="position")


def _portfolio_row_economics(
    *,
    row: dict[str, object],
    portfolio_currency: str | None,
    reporting_currency: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if not isinstance(row.get("cash_flows"), list) or not position_cash_flows_are_losslessly_normalizable(
        row.get("cash_flows"),
        row=row,
        value_basis="reporting",
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    ):
        raise ValueError("position source cash-flow economics are incomplete for reporting-currency group returns.")
    beginning = _finite_decimal(
        row.get("beginning_market_value_reporting_currency"),
        field_name="position beginning_market_value_reporting_currency",
    )
    ending = _finite_decimal(
        row.get("ending_market_value_reporting_currency"),
        field_name="position ending_market_value_reporting_currency",
    )
    bod_cash_flow, eod_cash_flow, _ = split_position_cash_flows_in_value_basis(
        cash_flows_raw=row["cash_flows"],
        row=row,
        value_basis="reporting",
    )
    return beginning, ending, bod_cash_flow, eod_cash_flow


def _validate_portfolio_source_reconciliation(
    *,
    portfolio_input: StatefulPortfolioInput,
    portfolio_dates: set[date],
    grouped_totals: dict[date, dict[str, dict[str, Decimal]]],
) -> None:
    source_values: dict[date, tuple[Decimal, Decimal]] = {}
    for observation in portfolio_input.observations:
        observation_date = _source_date(observation.get("valuation_date"), source_name="portfolio")
        source_values[observation_date] = (
            _finite_decimal(observation.get("beginning_market_value"), field_name="portfolio beginning_market_value"),
            _finite_decimal(observation.get("ending_market_value"), field_name="portfolio ending_market_value"),
        )
    for observation_date in portfolio_dates:
        date_groups = grouped_totals.get(observation_date)
        if not date_groups:
            raise ValueError("portfolio source date has no position evidence.")
        expected_beginning, expected_ending = source_values[observation_date]
        actual_beginning = sum((item["beginning_capital"] for item in date_groups.values()), Decimal("0"))
        actual_ending = sum((item["ending_value"] for item in date_groups.values()), Decimal("0"))
        if (
            abs(actual_beginning - expected_beginning) > _MONEY_RECONCILIATION_TOLERANCE
            or abs(actual_ending - expected_ending) > _MONEY_RECONCILIATION_TOLERANCE
        ):
            raise ValueError("position source values do not reconcile to the portfolio source valuations.")


def _portfolio_source_returns(
    *,
    portfolio_input: StatefulPortfolioInput,
    portfolio_dates: set[date],
) -> dict[date, Decimal]:
    valuation_points = portfolio_timeseries_to_valuation_points(observations=portfolio_input.observations)
    source_returns: dict[date, Decimal] = {}
    for point in valuation_points:
        observation_date = _source_date(point.get("perf_date"), source_name="portfolio")
        beginning = _finite_decimal(point.get("begin_mv"), field_name="portfolio begin_mv")
        ending = _finite_decimal(point.get("end_mv"), field_name="portfolio end_mv")
        bod_cash_flow = _finite_decimal(point.get("bod_cf"), field_name="portfolio bod_cf")
        eod_cash_flow = _finite_decimal(point.get("eod_cf"), field_name="portfolio eod_cf")
        denominator = abs(beginning + bod_cash_flow)
        if denominator == 0:
            raise ValueError("portfolio source has zero capital and cannot provide a group-return aggregate.")
        source_returns[observation_date] = (ending - bod_cash_flow - beginning - eod_cash_flow) / denominator
    if set(source_returns) != portfolio_dates:
        raise ValueError("portfolio return observations do not match the complete position source calendar.")
    return source_returns


def _benchmark_groups_by_date(
    *,
    request: GroupReturnEvidenceRequest,
    source_input: GroupReturnEvidenceSourceInput,
) -> tuple[dict[date, dict[str, _DailyBenchmarkGroup]], dict[str, str]]:
    labels_by_index = _benchmark_labels_by_index(source_input.index_records)
    grouped_totals: dict[date, dict[str, dict[str, Decimal]]] = defaultdict(
        lambda: defaultdict(lambda: {"weight": Decimal("0"), "contribution": Decimal("0")})
    )
    labels: dict[str, str] = {}
    seen_component_dates: set[tuple[str, date]] = set()
    for observation in source_input.benchmark_component_observations:
        observation_date = observation.perf_date
        _validate_window_date(request=request, observation_date=observation_date, source_name="benchmark")
        identity = (observation.component_id, observation_date)
        if identity in seen_component_dates:
            raise ValueError("duplicate benchmark component observation prevents deterministic group-return evidence.")
        seen_component_dates.add(identity)
        group_id, label = _benchmark_group_identity(
            request=request,
            component=observation,
            labels_by_index=labels_by_index,
        )
        _register_group_label(labels=labels, group_id=group_id, label=label)
        weight = _finite_decimal(observation.weight_bop, field_name="benchmark component weight_bop")
        component_return = _finite_decimal(observation.component_return, field_name="benchmark component_return")
        totals = grouped_totals[observation_date][group_id]
        totals["weight"] += weight
        totals["contribution"] += weight * component_return
    if not seen_component_dates:
        raise ValueError("group return evidence requires benchmark component return observations.")
    _validate_benchmark_weight_reconciliation(grouped_totals)
    return (
        {
            observation_date: {group_id: _DailyBenchmarkGroup(**totals) for group_id, totals in by_group.items()}
            for observation_date, by_group in grouped_totals.items()
        },
        labels,
    )


def _benchmark_labels_by_index(index_records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    labels_by_index: dict[str, dict[str, object]] = {}
    for record in index_records:
        index_id = record.get("index_id")
        labels = record.get("classification_labels")
        if isinstance(index_id, str) and index_id and isinstance(labels, dict):
            labels_by_index[index_id] = labels
    return labels_by_index


def _benchmark_group_identity(
    *,
    request: GroupReturnEvidenceRequest,
    component: BenchmarkComponentObservation,
    labels_by_index: dict[str, dict[str, object]],
) -> tuple[str, str]:
    source_field = _GROUP_SOURCE_FIELDS[request.grouping_dimension]
    raw_label: object
    if request.grouping_dimension is GroupReturnEvidenceGrouping.CURRENCY:
        raw_label = component.component_currency
    else:
        labels = labels_by_index.get(component.component_id)
        raw_label = labels.get(source_field) if labels is not None else None
    return _group_identity(grouping=request.grouping_dimension, raw_label=raw_label, source_name="benchmark")


def _group_identity(
    *,
    grouping: GroupReturnEvidenceGrouping,
    raw_label: object,
    source_name: str,
) -> tuple[str, str]:
    if not isinstance(raw_label, str) or not raw_label.strip():
        raise ValueError(f"{source_name} source is missing the requested {grouping.value} classification.")
    label = raw_label.strip()
    canonical = "_".join(label.casefold().split())
    return f"{grouping.value}:{canonical}", label


def _register_group_label(*, labels: dict[str, str], group_id: str, label: str) -> None:
    existing = labels.get(group_id)
    if existing is not None and existing != label:
        raise ValueError("conflicting source labels prevent deterministic group-return evidence.")
    labels[group_id] = label


def _merged_group_labels(*, benchmark_labels: dict[str, str], portfolio_labels: dict[str, str]) -> dict[str, str]:
    labels = dict(benchmark_labels)
    for group_id, label in portfolio_labels.items():
        _register_group_label(labels=labels, group_id=group_id, label=label)
    return labels


def _validate_benchmark_weight_reconciliation(
    grouped_totals: dict[date, dict[str, dict[str, Decimal]]],
) -> None:
    for observation_date, date_groups in grouped_totals.items():
        total_weight = sum((item["weight"] for item in date_groups.values()), Decimal("0"))
        if abs(total_weight - Decimal("1")) > _WEIGHT_RECONCILIATION_TOLERANCE:
            raise ValueError(f"benchmark component weights do not reconcile to one on {observation_date.isoformat()}.")


def _validate_observation_calendars(
    *,
    portfolio_dates: set[date],
    benchmark_groups: dict[date, dict[str, _DailyBenchmarkGroup]],
) -> None:
    if set(benchmark_groups) != portfolio_dates:
        raise ValueError("portfolio and benchmark source calendars are not aligned for group-return evidence.")


def _aligned_rows_and_aggregates(
    *,
    portfolio_groups: dict[date, dict[str, _DailyPortfolioGroup]],
    benchmark_groups: dict[date, dict[str, _DailyBenchmarkGroup]],
    portfolio_dates: set[date],
    group_labels: dict[str, str],
    source_portfolio_returns: dict[date, Decimal],
) -> tuple[list[GroupReturnEvidenceRow], list[GroupReturnEvidenceAggregateReturn]]:
    rows: list[GroupReturnEvidenceRow] = []
    aggregate_returns: list[GroupReturnEvidenceAggregateReturn] = []
    for observation_date in sorted(portfolio_dates):
        portfolio_by_group = portfolio_groups[observation_date]
        benchmark_by_group = benchmark_groups[observation_date]
        total_portfolio_capital = sum(
            (group.beginning_capital + group.bod_cash_flow for group in portfolio_by_group.values()), Decimal("0")
        )
        if total_portfolio_capital <= 0:
            raise ValueError("portfolio beginning capital must be positive for group-return evidence.")
        weighted_portfolio_return = _portfolio_return(portfolio_by_group, total_capital=total_portfolio_capital)
        portfolio_return = source_portfolio_returns[observation_date]
        portfolio_reconciliation_delta = weighted_portfolio_return - portfolio_return
        if abs(portfolio_reconciliation_delta) > _GROUP_RECONCILIATION_TOLERANCE:
            raise ValueError("weighted portfolio group economics do not reconcile to the source portfolio return.")
        benchmark_return = sum((group.contribution for group in benchmark_by_group.values()), Decimal("0"))
        date_rows = _aligned_rows_for_date(
            observation_date=observation_date,
            portfolio_by_group=portfolio_by_group,
            benchmark_by_group=benchmark_by_group,
            total_portfolio_capital=total_portfolio_capital,
            group_labels=group_labels,
        )
        active_return = portfolio_return - benchmark_return
        active_contribution_sum = sum((row.active_contribution for row in date_rows), Decimal("0"))
        group_active_contribution_delta = active_contribution_sum - active_return
        if abs(group_active_contribution_delta) > _GROUP_RECONCILIATION_TOLERANCE:
            raise ValueError("group active contributions do not reconcile to aggregate active return.")
        rows.extend(date_rows)
        aggregate_returns.append(
            GroupReturnEvidenceAggregateReturn(
                date=observation_date,
                portfolio_return=portfolio_return,
                weighted_portfolio_return=weighted_portfolio_return,
                portfolio_reconciliation_delta=portfolio_reconciliation_delta,
                benchmark_return=benchmark_return,
                active_return=active_return,
                group_active_contribution_delta=group_active_contribution_delta,
            )
        )
    return rows, aggregate_returns


def _portfolio_return(
    portfolio_by_group: dict[str, _DailyPortfolioGroup],
    *,
    total_capital: Decimal,
) -> Decimal:
    numerator = sum(
        (
            group.ending_value - group.bod_cash_flow - group.beginning_capital - group.eod_cash_flow
            for group in portfolio_by_group.values()
        ),
        Decimal("0"),
    )
    return numerator / total_capital


def _aligned_rows_for_date(
    *,
    observation_date: date,
    portfolio_by_group: dict[str, _DailyPortfolioGroup],
    benchmark_by_group: dict[str, _DailyBenchmarkGroup],
    total_portfolio_capital: Decimal,
    group_labels: dict[str, str],
) -> list[GroupReturnEvidenceRow]:
    rows: list[GroupReturnEvidenceRow] = []
    for group_id in sorted(set(portfolio_by_group) | set(benchmark_by_group)):
        portfolio_group = portfolio_by_group.get(group_id)
        benchmark_group = benchmark_by_group.get(group_id)
        portfolio_return, portfolio_weight = _portfolio_group_return_and_weight(
            portfolio_group=portfolio_group,
            total_portfolio_capital=total_portfolio_capital,
        )
        benchmark_return, benchmark_weight = _benchmark_group_return_and_weight(benchmark_group=benchmark_group)
        rows.append(
            GroupReturnEvidenceRow(
                date=observation_date,
                group_id=group_id,
                group_label=group_labels[group_id],
                portfolio_group_return=portfolio_return,
                benchmark_group_return=benchmark_return,
                portfolio_weight=portfolio_weight,
                benchmark_weight=benchmark_weight,
                active_contribution=portfolio_weight * portfolio_return - benchmark_weight * benchmark_return,
            )
        )
    return rows


def _portfolio_group_return_and_weight(
    *,
    portfolio_group: _DailyPortfolioGroup | None,
    total_portfolio_capital: Decimal,
) -> tuple[Decimal, Decimal]:
    if portfolio_group is None:
        return Decimal("0"), Decimal("0")
    group_capital = portfolio_group.beginning_capital + portfolio_group.bod_cash_flow
    numerator = (
        portfolio_group.ending_value
        - portfolio_group.bod_cash_flow
        - portfolio_group.beginning_capital
        - portfolio_group.eod_cash_flow
    )
    if group_capital == 0:
        if numerator != 0:
            raise ValueError("zero-capital portfolio group has non-zero return economics.")
        return Decimal("0"), Decimal("0")
    return numerator / group_capital, group_capital / total_portfolio_capital


def _benchmark_group_return_and_weight(
    *,
    benchmark_group: _DailyBenchmarkGroup | None,
) -> tuple[Decimal, Decimal]:
    if benchmark_group is None or benchmark_group.weight == 0:
        return Decimal("0"), Decimal("0")
    return benchmark_group.contribution / benchmark_group.weight, benchmark_group.weight


def _normalized_snapshots(source_snapshots: Iterable[object]) -> list[GroupReturnEvidenceSourceSnapshot]:
    snapshots: list[GroupReturnEvidenceSourceSnapshot] = []
    for source_snapshot in source_snapshots:
        snapshot = _source_snapshot(source_snapshot)
        if not snapshot.retrieval_status.startswith("2"):
            raise ValueError("group return evidence cannot publish a failed upstream source snapshot.")
        snapshots.append(snapshot)
    return sorted(
        snapshots,
        key=lambda item: (
            item.upstream_endpoint,
            item.source_identifier,
            item.request_fingerprint,
            item.response_fingerprint,
        ),
    )


def _source_snapshot(source_snapshot: object) -> GroupReturnEvidenceSourceSnapshot:
    if isinstance(source_snapshot, dict):
        return GroupReturnEvidenceSourceSnapshot.model_validate(source_snapshot)
    return GroupReturnEvidenceSourceSnapshot(
        upstream_endpoint=str(getattr(source_snapshot, "upstream_endpoint")),
        source_identifier=str(getattr(source_snapshot, "source_identifier")),
        as_of_date=str(getattr(source_snapshot, "as_of_date")),
        request_fingerprint=str(getattr(source_snapshot, "request_fingerprint")),
        response_fingerprint=str(getattr(source_snapshot, "response_fingerprint")),
        retrieval_status=str(getattr(source_snapshot, "retrieval_status")),
    )


def _source_cut_id(
    *,
    request: GroupReturnEvidenceRequest,
    benchmark_id: str,
    rows: list[GroupReturnEvidenceRow],
    aggregate_returns: list[GroupReturnEvidenceAggregateReturn],
    source_snapshots: list[GroupReturnEvidenceSourceSnapshot],
) -> str:
    payload = {
        "contract_version": "v1",
        "portfolio_id": request.portfolio_id,
        "benchmark_id": benchmark_id,
        "as_of_date": request.as_of_date.isoformat(),
        "window": request.window.model_dump(mode="json"),
        "grouping_dimension": request.grouping_dimension.value,
        "reporting_currency": request.reporting_currency,
        "return_basis": _RETURN_BASIS,
        "valuation_basis": _VALUATION_BASIS,
        "weight_basis": _WEIGHT_BASIS,
        "source_snapshots": [
            {
                "upstream_endpoint": item.upstream_endpoint,
                "source_identifier": item.source_identifier,
                "as_of_date": item.as_of_date.isoformat(),
                "request_fingerprint": item.request_fingerprint,
                "response_fingerprint": item.response_fingerprint,
                "retrieval_status": item.retrieval_status,
            }
            for item in source_snapshots
        ],
        "aggregate_returns": [
            {
                "date": item.date.isoformat(),
                "portfolio_return": _decimal_text(item.portfolio_return),
                "weighted_portfolio_return": _decimal_text(item.weighted_portfolio_return),
                "portfolio_reconciliation_delta": _decimal_text(item.portfolio_reconciliation_delta),
                "benchmark_return": _decimal_text(item.benchmark_return),
                "active_return": _decimal_text(item.active_return),
                "group_active_contribution_delta": _decimal_text(item.group_active_contribution_delta),
            }
            for item in aggregate_returns
        ],
        "rows": [
            {
                "date": item.date.isoformat(),
                "group_id": item.group_id,
                "group_label": item.group_label,
                "portfolio_group_return": _decimal_text(item.portfolio_group_return),
                "benchmark_group_return": _decimal_text(item.benchmark_group_return),
                "portfolio_weight": _decimal_text(item.portfolio_weight),
                "benchmark_weight": _decimal_text(item.benchmark_weight),
                "active_contribution": _decimal_text(item.active_contribution),
            }
            for item in rows
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _source_date(value: object, *, source_name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{source_name} source observation is missing an ISO business date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{source_name} source observation has an invalid ISO business date.") from exc


def _validate_window_date(
    *,
    request: GroupReturnEvidenceRequest,
    observation_date: date,
    source_name: str,
) -> None:
    if not request.window.start_date <= observation_date <= request.window.end_date:
        raise ValueError(f"{source_name} source observation falls outside the requested window.")


def _finite_decimal(value: object, *, field_name: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite decimal.") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal.")
    return decimal_value


def _uppercase_currency(value: object) -> str | None:
    return value if isinstance(value, str) and value == value.upper() and len(value) == 3 else None


def _empty_portfolio_totals() -> dict[str, Decimal]:
    return {
        "beginning_capital": Decimal("0"),
        "ending_value": Decimal("0"),
        "bod_cash_flow": Decimal("0"),
        "eod_cash_flow": Decimal("0"),
    }


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
