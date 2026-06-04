from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.services.mwr_mode_service import resolve_mwr_request
from app.services.stateful_mwr_input_service import (
    _collect_stateful_mwr_cash_flows,
    _parse_decimal,
    build_stateful_mwr_input,
    build_stateful_mwr_input_for_window,
)
from app.services.stateful_performance_input_service import StatefulPortfolioInput


def test_build_stateful_mwr_input_aggregates_cash_flows():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        portfolio_currency="EUR",
        reporting_currency="USD",
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1110",
                "cash_flow_currency": "USD",
                "cash_flows": [
                    {
                        "amount": "100",
                        "timing": "bod",
                        "cash_flow_type": "external_flow",
                        "flow_scope": "external",
                        "source_classification": "CONTRIBUTION",
                    },
                    {"amount": "10", "timing": "eod"},
                ],
            },
            {
                "valuation_date": "2025-01-02",
                "beginning_market_value": "1110",
                "ending_market_value": "1120",
                "cash_flow_currency": "USD",
                "cash_flows": [{"amount": "-20", "timing": "bod"}],
            },
        ],
    )

    normalized = build_stateful_mwr_input(source_input=source_input)

    assert normalized.start_date == date(2025, 1, 1)
    assert normalized.begin_mv == Decimal("1000")
    assert normalized.end_mv == Decimal("1120")
    assert [(cash_flow.date.isoformat(), cash_flow.amount) for cash_flow in normalized.cash_flows] == [
        ("2025-01-01", 110.0),
        ("2025-01-02", -20.0),
    ]
    assert normalized.currency_evidence.reporting_currency == "USD"
    assert normalized.currency_evidence.portfolio_currency == "EUR"
    assert normalized.currency_evidence.currency_mode == "SINGLE_REPORTING_CURRENCY"
    assert normalized.currency_evidence.conversion_evidence_reason_codes == [
        "UPSTREAM_PORTFOLIO_TIMESERIES_PRECONVERTED",
        "PER_INPUT_FX_METADATA_NOT_EXPOSED_BY_SOURCE_CONTRACT",
    ]
    assert [item.value_role for item in normalized.currency_evidence.market_values_used] == [
        "beginning_market_value",
        "ending_market_value",
    ]
    assert normalized.currency_evidence.cashflow_evidence[0].source_components[0].source_classification == (
        "CONTRIBUTION"
    )


def test_build_stateful_mwr_input_for_window_uses_requested_window_start():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2024, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-10",
                "beginning_market_value": "1000",
                "ending_market_value": "1005",
                "cash_flows": [],
            },
            {
                "valuation_date": "2025-01-31",
                "beginning_market_value": "1005",
                "ending_market_value": "1010",
                "cash_flows": [],
            },
        ],
    )

    normalized = build_stateful_mwr_input_for_window(
        source_input=source_input,
        window_start_date=date(2025, 1, 10),
    )

    assert normalized.start_date == date(2025, 1, 10)


def test_build_stateful_mwr_input_marks_single_currency_fx_conversion_not_required():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        portfolio_currency="EUR",
        reporting_currency="EUR",
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1110",
                "cash_flow_currency": "EUR",
                "cash_flows": [{"amount": "100", "timing": "bod"}],
            },
            {
                "valuation_date": "2025-01-03",
                "beginning_market_value": "1110",
                "ending_market_value": "1120",
                "cash_flow_currency": "EUR",
                "cash_flows": [],
            },
        ],
    )

    normalized = build_stateful_mwr_input(source_input=source_input)

    assert normalized.currency_evidence.conversion_evidence_status == "not_required_single_currency_inputs"
    assert normalized.currency_evidence.conversion_evidence_reason_codes == [
        "SOURCE_AND_REPORTING_CURRENCY_MATCH",
        "PER_INPUT_FX_CONVERSION_NOT_REQUIRED",
        "MWR_ENGINE_CALCULATED_REPORTING_CURRENCY_SCHEDULE",
    ]
    assert [item.conversion_status for item in normalized.currency_evidence.market_values_used] == [
        "no_conversion_required",
        "no_conversion_required",
    ]


def test_build_stateful_mwr_input_keeps_fx_metadata_gap_when_cash_flow_currency_differs():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        portfolio_currency="EUR",
        reporting_currency="EUR",
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1110",
                "cash_flow_currency": "USD",
                "cash_flows": [{"amount": "100", "timing": "bod"}],
            },
            {
                "valuation_date": "2025-01-03",
                "beginning_market_value": "1110",
                "ending_market_value": "1120",
                "cash_flow_currency": "EUR",
                "cash_flows": [],
            },
        ],
    )

    normalized = build_stateful_mwr_input(source_input=source_input)

    assert normalized.currency_evidence.conversion_evidence_status == (
        "upstream_preconverted_missing_per_input_fx_metadata"
    )
    assert [item.conversion_status for item in normalized.currency_evidence.market_values_used] == [
        "upstream_preconverted",
        "upstream_preconverted",
    ]


def test_build_stateful_mwr_input_captures_carry_forward_capital_breaks():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [],
            },
            {
                "valuation_date": "2025-01-02",
                "beginning_market_value": "1250",
                "ending_market_value": "1260",
                "cash_flows": [{"amount": "-25", "timing": "eod"}],
            },
            {
                "valuation_date": "2025-01-03",
                "beginning_market_value": "1260",
                "ending_market_value": "1270",
                "cash_flows": [],
            },
        ],
    )

    normalized = build_stateful_mwr_input(source_input=source_input)

    assert [(cash_flow.date.isoformat(), cash_flow.amount) for cash_flow in normalized.cash_flows] == [
        ("2025-01-02", 215.0),
    ]


def test_collect_stateful_mwr_cash_flows_combines_external_flows_and_carry_forward_adjustments():
    collection = _collect_stateful_mwr_cash_flows(
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [{"amount": "100", "cash_flow_type": "external_flow"}],
            },
            {
                "valuation_date": "2025-01-02",
                "beginning_market_value": "1250",
                "ending_market_value": "1260",
                "cash_flows": [{"amount": "-25"}],
            },
        ],
        reporting_currency="USD",
    )

    assert collection.cash_flows_by_date == {
        date(2025, 1, 1): Decimal("100"),
        date(2025, 1, 2): Decimal("215"),
    }
    assert [component.component_type for component in collection.cash_flow_components_by_date[date(2025, 1, 2)]] == [
        "carry_forward_adjustment",
        "source_cash_flow",
    ]


def test_build_stateful_mwr_input_excludes_operational_fees_from_capital_flows():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [
                    {"amount": "100", "timing": "bod", "cash_flow_type": "external_flow"},
                    {"amount": "-3", "timing": "eod", "cash_flow_type": "fee"},
                    {"amount": "2", "timing": "eod", "cash_flow_type": "dividend"},
                ],
            },
            {
                "valuation_date": "2025-01-02",
                "beginning_market_value": "1025",
                "ending_market_value": "1030",
                "cash_flows": [],
            },
        ],
    )

    normalized = build_stateful_mwr_input(source_input=source_input)

    assert [(cash_flow.date.isoformat(), cash_flow.amount) for cash_flow in normalized.cash_flows] == [
        ("2025-01-01", 100.0),
        ("2025-01-02", 15.0),
    ]


def test_collect_stateful_mwr_cash_flows_excludes_fee_and_unsupported_economics():
    collection = _collect_stateful_mwr_cash_flows(
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [
                    {"amount": "100", "cash_flow_type": "external_flow"},
                    {"amount": "-3", "cash_flow_type": "fee"},
                    {"amount": "2", "cash_flow_type": "dividend"},
                ],
            }
        ],
        reporting_currency="USD",
    )

    assert collection.cash_flows_by_date == {date(2025, 1, 1): Decimal("100")}
    assert len(collection.cash_flow_components_by_date[date(2025, 1, 1)]) == 1


def test_build_stateful_mwr_input_skips_invalid_cash_flow_rows():
    source_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1005",
                "cash_flows": "bad",
            },
            {
                "valuation_date": 1,
                "beginning_market_value": "1005",
                "ending_market_value": "1010",
                "cash_flows": [{"amount": "10", "timing": "bod"}],
            },
            {
                "valuation_date": "2025-01-03",
                "beginning_market_value": "1010",
                "ending_market_value": "1015",
                "cash_flows": [{"amount": None, "timing": "bod"}],
            },
        ],
    )

    normalized = build_stateful_mwr_input(source_input=source_input)

    assert normalized.cash_flows == []


def test_parse_decimal_handles_none_and_invalid_values():
    assert _parse_decimal(None) is None
    assert _parse_decimal("not-a-decimal") is None


@pytest.mark.asyncio
async def test_resolve_mwr_request_uses_stateful_portfolio_window(monkeypatch):
    async def _mock_retrieve_stateful_portfolio_input(**kwargs):
        assert kwargs["start_date"] == date(2025, 1, 1)
        assert kwargs["end_date"] == date(2025, 1, 3)
        return StatefulPortfolioInput(
            performance_start_date=date(2024, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1110",
                    "cash_flow_currency": "USD",
                    "cash_flows": [{"amount": "100", "timing": "bod"}],
                },
                {
                    "valuation_date": "2025-01-03",
                    "beginning_market_value": "1110",
                    "ending_market_value": "1125",
                    "cash_flow_currency": "USD",
                    "cash_flows": [],
                },
            ],
        )

    monkeypatch.setattr(
        "app.services.mwr_mode_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.start_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.complete_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.fail_stage", lambda *args, **kwargs: None)

    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "MWR_STATEFUL",
            "as_of": "2025-01-03",
            "mwr_method": "XIRR",
            "input_mode": "stateful",
            "stateful_input": {
                "window_start_date": "2025-01-01",
            },
        }
    )

    settings = type("Settings", (), {})()
    resolved = await resolve_mwr_request(request, settings=settings)

    assert resolved.input_mode == MWRInputMode.STATEFUL
    assert resolved.mwr_request.start_date == date(2025, 1, 1)
    assert resolved.mwr_request.begin_mv == 1000
    assert resolved.mwr_request.end_mv == 1125
    assert len(resolved.mwr_request.cash_flows) == 1
    assert resolved.currency_evidence is not None
    assert resolved.currency_evidence.reporting_currency == "USD"


@pytest.mark.asyncio
async def test_resolve_mwr_request_passthroughs_stateless_mode():
    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "portfolio_id": "MWR_STATELESS",
            "as_of": "2025-01-03",
            "input_mode": "stateless",
            "stateless_input": {
                "begin_mv": 1000,
                "end_mv": 1125,
                "cash_flows": [{"amount": 100, "date": "2025-01-01"}],
            },
        }
    )

    resolved = await resolve_mwr_request(request, settings=type("Settings", (), {})())

    assert resolved.input_mode == MWRInputMode.STATELESS
    assert resolved.mwr_request.begin_mv == 1000


@pytest.mark.asyncio
async def test_resolve_mwr_request_fails_retrieval_stage(monkeypatch):
    async def _boom(**kwargs):  # noqa: ARG001
        raise HTTPException(status_code=503, detail="source unavailable")

    failed: list[tuple] = []
    monkeypatch.setattr("app.services.mwr_mode_service.retrieve_stateful_portfolio_input", _boom)
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.start_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.complete_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.mwr_mode_service.execution_registry.fail_stage",
        lambda *args, **kwargs: failed.append(args),
    )

    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "MWR_STATEFUL",
            "as_of": "2025-01-03",
            "input_mode": "stateful",
            "stateful_input": {
                "window_start_date": "2025-01-01",
            },
        }
    )

    with pytest.raises(HTTPException, match="source unavailable"):
        await resolve_mwr_request(request, settings=type("Settings", (), {})())

    assert failed and failed[0][1] == "retrieval"


@pytest.mark.asyncio
async def test_resolve_mwr_request_fails_normalization_stage(monkeypatch):
    async def _mock_retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
        return StatefulPortfolioInput(
            performance_start_date=date(2024, 1, 1),
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1110",
                    "cash_flows": [],
                }
            ],
        )

    failed: list[tuple] = []
    monkeypatch.setattr(
        "app.services.mwr_mode_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    monkeypatch.setattr(
        "app.services.mwr_mode_service.build_stateful_mwr_input_for_window",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad normalization")),
    )
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.start_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.complete_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.mwr_mode_service.execution_registry.fail_stage",
        lambda *args, **kwargs: failed.append(args),
    )

    request = MoneyWeightedReturnAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "MWR_STATEFUL",
            "as_of": "2025-01-03",
            "input_mode": "stateful",
            "stateful_input": {
                "window_start_date": "2025-01-01",
            },
        }
    )

    with pytest.raises(ValueError, match="bad normalization"):
        await resolve_mwr_request(request, settings=type("Settings", (), {})())

    assert failed and failed[0][1] == "normalization"
