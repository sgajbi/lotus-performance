from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.contribution_requests import PortfolioData, PositionData
from app.services.position_source_service import parse_stateful_position_timeseries_payload
from app.services.source_cashflow_taxonomy import classify_cashflow_type
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_performance_input_service import (
    StatefulPortfolioInput,
    retrieve_stateful_portfolio_input,
)
from app.services.stateful_position_row_service import (
    PositionValueBasis,
    split_position_cash_flows_in_value_basis,
)
from app.services.stateful_upstream_errors import stateful_control_plane_unavailable_detail
from app.services.valuation_points_service import portfolio_timeseries_to_valuation_points


@dataclass(frozen=True)
class StatefulContributionSourceInput:
    portfolio_input: StatefulPortfolioInput
    position_rows: list[dict[str, object]]
    position_retrieval_metadata: RetrievalMetadata


@dataclass(frozen=True)
class StatefulContributionNormalizedInput:
    portfolio_data: PortfolioData
    positions_data: list[PositionData]


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
        dimensions=dimensions,
        include_cash_flows=include_cash_flows,
        filters=filters,
    )
    if upstream_status >= status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=stateful_control_plane_unavailable_detail(
                source_label="stateful position timeseries source",
                upstream_status=upstream_status,
            ),
        )

    position_source = parse_stateful_position_timeseries_payload(upstream_payload)
    return StatefulContributionSourceInput(
        portfolio_input=portfolio_input,
        position_rows=position_source.rows,
        position_retrieval_metadata=_parse_retrieval_metadata(upstream_payload),
    )


def build_stateful_contribution_input(
    *,
    source_input: StatefulContributionSourceInput,
    metric_basis: str,
    currency_mode: str | None,
    fx: object,
    reporting_currency: str | None,
) -> StatefulContributionNormalizedInput:
    normalized_currency_mode = currency_mode or "BASE_ONLY"
    if normalized_currency_mode == "BOTH":
        _validate_stateful_both_currency_support(
            rows=source_input.position_rows,
            reporting_currency=reporting_currency,
            fx=fx,
        )

    portfolio_valuation_points = portfolio_timeseries_to_valuation_points(
        observations=source_input.portfolio_input.observations
    )
    portfolio_data = PortfolioData.model_validate(
        {
            "metric_basis": metric_basis,
            "valuation_points": portfolio_valuation_points,
        }
    )

    positions_by_id: dict[str, list[dict[str, object]]] = {}
    position_meta: dict[str, dict[str, object]] = {}
    for row in source_input.position_rows:
        position_id_raw = row.get("position_id")
        valuation_date = row.get("valuation_date")
        if not isinstance(position_id_raw, str) or not isinstance(valuation_date, str):
            continue
        point = _position_row_to_daily_point(
            row=row,
            currency_mode=normalized_currency_mode,
            reporting_currency=reporting_currency,
        )
        if point is None:
            continue
        positions_by_id.setdefault(position_id_raw, []).append(point)
        position_meta[position_id_raw] = _position_meta_from_row(row)

    positions_data = [
        PositionData.model_validate(
            {
                "position_id": position_id,
                "meta": position_meta.get(position_id, {}),
                "valuation_points": valuation_points,
            }
        )
        for position_id, valuation_points in sorted(positions_by_id.items())
    ]

    return StatefulContributionNormalizedInput(
        portfolio_data=portfolio_data,
        positions_data=positions_data,
    )


def _position_row_to_daily_point(
    *,
    row: dict[str, object],
    currency_mode: str,
    reporting_currency: str | None,
) -> dict[str, object] | None:
    valuation_date = row.get("valuation_date")
    if not isinstance(valuation_date, str):
        return None
    value_basis: PositionValueBasis

    if currency_mode == "LOCAL_ONLY":
        begin_value = row.get("beginning_market_value_position_currency")
        end_value = row.get("ending_market_value_position_currency")
        value_basis = "position"
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

    bod_cf, eod_cf, mgmt_fees = split_position_cash_flows_in_value_basis(
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
        "mgmt_fees": mgmt_fees,
    }


def _split_position_cash_flows(cash_flows_raw: object) -> tuple[Decimal, Decimal, Decimal]:
    bod_cf = Decimal("0")
    eod_cf = Decimal("0")
    mgmt_fees = Decimal("0")
    if not isinstance(cash_flows_raw, list):
        return bod_cf, eod_cf, mgmt_fees

    for flow in cash_flows_raw:
        if not isinstance(flow, dict):
            continue
        amount = flow.get("amount")
        timing = flow.get("timing")
        cash_flow_type = flow.get("cash_flow_type")
        if amount is None or timing not in {"bod", "eod"}:
            continue
        decimal_amount = Decimal(str(amount))
        if cash_flow_type == "fee":
            mgmt_fees += decimal_amount
        if timing == "bod":
            bod_cf += decimal_amount
        else:
            eod_cf += decimal_amount
    return bod_cf, eod_cf, mgmt_fees


def _position_meta_from_row(row: dict[str, object]) -> dict[str, object]:
    meta: dict[str, object] = {}
    security_id = row.get("security_id")
    if isinstance(security_id, str):
        meta["security_id"] = security_id
    position_currency = row.get("position_currency")
    if isinstance(position_currency, str) and position_currency:
        meta["currency"] = position_currency
    cash_flow_currency = row.get("cash_flow_currency")
    if isinstance(cash_flow_currency, str) and cash_flow_currency:
        meta["cash_flow_currency"] = cash_flow_currency
    position_to_portfolio_fx_rate = row.get("position_to_portfolio_fx_rate")
    if position_to_portfolio_fx_rate is not None:
        meta["position_to_portfolio_fx_rate"] = Decimal(str(position_to_portfolio_fx_rate))
    portfolio_to_reporting_fx_rate = row.get("portfolio_to_reporting_fx_rate")
    if portfolio_to_reporting_fx_rate is not None:
        meta["portfolio_to_reporting_fx_rate"] = Decimal(str(portfolio_to_reporting_fx_rate))

    dimensions_raw = row.get("dimensions")
    if isinstance(dimensions_raw, dict):
        for key, value in dimensions_raw.items():
            if isinstance(key, str) and value is not None:
                meta[key] = value
    meta["_source_economics"] = _position_source_economics_from_row(row)
    return meta


def _position_source_economics_from_row(row: dict[str, object]) -> dict[str, object]:
    cash_flow_type_counts: dict[str, int] = {}
    cash_flows_raw = row.get("cash_flows")
    if isinstance(cash_flows_raw, list):
        for flow in cash_flows_raw:
            if not isinstance(flow, dict):
                continue
            classification = classify_cashflow_type(flow.get("cash_flow_type"))
            key = classification.normalized_value or "missing"
            cash_flow_type_counts[key] = cash_flow_type_counts.get(key, 0) + 1

    return {
        "cash_flow_type_counts": dict(sorted(cash_flow_type_counts.items())),
        "valuation_status": row.get("valuation_status"),
        "source_contract": "PositionTimeseriesInput:v1",
    }


def _validate_stateful_both_currency_support(
    *,
    rows: list[dict[str, object]],
    reporting_currency: str | None,
    fx: object,
) -> None:
    if not reporting_currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Stateful contribution input requires report_ccy when currency_mode=BOTH.",
        )

    position_currencies = {
        str(position_currency)
        for row in rows
        for position_currency in [row.get("position_currency")]
        if isinstance(position_currency, str) and position_currency
    }
    if not position_currencies:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Stateful contribution input requires position_currency on lotus-core position-timeseries rows "
                "when currency_mode=BOTH."
            ),
        )

    if any(position_currency != reporting_currency for position_currency in position_currencies) and fx is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Stateful contribution input requires fx.rates when currency_mode=BOTH and sourced positions "
                "include currencies different from report_ccy."
            ),
        )


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
