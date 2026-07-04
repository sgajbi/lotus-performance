from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.mwr_analytics_requests import MoneyWeightedReturnAnalyticsRequest, MWRInputMode
from app.services.mwr_mode_service import resolve_mwr_request
from app.services.stateful_mwr_input_service import (
    MWRCashFlowEvidenceComponent,
    _add_stateful_mwr_cash_flow_component,
    _carry_forward_mwr_cash_flow_component,
    _collect_stateful_mwr_cash_flows,
    _eligible_source_mwr_cash_flow_amount,
    _observation_cash_flow_currency_matches_reporting,
    _parse_decimal,
    _portfolio_currency_matches_reporting,
    _source_mwr_cash_flow_component,
    _stateful_mwr_cash_flow_projection,
    _stateful_mwr_market_value_evidence,
    _StatefulMWRCashFlowCollection,
    _StatefulMWRSourceCashFlowQualityAccumulator,
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
    assert normalized.currency_evidence.source_cashflow_quality is not None
    assert normalized.currency_evidence.source_cashflow_quality.observed_source_row_count == 3
    assert normalized.currency_evidence.source_cashflow_quality.included_source_row_count == 3
    assert normalized.currency_evidence.source_cashflow_quality.excluded_source_row_count == 0


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


def test_stateful_mwr_market_value_evidence_projects_boundary_values_and_conversion_status():
    evidence = _stateful_mwr_market_value_evidence(
        first_observation={"valuation_date": "2025-01-01"},
        last_observation={"valuation_date": "2025-12-31"},
        begin_mv=Decimal("1000.25"),
        end_mv=Decimal("1125.50"),
        reporting_currency="CHF",
        single_currency_inputs=True,
    )

    assert [item.valuation_date for item in evidence] == [date(2025, 1, 1), date(2025, 12, 31)]
    assert [item.amount for item in evidence] == [Decimal("1000.25"), Decimal("1125.50")]
    assert [item.currency for item in evidence] == ["CHF", "CHF"]
    assert [item.value_role for item in evidence] == ["beginning_market_value", "ending_market_value"]
    assert [item.conversion_status for item in evidence] == [
        "no_conversion_required",
        "no_conversion_required",
    ]

    preconverted = _stateful_mwr_market_value_evidence(
        first_observation={"valuation_date": "2025-01-01"},
        last_observation={"valuation_date": "2025-12-31"},
        begin_mv=Decimal("1000.25"),
        end_mv=Decimal("1125.50"),
        reporting_currency="CHF",
        single_currency_inputs=False,
    )

    assert [item.conversion_status for item in preconverted] == [
        "upstream_preconverted",
        "upstream_preconverted",
    ]


def test_observation_cash_flow_currency_matches_reporting_ignores_missing_currency_and_compares_case_insensitive():
    assert _observation_cash_flow_currency_matches_reporting(
        observation={"cash_flow_currency": "eur"},
        reporting_currency="EUR",
    )
    assert _observation_cash_flow_currency_matches_reporting(
        observation={},
        reporting_currency="EUR",
    )
    assert not _observation_cash_flow_currency_matches_reporting(
        observation={"cash_flow_currency": "USD"},
        reporting_currency="EUR",
    )


def test_portfolio_currency_matches_reporting_requires_both_values_and_compares_case_insensitive():
    assert _portfolio_currency_matches_reporting(
        source_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="eur",
            observations=[],
        ),
        reporting_currency="EUR",
    )
    assert not _portfolio_currency_matches_reporting(
        source_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="USD",
            observations=[],
        ),
        reporting_currency="EUR",
    )
    assert not _portfolio_currency_matches_reporting(
        source_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency=None,
            observations=[],
        ),
        reporting_currency="EUR",
    )
    assert not _portfolio_currency_matches_reporting(
        source_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            observations=[],
        ),
        reporting_currency=None,
    )


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


def test_carry_forward_mwr_cash_flow_component_projects_only_non_zero_capital_breaks():
    component = _carry_forward_mwr_cash_flow_component(
        beginning_market_value=Decimal("1250"),
        previous_ending_market_value=Decimal("1010"),
        reporting_currency="USD",
    )

    assert component == MWRCashFlowEvidenceComponent(
        component_type="carry_forward_adjustment",
        amount=Decimal("240"),
        currency="USD",
    )
    assert (
        _carry_forward_mwr_cash_flow_component(
            beginning_market_value=Decimal("1010"),
            previous_ending_market_value=Decimal("1010"),
            reporting_currency="USD",
        )
        is None
    )
    assert (
        _carry_forward_mwr_cash_flow_component(
            beginning_market_value=None,
            previous_ending_market_value=Decimal("1010"),
            reporting_currency="USD",
        )
        is None
    )


def test_stateful_mwr_cash_flow_projection_keeps_sorted_non_zero_flows_and_evidence():
    component = MWRCashFlowEvidenceComponent(
        component_type="source_cash_flow",
        amount=Decimal("25"),
        currency="USD",
    )

    projection = _stateful_mwr_cash_flow_projection(
        cash_flow_collection=_StatefulMWRCashFlowCollection(
            cash_flows_by_date={
                date(2025, 1, 3): Decimal("0"),
                date(2025, 1, 2): Decimal("-5"),
                date(2025, 1, 1): Decimal("25"),
            },
            cash_flow_components_by_date={date(2025, 1, 1): [component]},
        ),
        reporting_currency="USD",
    )

    assert [(cash_flow.date, cash_flow.amount) for cash_flow in projection.cash_flows] == [
        (date(2025, 1, 1), 25.0),
        (date(2025, 1, 2), -5.0),
    ]
    assert [evidence.date for evidence in projection.cashflow_evidence] == [
        date(2025, 1, 1),
        date(2025, 1, 2),
    ]
    assert projection.cashflow_evidence[0].source_components == [component]
    assert projection.cashflow_evidence[1].source_components == []


def test_add_stateful_mwr_cash_flow_component_accumulates_amount_and_evidence():
    cash_flows_by_date: dict[date, Decimal] = {}
    cash_flow_components_by_date: dict[date, list[MWRCashFlowEvidenceComponent]] = {}
    valuation_date = date(2025, 1, 2)

    _add_stateful_mwr_cash_flow_component(
        cash_flows_by_date=cash_flows_by_date,
        cash_flow_components_by_date=cash_flow_components_by_date,
        valuation_date=valuation_date,
        component=MWRCashFlowEvidenceComponent(
            component_type="source_cash_flow",
            amount=Decimal("100"),
            currency="USD",
        ),
    )
    _add_stateful_mwr_cash_flow_component(
        cash_flows_by_date=cash_flows_by_date,
        cash_flow_components_by_date=cash_flow_components_by_date,
        valuation_date=valuation_date,
        component=MWRCashFlowEvidenceComponent(
            component_type="carry_forward_adjustment",
            amount=Decimal("-25"),
            currency="USD",
        ),
    )

    assert cash_flows_by_date == {valuation_date: Decimal("75")}
    assert [component.component_type for component in cash_flow_components_by_date[valuation_date]] == [
        "source_cash_flow",
        "carry_forward_adjustment",
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
    assert collection.source_cashflow_quality.observed_source_row_count == 3
    assert collection.source_cashflow_quality.included_source_row_count == 1
    assert collection.source_cashflow_quality.excluded_source_row_count == 2
    assert collection.source_cashflow_quality.observed_economics_role_counts == {
        "external": 1,
        "fee": 1,
        "unsupported": 1,
    }
    assert collection.source_cashflow_quality.exclusion_counts == {
        "fee_or_operational": 1,
        "unsupported_or_income_like": 1,
    }
    assert "SOURCE_CASHFLOW_ROWS_EXCLUDED" in collection.source_cashflow_quality.reason_codes


def test_source_mwr_cash_flow_component_projects_eligible_source_flow():
    component = _source_mwr_cash_flow_component(
        {
            "amount": "100",
            "cash_flow_type": "external_flow",
            "flow_scope": "external",
            "source_classification": "official",
        },
        reporting_currency="USD",
    )

    assert component is not None
    assert component.amount == Decimal("100")
    assert component.currency == "USD"
    assert component.cash_flow_type == "external_flow"
    assert component.flow_scope == "external"
    assert component.source_classification == "official"
    assert component.lifecycle_identity_status == "not_supplied_by_source"
    numeric_metadata_component = _source_mwr_cash_flow_component(
        {
            "amount": "25",
            "cash_flow_type": "external_flow",
            "flow_scope": 123,
        },
        reporting_currency="USD",
    )
    assert numeric_metadata_component is not None
    assert numeric_metadata_component.flow_scope == "123"
    assert numeric_metadata_component.source_classification is None
    assert _source_mwr_cash_flow_component({"amount": "-3", "cash_flow_type": "fee"}, reporting_currency="USD") is None


def test_source_mwr_cash_flow_component_preserves_source_lifecycle_identity():
    component = _source_mwr_cash_flow_component(
        {
            "amount": "100",
            "cash_flow_type": "external_flow",
            "transaction_id": "TXN-001",
            "event_id": "EVT-001",
            "lifecycle_status": "corrected",
            "correction_id": "CORR-001",
            "reversal_id": "REV-001",
            "cancellation_id": "CAN-001",
            "trade_date": "2025-01-02",
            "settlement_date": "2025-01-04",
            "effective_date": "2025-01-01",
            "posting_date": "2025-01-03",
        },
        reporting_currency="USD",
    )

    assert component is not None
    assert component.source_transaction_id == "TXN-001"
    assert component.source_event_id == "EVT-001"
    assert component.lifecycle_status == "corrected"
    assert component.correction_reference_id == "CORR-001"
    assert component.reversal_reference_id == "REV-001"
    assert component.cancellation_reference_id == "CAN-001"
    assert component.trade_date == date(2025, 1, 2)
    assert component.settlement_date == date(2025, 1, 4)
    assert component.effective_date == date(2025, 1, 1)
    assert component.posting_date == date(2025, 1, 3)
    assert component.lifecycle_identity_status == "available"


def test_eligible_source_mwr_cash_flow_amount_records_quality_reasons():
    source_quality = _StatefulMWRSourceCashFlowQualityAccumulator()

    assert _eligible_source_mwr_cash_flow_amount(
        flow={"amount": "25.5", "cash_flow_type": "external_flow"},
        source_quality=source_quality,
    ) == Decimal("25.5")
    assert (
        _eligible_source_mwr_cash_flow_amount(
            flow={"cash_flow_type": "external_flow"},
            source_quality=source_quality,
        )
        is None
    )
    assert (
        _eligible_source_mwr_cash_flow_amount(
            flow={"amount": "bad", "cash_flow_type": "external_flow"},
            source_quality=source_quality,
        )
        is None
    )
    assert (
        _eligible_source_mwr_cash_flow_amount(
            flow={"amount": "-3", "cash_flow_type": "fee"},
            source_quality=source_quality,
        )
        is None
    )

    assert source_quality.to_evidence().observed_economics_role_counts == {
        "external": 1,
        "fee": 1,
    }
    assert source_quality.to_evidence().exclusion_counts == {
        "fee_or_operational": 1,
        "invalid_amount": 1,
        "missing_amount": 1,
    }


def test_stateful_mwr_cash_flow_projection_aggregates_same_date_but_keeps_source_components():
    collection = _collect_stateful_mwr_cash_flows(
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
                "cash_flows": [
                    {
                        "amount": "100",
                        "cash_flow_type": "external_flow",
                        "transaction_id": "TXN-001",
                        "event_id": "EVT-001",
                    },
                    {
                        "amount": "-25",
                        "cash_flow_type": "external_flow",
                        "transaction_id": "TXN-002",
                        "event_id": "EVT-002",
                        "lifecycle_status": "reversal",
                        "reversal_id": "TXN-001",
                    },
                ],
            }
        ],
        reporting_currency="USD",
    )
    projection = _stateful_mwr_cash_flow_projection(
        cash_flow_collection=collection,
        reporting_currency="USD",
    )

    assert [(cash_flow.date, cash_flow.amount) for cash_flow in projection.cash_flows] == [(date(2025, 1, 1), 75.0)]
    components = projection.cashflow_evidence[0].source_components
    assert [component.source_transaction_id for component in components] == ["TXN-001", "TXN-002"]
    assert components[1].reversal_reference_id == "TXN-001"
    assert collection.source_cashflow_quality.included_source_row_count == 2


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
    assert normalized.currency_evidence.source_cashflow_quality is not None
    assert normalized.currency_evidence.source_cashflow_quality.exclusion_counts == {
        "invalid_cash_flow_collection": 1,
        "invalid_observation_date": 1,
        "missing_amount": 1,
    }


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
    completed: list[tuple[tuple, dict]] = []
    monkeypatch.setattr("app.services.mwr_mode_service.execution_registry.start_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.services.mwr_mode_service.execution_registry.complete_stage",
        lambda *args, **kwargs: completed.append((args, kwargs)),
    )
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
    assert completed[0][0][1] == "retrieval"
    assert completed[0][1]["details"] == {
        "portfolio_observations": 2,
        "portfolio_chunk_count": 1,
        "portfolio_page_count": 1,
    }
    assert completed[1][0][1] == "normalization"
    assert completed[1][1]["details"] == {"cashflows": 1}


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
    assert resolved.currency_evidence is None


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
