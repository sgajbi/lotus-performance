from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TypeGuard
from uuid import UUID

from app.core.config import Settings
from app.models.contribution_requests import (
    SOURCE_HIERARCHY_MEMBERSHIPS_META_KEY,
    PortfolioData,
    PositionData,
)
from app.services.currency_code_normalization import normalized_currency_code
from app.services.position_source_service import parse_stateful_position_timeseries_payload
from app.services.source_cashflow_taxonomy import classify_cashflow_type
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_performance_input_service import (
    StatefulPortfolioInput,
    retrieve_stateful_portfolio_input,
)
from app.services.stateful_position_currency_support import (
    stateful_both_currency_requires_fx as _shared_stateful_both_currency_requires_fx,
)
from app.services.stateful_position_currency_support import (
    stateful_position_currencies as _shared_stateful_position_currencies,
)
from app.services.stateful_position_currency_support import (
    validate_stateful_both_currency_support,
)
from app.services.stateful_position_row_service import (
    PositionValueBasis,
    position_cash_flows_are_losslessly_normalizable,
    split_position_cash_flows_in_value_basis,
)
from app.services.stateful_retrieval_metadata import parse_retrieval_metadata
from app.services.stateful_upstream_errors import raise_for_stateful_control_plane_unavailable
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points
from core.errors import APIUnprocessableEntityError


@dataclass(frozen=True)
class StatefulContributionSourceInput:
    portfolio_input: StatefulPortfolioInput
    position_rows: list[dict[str, object]]
    position_retrieval_metadata: RetrievalMetadata
    performance_component_economics_payload: dict[str, object] | None = None
    performance_component_economics_status: int | None = None
    position_source_rows_complete: bool = False


@dataclass(frozen=True)
class _StatefulContributionPositionSource:
    rows: list[dict[str, object]]
    retrieval_metadata: RetrievalMetadata
    source_rows_complete: bool


@dataclass(frozen=True)
class _StatefulContributionComponentEconomicsSource:
    status_code: int | None
    payload: dict[str, object] | None


@dataclass(frozen=True)
class _StatefulContributionSourceRequest:
    settings: Settings
    stateful_input_service: StatefulInputService
    calculation_id: UUID | None
    portfolio_id: str
    as_of_date: date
    report_start_date: date
    report_end_date: date
    reporting_currency: str | None
    consumer_system: str
    dimensions: list[str]
    include_cash_flows: bool
    filters: dict[str, object]


@dataclass(frozen=True)
class StatefulContributionNormalizedInput:
    portfolio_data: PortfolioData
    positions_data: list[PositionData]
    portfolio_currency: str | None = None
    reporting_currency: str | None = None
    valuation_currency: str | None = None
    source_preconverted_cash_flow_conversion: bool = False
    source_position_window_complete: bool = False


@dataclass(frozen=True)
class _StatefulContributionPositionSeries:
    valuation_points_by_position_id: dict[str, list[dict[str, object]]]
    meta_by_position_id: dict[str, dict[str, object]]
    source_rows_complete: bool


@dataclass(frozen=True)
class _PositionValueInputs:
    begin_value: object
    end_value: object
    value_basis: PositionValueBasis


async def retrieve_stateful_contribution_source_input(
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
    dimensions: list[str],
    include_cash_flows: bool,
    filters: dict[str, object],
) -> StatefulContributionSourceInput:
    source_request = _StatefulContributionSourceRequest(
        settings=settings,
        stateful_input_service=stateful_input_service,
        calculation_id=calculation_id,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        report_start_date=report_start_date,
        report_end_date=report_end_date,
        reporting_currency=reporting_currency,
        consumer_system=consumer_system,
        dimensions=dimensions,
        include_cash_flows=include_cash_flows,
        filters=filters,
    )

    portfolio_input = await _retrieve_stateful_contribution_portfolio_input(source_request)
    position_source = await _retrieve_stateful_contribution_position_source(source_request)
    component_economics_source = await _retrieve_performance_component_economics_source(source_request)
    return StatefulContributionSourceInput(
        portfolio_input=portfolio_input,
        position_rows=position_source.rows,
        position_retrieval_metadata=position_source.retrieval_metadata,
        performance_component_economics_payload=component_economics_source.payload,
        performance_component_economics_status=component_economics_source.status_code,
        position_source_rows_complete=position_source.source_rows_complete,
    )


async def _retrieve_stateful_contribution_portfolio_input(
    source_request: _StatefulContributionSourceRequest,
) -> StatefulPortfolioInput:
    return await retrieve_stateful_portfolio_input(
        settings=source_request.settings,
        stateful_input_service=source_request.stateful_input_service,
        calculation_id=source_request.calculation_id,
        portfolio_id=source_request.portfolio_id,
        as_of_date=source_request.as_of_date,
        start_date=source_request.report_start_date,
        end_date=source_request.report_end_date,
        reporting_currency=source_request.reporting_currency,
        consumer_system=source_request.consumer_system,
    )


async def _retrieve_stateful_contribution_position_source(
    source_request: _StatefulContributionSourceRequest,
) -> _StatefulContributionPositionSource:
    upstream_status, upstream_payload = await source_request.stateful_input_service.get_position_timeseries(
        calculation_id=source_request.calculation_id,
        portfolio_id=source_request.portfolio_id,
        as_of_date=source_request.as_of_date,
        start_date=source_request.report_start_date,
        end_date=source_request.report_end_date,
        reporting_currency=source_request.reporting_currency,
        consumer_system=source_request.consumer_system,
        dimensions=source_request.dimensions,
        include_cash_flows=source_request.include_cash_flows,
        filters=source_request.filters,
    )
    raise_for_stateful_control_plane_unavailable(
        source_label="stateful position timeseries source",
        upstream_status=upstream_status,
    )

    position_source = parse_stateful_position_timeseries_payload(upstream_payload)
    return _StatefulContributionPositionSource(
        rows=position_source.rows,
        retrieval_metadata=parse_retrieval_metadata(upstream_payload),
        source_rows_complete=_position_source_rows_complete(
            payload=upstream_payload,
            retained_row_count=len(position_source.rows),
        ),
    )


async def _retrieve_performance_component_economics_source(
    source_request: _StatefulContributionSourceRequest,
) -> _StatefulContributionComponentEconomicsSource:
    status_code, payload = await source_request.stateful_input_service.get_performance_component_economics(
        calculation_id=source_request.calculation_id,
        portfolio_id=source_request.portfolio_id,
        as_of_date=source_request.as_of_date,
        start_date=source_request.report_start_date,
        end_date=source_request.report_end_date,
        security_ids=_security_ids_filter(source_request.filters),
    )
    return _StatefulContributionComponentEconomicsSource(
        status_code=status_code,
        payload=payload,
    )


def build_stateful_contribution_input(
    *,
    source_input: StatefulContributionSourceInput,
    metric_basis: str,
    currency_mode: str | None,
    fx: object,
    reporting_currency: str | None,
    portfolio_base_currency: str | None = None,
) -> StatefulContributionNormalizedInput:
    normalized_currency_mode = currency_mode or "BASE_ONLY"
    if normalized_currency_mode == "BOTH":
        _validate_stateful_both_currency_support(
            rows=source_input.position_rows,
            reporting_currency=reporting_currency,
            fx=fx,
        )

    valuation_currency = _stateful_base_only_valuation_currency(
        source_input=source_input,
        currency_mode=normalized_currency_mode,
        requested_reporting_currency=reporting_currency,
        fallback_portfolio_currency=portfolio_base_currency,
    )
    resolved_portfolio_currency = normalized_currency_code(
        getattr(source_input.portfolio_input, "portfolio_currency", None)
    ) or normalized_currency_code(portfolio_base_currency)

    position_series = _stateful_contribution_position_series(
        rows=source_input.position_rows,
        currency_mode=normalized_currency_mode,
        portfolio_currency=resolved_portfolio_currency,
        reporting_currency=_stateful_position_reporting_currency(
            source_input=source_input,
            currency_mode=normalized_currency_mode,
            valuation_currency=valuation_currency,
            requested_reporting_currency=reporting_currency,
        ),
        performance_component_economics_payload=getattr(
            source_input,
            "performance_component_economics_payload",
            None,
        ),
        performance_component_economics_status=getattr(
            source_input,
            "performance_component_economics_status",
            None,
        ),
    )

    return StatefulContributionNormalizedInput(
        portfolio_data=_stateful_contribution_portfolio_data(
            source_input=source_input,
            metric_basis=metric_basis,
        ),
        positions_data=_stateful_contribution_positions_data(position_series),
        portfolio_currency=resolved_portfolio_currency,
        reporting_currency=getattr(source_input.portfolio_input, "reporting_currency", None),
        valuation_currency=valuation_currency,
        source_preconverted_cash_flow_conversion=_stateful_has_source_preconverted_cash_flow_conversion(
            rows=source_input.position_rows,
            portfolio_currency=resolved_portfolio_currency,
        ),
        source_position_window_complete=(
            getattr(source_input, "position_source_rows_complete", False) and position_series.source_rows_complete
        ),
    )


def _position_source_rows_complete(
    *,
    payload: dict[str, object],
    retained_row_count: int,
) -> bool:
    metadata = payload.get("retrieval_metadata")
    if not isinstance(metadata, dict):
        return False
    source_row_count = _non_negative_int_or_none(metadata.get("source_row_count"))
    declared_retained_row_count = _non_negative_int_or_none(metadata.get("retained_row_count"))
    discarded_source_row_count = _non_negative_int_or_none(metadata.get("discarded_source_row_count"))
    return (
        source_row_count is not None
        and declared_retained_row_count == retained_row_count
        and discarded_source_row_count == 0
        and source_row_count >= retained_row_count
    )


def _non_negative_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _stateful_position_reporting_currency(
    *,
    source_input: StatefulContributionSourceInput,
    currency_mode: str,
    valuation_currency: str | None,
    requested_reporting_currency: str | None,
) -> str | None:
    if currency_mode != "BASE_ONLY":
        return requested_reporting_currency
    source_reporting_currency = normalized_currency_code(
        getattr(source_input.portfolio_input, "reporting_currency", None)
    )
    return source_reporting_currency if valuation_currency == source_reporting_currency else None


def _stateful_base_only_valuation_currency(
    *,
    source_input: StatefulContributionSourceInput,
    currency_mode: str,
    requested_reporting_currency: str | None,
    fallback_portfolio_currency: str | None = None,
) -> str | None:
    """Return Core's selected valuation denomination without relabelling a fallback value pair."""
    portfolio_currency = normalized_currency_code(
        getattr(source_input.portfolio_input, "portfolio_currency", None)
    ) or normalized_currency_code(fallback_portfolio_currency)
    reporting_currency = normalized_currency_code(getattr(source_input.portfolio_input, "reporting_currency", None))
    requested_currency = normalized_currency_code(requested_reporting_currency)
    if currency_mode != "BASE_ONLY":
        return portfolio_currency
    if requested_currency is None:
        return portfolio_currency
    _require_matching_stateful_reporting_currency(
        reporting_currency=reporting_currency,
        requested_currency=requested_currency,
    )
    if reporting_currency is None:
        return portfolio_currency
    if reporting_currency == portfolio_currency:
        _require_complete_stateful_reporting_cash_flow_conversion(
            rows=source_input.position_rows,
            portfolio_currency=portfolio_currency,
            reporting_currency=reporting_currency,
        )
        return portfolio_currency

    incomplete_rows = _incomplete_stateful_reporting_value_rows(source_input.position_rows)
    if incomplete_rows:
        raise APIUnprocessableEntityError(
            detail=(
                "Stateful contribution BASE_ONLY cannot publish Core reporting-currency valuation evidence "
                "when a position lacks a complete reporting value pair: " + ", ".join(incomplete_rows) + "."
            ),
            error_code="REPORTING_CURRENCY_VALUATIONS_INCOMPLETE",
        )
    _require_complete_stateful_reporting_cash_flow_conversion(
        rows=source_input.position_rows,
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    )
    return reporting_currency


def _require_matching_stateful_reporting_currency(
    *,
    reporting_currency: str | None,
    requested_currency: str,
) -> None:
    if reporting_currency is not None and reporting_currency != requested_currency:
        raise APIUnprocessableEntityError(
            detail="Stateful contribution source reporting_currency does not match requested report_ccy.",
            error_code="SOURCE_REPORTING_CURRENCY_MISMATCH",
        )


def _incomplete_stateful_reporting_value_rows(rows: list[dict[str, object]]) -> list[str]:
    return [
        _stateful_position_row_identity(row, index=index)
        for index, row in enumerate(rows)
        if _stateful_row_is_consumed_for_reporting_valuation(row) and _stateful_row_lacks_reporting_value_pair(row)
    ]


def _stateful_row_lacks_reporting_value_pair(row: dict[str, object]) -> bool:
    if not isinstance(row.get("valuation_date"), str):
        return False
    return (
        row.get("beginning_market_value_reporting_currency") is None
        or row.get("ending_market_value_reporting_currency") is None
    )


def _stateful_position_row_identity(row: dict[str, object], *, index: int) -> str:
    for field_name in ("position_id", "security_id"):
        value = row.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"row[{index}]"


def _incomplete_stateful_reporting_cash_flow_conversion_rows(
    *,
    rows: list[dict[str, object]],
    portfolio_currency: str | None,
    reporting_currency: str,
) -> list[str]:
    return [
        _stateful_position_row_identity(row, index=index)
        for index, row in enumerate(rows)
        if _stateful_row_is_consumed_for_reporting_valuation(row)
        and _stateful_row_lacks_required_reporting_cash_flow_rates(
            row=row,
            portfolio_currency=portfolio_currency,
            reporting_currency=reporting_currency,
        )
    ]


def _require_complete_stateful_reporting_cash_flow_conversion(
    *,
    rows: list[dict[str, object]],
    portfolio_currency: str | None,
    reporting_currency: str,
) -> None:
    incomplete_rows = _incomplete_stateful_reporting_cash_flow_conversion_rows(
        rows=rows,
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    )
    if incomplete_rows:
        raise APIUnprocessableEntityError(
            detail=(
                "Stateful contribution BASE_ONLY cannot publish Core reporting-currency valuation evidence "
                "when nonzero position-currency cash flows lack required source FX rates: "
                + ", ".join(incomplete_rows)
                + "."
            ),
            error_code="REPORTING_CURRENCY_CASH_FLOW_FX_INCOMPLETE",
        )


def _stateful_row_lacks_required_reporting_cash_flow_rates(
    *,
    row: dict[str, object],
    portfolio_currency: str | None,
    reporting_currency: str,
) -> bool:
    position_currency = normalized_currency_code(row.get("position_currency"))
    if not _stateful_row_has_nonzero_timed_cash_flow(row):
        return False
    cash_flow_currency = normalized_currency_code(row.get("cash_flow_currency"))
    if position_currency is None or cash_flow_currency is None or cash_flow_currency != position_currency:
        return True
    return (
        position_currency != portfolio_currency and not _is_positive_decimal(row.get("position_to_portfolio_fx_rate"))
    ) or (
        portfolio_currency != reporting_currency and not _is_positive_decimal(row.get("portfolio_to_reporting_fx_rate"))
    )


def _stateful_row_is_consumed_for_reporting_valuation(row: dict[str, object]) -> bool:
    position_id = row.get("position_id")
    valuation_date = row.get("valuation_date")
    return (
        isinstance(position_id, str)
        and isinstance(valuation_date, str)
        and _position_value_inputs(
            row=row,
            currency_mode="BASE_ONLY",
            reporting_currency="reporting",
        )
        is not None
    )


def _stateful_row_has_nonzero_timed_cash_flow(row: dict[str, object]) -> bool:
    cash_flows = row.get("cash_flows")
    if not isinstance(cash_flows, list):
        return False
    return any(
        isinstance(flow, dict)
        and flow.get("timing") in {"bod", "eod"}
        and flow.get("amount") is not None
        and Decimal(str(flow["amount"])) != 0
        and classify_cashflow_type(flow.get("cash_flow_type")).economics_role != "unsupported"
        for flow in cash_flows
    )


def _stateful_has_source_preconverted_cash_flow_conversion(
    *,
    rows: list[dict[str, object]],
    portfolio_currency: str | None,
) -> bool:
    """Whether consumed flow evidence used Core's position-to-base conversion."""
    return any(
        _stateful_row_is_consumed_for_reporting_valuation(row)
        and _stateful_row_has_nonzero_timed_cash_flow(row)
        and normalized_currency_code(row.get("position_currency")) not in {None, portfolio_currency}
        for row in rows
    )


def _is_positive_decimal(value: object) -> bool:
    if value is None:
        return False
    try:
        parsed = Decimal(str(value))
        return parsed.is_finite() and parsed > 0
    except ArithmeticError:
        return False


def _stateful_contribution_portfolio_data(
    *,
    source_input: StatefulContributionSourceInput,
    metric_basis: str,
) -> PortfolioData:
    return PortfolioData.model_validate(
        {
            "metric_basis": metric_basis,
            "valuation_points": portfolio_timeseries_to_valuation_points(
                observations=source_input.portfolio_input.observations
            ),
        }
    )


def _stateful_contribution_positions_data(
    position_series: _StatefulContributionPositionSeries,
) -> list[PositionData]:
    return [
        PositionData.model_validate(
            {
                "position_id": position_id,
                "meta": position_series.meta_by_position_id.get(position_id, {}),
                "valuation_points": position_series.valuation_points_by_position_id.get(position_id, []),
            }
        )
        for position_id in sorted(position_series.meta_by_position_id)
    ]


def _stateful_contribution_position_series(
    *,
    rows: list[dict[str, object]],
    currency_mode: str,
    portfolio_currency: str | None = None,
    reporting_currency: str | None = None,
    performance_component_economics_payload: dict[str, object] | None = None,
    performance_component_economics_status: int | None = None,
) -> _StatefulContributionPositionSeries:
    positions_by_id: dict[str, list[dict[str, object]]] = {}
    position_meta: dict[str, dict[str, object]] = {}
    latest_source_meta: dict[str, dict[str, object]] = {}
    source_memberships: dict[str, list[dict[str, object]]] = {}
    cash_flow_currencies_by_position_id: dict[str, set[str]] = {}
    normalized_row_count = 0
    for row in rows:
        position_id_raw = row.get("position_id")
        valuation_date = row.get("valuation_date")
        if not isinstance(position_id_raw, str) or not isinstance(valuation_date, str):
            continue
        normalized_position_id = _source_position_key_or_position_id(row, position_id_raw)
        row_meta = _position_meta_from_row(
            row,
            normalized_position_id=normalized_position_id,
            performance_component_economics_payload=performance_component_economics_payload,
            performance_component_economics_status=performance_component_economics_status,
        )
        latest_source_meta[normalized_position_id] = row_meta
        source_memberships.setdefault(normalized_position_id, []).append(
            _source_hierarchy_membership_from_row(row, valuation_date=valuation_date)
        )
        point = _position_row_to_daily_point(
            row=row,
            currency_mode=currency_mode,
            reporting_currency=reporting_currency,
        )
        if point is None:
            continue
        if _position_row_cash_flows_are_losslessly_normalized(
            row,
            currency_mode=currency_mode,
            portfolio_currency=portfolio_currency,
            reporting_currency=reporting_currency,
        ):
            normalized_row_count += 1
        positions_by_id.setdefault(normalized_position_id, []).append(point)
        position_meta[normalized_position_id] = row_meta
        _record_position_cash_flow_currency(
            row=row,
            normalized_position_id=normalized_position_id,
            currencies_by_position_id=cash_flow_currencies_by_position_id,
        )
    for position_id, memberships in source_memberships.items():
        position_meta.setdefault(position_id, latest_source_meta[position_id])[
            SOURCE_HIERARCHY_MEMBERSHIPS_META_KEY
        ] = memberships
    for position_id, currencies in cash_flow_currencies_by_position_id.items():
        position_meta[position_id]["_source_cash_flow_currencies"] = sorted(currencies)
    return _StatefulContributionPositionSeries(
        valuation_points_by_position_id=positions_by_id,
        meta_by_position_id=position_meta,
        source_rows_complete=normalized_row_count == len(rows),
    )


def _position_row_cash_flows_are_losslessly_normalized(
    row: dict[str, object],
    *,
    currency_mode: str,
    portfolio_currency: str | None,
    reporting_currency: str | None,
) -> bool:
    if "cash_flows" not in row:
        return True
    value_inputs = _position_value_inputs(
        row=row,
        currency_mode=currency_mode,
        reporting_currency=reporting_currency,
    )
    return value_inputs is not None and position_cash_flows_are_losslessly_normalizable(
        row.get("cash_flows"),
        row=row,
        value_basis=value_inputs.value_basis,
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    )


def _source_hierarchy_membership_from_row(
    row: dict[str, object],
    *,
    valuation_date: str,
) -> dict[str, object]:
    membership: dict[str, object] = {"perf_date": valuation_date}
    position_currency = row.get("position_currency")
    if isinstance(position_currency, str) and position_currency:
        membership["currency"] = position_currency
    membership.update(_normalized_position_dimensions(row.get("dimensions")))
    return membership


def _record_position_cash_flow_currency(
    *,
    row: dict[str, object],
    normalized_position_id: str,
    currencies_by_position_id: dict[str, set[str]],
) -> None:
    if not _stateful_row_has_nonzero_timed_cash_flow(row):
        return
    cash_flow_currency = normalized_currency_code(row.get("cash_flow_currency"))
    if cash_flow_currency is not None:
        currencies_by_position_id.setdefault(normalized_position_id, set()).add(cash_flow_currency)


def _position_row_to_daily_point(
    *,
    row: dict[str, object],
    currency_mode: str,
    reporting_currency: str | None,
) -> dict[str, object] | None:
    valuation_date = row.get("valuation_date")
    if not isinstance(valuation_date, str):
        return None
    value_inputs = _position_value_inputs(
        row=row,
        currency_mode=currency_mode,
        reporting_currency=reporting_currency,
    )
    if value_inputs is None:
        return None

    bod_cf, eod_cf, mgmt_fees = split_position_cash_flows_in_value_basis(
        cash_flows_raw=row.get("cash_flows"),
        row=row,
        value_basis=value_inputs.value_basis,
    )
    return {
        "perf_date": valuation_date,
        "begin_mv": Decimal(str(value_inputs.begin_value)),
        "end_mv": Decimal(str(value_inputs.end_value)),
        "bod_cf": bod_cf,
        "eod_cf": eod_cf,
        "mgmt_fees": mgmt_fees,
    }


def _position_value_inputs(
    *,
    row: dict[str, object],
    currency_mode: str,
    reporting_currency: str | None,
) -> _PositionValueInputs | None:
    if currency_mode == "LOCAL_ONLY":
        begin_value = row.get("beginning_market_value_position_currency")
        end_value = row.get("ending_market_value_position_currency")
        value_basis: PositionValueBasis = "position"
    elif reporting_currency is not None:
        begin_value, end_value = _reporting_position_value_pair(row)
        value_basis = "reporting"
    else:
        begin_value = row.get("beginning_market_value_portfolio_currency")
        end_value = row.get("ending_market_value_portfolio_currency")
        value_basis = "portfolio"

    if begin_value is None or end_value is None:
        return None
    return _PositionValueInputs(
        begin_value=begin_value,
        end_value=end_value,
        value_basis=value_basis,
    )


def _reporting_position_value_pair(row: dict[str, object]) -> tuple[object, object]:
    begin_value = row.get("beginning_market_value_reporting_currency")
    end_value = row.get("ending_market_value_reporting_currency")
    if begin_value is None or end_value is None:
        return (
            row.get("beginning_market_value_portfolio_currency"),
            row.get("ending_market_value_portfolio_currency"),
        )
    return begin_value, end_value


def _position_meta_from_row(
    row: dict[str, object],
    *,
    normalized_position_id: str | None = None,
    performance_component_economics_payload: dict[str, object] | None = None,
    performance_component_economics_status: int | None = None,
) -> dict[str, object]:
    meta = _position_contract_meta_from_row(row)
    meta.update(_position_source_grain_meta(row, normalized_position_id=normalized_position_id))
    meta.update(_normalized_position_dimensions(row.get("dimensions")))
    meta["_source_economics"] = _position_source_economics_from_row(
        row,
        performance_component_economics_payload=performance_component_economics_payload,
        performance_component_economics_status=performance_component_economics_status,
    )
    return meta


def _source_position_key_or_position_id(row: dict[str, object], position_id: str) -> str:
    source_position_key = row.get("source_position_key")
    if isinstance(source_position_key, str) and source_position_key:
        return source_position_key
    return position_id


def _position_source_grain_meta(
    row: dict[str, object],
    *,
    normalized_position_id: str | None,
) -> dict[str, object]:
    meta: dict[str, object] = {}
    source_position_key = row.get("source_position_key")
    if isinstance(source_position_key, str) and source_position_key:
        meta["source_position_key"] = source_position_key

    business_position_id = row.get("position_id")
    if _is_distinct_business_position_id(
        business_position_id,
        normalized_position_id=normalized_position_id,
    ):
        meta["business_position_id"] = business_position_id
    return meta


def _is_distinct_business_position_id(
    business_position_id: object,
    *,
    normalized_position_id: str | None,
) -> bool:
    return (
        normalized_position_id is not None
        and isinstance(business_position_id, str)
        and bool(business_position_id)
        and business_position_id != normalized_position_id
    )


def _normalized_position_dimensions(dimensions_raw: object) -> dict[str, object]:
    if not isinstance(dimensions_raw, dict):
        return {}
    return {key: value for key, value in dimensions_raw.items() if isinstance(key, str) and value is not None}


def _position_contract_meta_from_row(row: dict[str, object]) -> dict[str, object]:
    meta: dict[str, object] = {}
    security_id = row.get("security_id")
    if isinstance(security_id, str):
        meta["security_id"] = security_id

    for source_field, target_field in (
        ("position_currency", "currency"),
        ("cash_flow_currency", "cash_flow_currency"),
    ):
        value = row.get(source_field)
        if isinstance(value, str) and value:
            meta[target_field] = value

    meta.update(_position_contract_fx_rate_meta(row))
    return meta


def _position_contract_fx_rate_meta(row: dict[str, object]) -> dict[str, object]:
    meta: dict[str, object] = {}
    for fx_rate_field in (
        "position_to_portfolio_fx_rate",
        "portfolio_to_reporting_fx_rate",
    ):
        value = row.get(fx_rate_field)
        if value is not None:
            meta[fx_rate_field] = Decimal(str(value))
    return meta


def _position_source_economics_from_row(
    row: dict[str, object],
    *,
    performance_component_economics_payload: dict[str, object] | None = None,
    performance_component_economics_status: int | None = None,
) -> dict[str, object]:
    source_economics: dict[str, object] = {
        "cash_flow_type_counts": _source_cash_flow_type_counts(row.get("cash_flows")),
        "valuation_status": row.get("valuation_status"),
        "source_contract": "PositionTimeseriesInput:v1",
    }
    if performance_component_economics_payload is not None:
        source_economics["performance_component_economics"] = _performance_component_economics_context(
            row=row,
            payload=performance_component_economics_payload,
            status_code=performance_component_economics_status,
        )
    return source_economics


def _source_cash_flow_type_counts(cash_flows_raw: object) -> dict[str, int]:
    if not isinstance(cash_flows_raw, list):
        return {}

    cash_flow_type_counts: dict[str, int] = {}
    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            continue
        classification = classify_cashflow_type(flow.get("cash_flow_type"))
        key = classification.normalized_value or "missing"
        cash_flow_type_counts[key] = cash_flow_type_counts.get(key, 0) + 1
    return dict(sorted(cash_flow_type_counts.items()))


def _performance_component_economics_context(
    *,
    row: dict[str, object] | None = None,
    payload: dict[str, object],
    status_code: int | None,
) -> dict[str, object]:
    supportability_raw = payload.get("supportability")
    supportability = supportability_raw if isinstance(supportability_raw, dict) else {}
    source_rows = _performance_component_economics_source_rows_for_position(row=row, payload=payload)
    return {
        "source_contract": "PerformanceComponentEconomics:v1",
        "retrieval_status": status_code,
        "supportability_state": _string_value(supportability.get("state")),
        "supportability_reason": _string_value(supportability.get("reason")),
        "source_verdicts": supportability.get("source_verdicts")
        if isinstance(supportability.get("source_verdicts"), list)
        else [],
        "source_row_count": _non_negative_int(supportability.get("source_row_count")),
        "position_source_row_count": len(source_rows),
        "source_rows": source_rows,
        "component_totals_scope": _string_value(payload.get("component_totals_scope")),
        "lineage": payload.get("lineage") if isinstance(payload.get("lineage"), dict) else {},
        "request_fingerprints": _string_values(payload.get("request_fingerprints")),
        "retrieval_metadata": payload.get("retrieval_metadata")
        if isinstance(payload.get("retrieval_metadata"), dict)
        else {},
        "observed_component_families": _string_values(supportability.get("observed_component_families")),
        "missing_component_families": _string_values(supportability.get("missing_component_families")),
        "supported_component_families": _string_values(supportability.get("supported_component_families")),
    }


def _performance_component_economics_source_rows_for_position(
    *,
    row: dict[str, object] | None,
    payload: dict[str, object],
) -> list[dict[str, object]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    security_id = _position_security_id(row)
    source_rows = [
        source_row
        for source_row in rows
        if _is_performance_component_economics_source_row(source_row, security_id=security_id)
    ]
    return sorted(source_rows, key=_performance_component_economics_source_row_sort_key)


def _position_security_id(row: dict[str, object] | None) -> str | None:
    if row is None:
        return None
    return _string_value(row.get("security_id"))


def _is_performance_component_economics_source_row(
    value: object,
    *,
    security_id: str | None,
) -> TypeGuard[dict[str, object]]:
    if not isinstance(value, dict):
        return False
    return security_id is None or _string_value(value.get("security_id")) == security_id


def _performance_component_economics_source_row_sort_key(
    source_row: dict[str, object],
) -> tuple[str, str, str]:
    return (
        _string_value(source_row.get("security_id")) or "",
        _string_value(source_row.get("transaction_date")) or "",
        _string_value(source_row.get("transaction_id")) or "",
    )


def _security_ids_filter(filters: dict[str, object]) -> list[str] | None:
    return _source_security_ids_filter(filters.get("security_ids"))


def _source_security_ids_filter(security_ids_raw: object) -> list[str] | None:
    if not isinstance(security_ids_raw, list):
        return None
    normalized = sorted(set(filter(_is_non_empty_string, security_ids_raw)))
    return normalized or None


def _is_non_empty_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _non_negative_int(value: object) -> int:
    if type(value) is int and value > 0:
        return value
    return 0


def _validate_stateful_both_currency_support(
    *,
    rows: list[dict[str, object]],
    reporting_currency: str | None,
    fx: object,
) -> None:
    validate_stateful_both_currency_support(
        rows=rows,
        reporting_currency=reporting_currency,
        fx=fx,
        workflow_name="contribution",
    )


def _stateful_both_currency_requires_fx(
    *,
    position_currencies: set[str],
    reporting_currency: str,
) -> bool:
    return _shared_stateful_both_currency_requires_fx(
        position_currencies=position_currencies,
        reporting_currency=reporting_currency,
    )


def _stateful_position_currencies(rows: list[dict[str, object]]) -> set[str]:
    return _shared_stateful_position_currencies(rows)
