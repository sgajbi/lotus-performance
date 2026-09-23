from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.contribution_service import (
    _source_cash_flow_currencies,
    _source_preconverted_cash_flow_pairs_for_position,
)
from app.services.stateful_contribution_input_service import (
    StatefulContributionSourceInput,
    _position_contract_fx_rate_meta,
    _position_contract_meta_from_row,
    _position_meta_from_row,
    _position_row_to_daily_point,
    _position_source_economics_from_row,
    _position_value_inputs,
    _reporting_position_value_pair,
    _security_ids_filter,
    _stateful_base_only_valuation_currency,
    _stateful_both_currency_requires_fx,
    _stateful_contribution_portfolio_data,
    _stateful_contribution_position_series,
    _stateful_contribution_positions_data,
    _stateful_position_currencies,
    build_stateful_contribution_input,
    retrieve_stateful_contribution_source_input,
)
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_performance_input_service import StatefulPortfolioInput
from core.errors import APIError


class _ContributionInputServiceStub:
    def __init__(
        self,
        status_code: int = 200,
        payload: dict[str, object] | None = None,
        component_status_code: int = 200,
        component_payload: dict[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload or {"rows": []}
        self.component_status_code = component_status_code
        self.component_payload = component_payload or {
            "supportability": {
                "state": "UNAVAILABLE",
                "reason": "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE",
                "source_row_count": 0,
                "observed_component_families": [],
                "missing_component_families": [],
                "supported_component_families": [],
            }
        }
        self.calls: list[dict[str, object]] = []
        self.component_calls: list[dict[str, object]] = []

    async def get_position_timeseries(self, **kwargs):
        self.calls.append(kwargs)
        return self.status_code, self.payload

    async def get_performance_component_economics(self, **kwargs):
        self.component_calls.append(kwargs)
        return self.component_status_code, self.component_payload


@pytest.mark.asyncio
async def test_retrieve_stateful_contribution_source_input_returns_rows_and_metadata(monkeypatch):
    portfolio_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
            }
        ],
    )

    portfolio_calls: list[dict[str, object]] = []

    async def _mock_retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
        portfolio_calls.append(kwargs)
        return portfolio_input

    monkeypatch.setattr(
        "app.services.stateful_contribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    service = _ContributionInputServiceStub(
        payload={
            "rows": [
                {
                    "position_id": "POS_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                },
                "ignored",
            ],
            "retrieval_metadata": {
                "chunk_count": 2,
                "page_count": 3,
                "source_row_count": 2,
                "retained_row_count": 1,
                "discarded_source_row_count": 1,
            },
        }
    )

    result = await retrieve_stateful_contribution_source_input(
        settings=object(),
        stateful_input_service=service,
        calculation_id=uuid4(),
        portfolio_id="P1",
        as_of_date=date(2025, 1, 1),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["sector"],
        include_cash_flows=False,
        filters={"security_ids": ["SEC_1"]},
    )

    assert result.portfolio_input is portfolio_input
    assert portfolio_calls[0]["portfolio_id"] == "P1"
    assert portfolio_calls[0]["start_date"] == date(2025, 1, 1)
    assert portfolio_calls[0]["end_date"] == date(2025, 1, 1)
    assert portfolio_calls[0]["reporting_currency"] == "USD"
    assert portfolio_calls[0]["consumer_system"] == "lotus-performance"
    assert len(result.position_rows) == 1
    assert result.position_retrieval_metadata == RetrievalMetadata(chunk_count=2, page_count=3)
    assert result.position_source_rows_complete is False
    assert service.calls[0]["portfolio_id"] == "P1"
    assert service.calls[0]["start_date"] == date(2025, 1, 1)
    assert service.calls[0]["end_date"] == date(2025, 1, 1)
    assert service.calls[0]["reporting_currency"] == "USD"
    assert service.calls[0]["consumer_system"] == "lotus-performance"
    assert service.calls[0]["dimensions"] == ["sector"]
    assert service.calls[0]["include_cash_flows"] is False
    assert result.performance_component_economics_status == 200
    assert result.performance_component_economics_payload is service.component_payload
    assert service.component_calls[0]["portfolio_id"] == "P1"
    assert service.component_calls[0]["start_date"] == date(2025, 1, 1)
    assert service.component_calls[0]["end_date"] == date(2025, 1, 1)
    assert service.component_calls[0]["security_ids"] == ["SEC_1"]


@pytest.mark.asyncio
async def test_retrieve_stateful_contribution_source_input_preserves_degraded_component_economics(
    monkeypatch,
):
    portfolio_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
            }
        ],
    )

    async def _mock_retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
        return portfolio_input

    monkeypatch.setattr(
        "app.services.stateful_contribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    degraded_component_payload = {
        "supportability": {
            "state": "UNAVAILABLE",
            "reason": "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE",
            "source_row_count": 0,
            "observed_component_families": [],
            "missing_component_families": ["fee", "income", "tax", "realized_fx_pnl"],
            "supported_component_families": [],
        }
    }
    service = _ContributionInputServiceStub(
        payload={
            "rows": [
                {
                    "position_id": "POS_1",
                    "security_id": "SEC_1",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "1000",
                    "ending_market_value_portfolio_currency": "1010",
                }
            ],
            "retrieval_metadata": {
                "chunk_count": 1,
                "page_count": 1,
                "source_row_count": 1,
                "retained_row_count": 1,
                "discarded_source_row_count": 0,
            },
        },
        component_status_code=503,
        component_payload=degraded_component_payload,
    )

    result = await retrieve_stateful_contribution_source_input(
        settings=object(),
        stateful_input_service=service,
        calculation_id=uuid4(),
        portfolio_id="P1",
        as_of_date=date(2025, 1, 1),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=[],
        include_cash_flows=True,
        filters={"security_ids": ["SEC_1", ""]},
    )

    assert result.position_rows[0]["position_id"] == "POS_1"
    assert result.position_retrieval_metadata == RetrievalMetadata(chunk_count=1, page_count=1)
    assert result.position_source_rows_complete is True
    assert result.performance_component_economics_status == 503
    assert result.performance_component_economics_payload is degraded_component_payload
    assert service.component_calls[0]["security_ids"] == ["SEC_1"]


@pytest.mark.asyncio
async def test_retrieve_stateful_contribution_source_input_raises_on_upstream_error(monkeypatch):
    portfolio_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        observations=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value": "1000",
                "ending_market_value": "1010",
            }
        ],
    )

    async def _mock_retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
        return portfolio_input

    monkeypatch.setattr(
        "app.services.stateful_contribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    service = _ContributionInputServiceStub(status_code=503, payload={"detail": "boom"})

    with pytest.raises((HTTPException, APIError), match="stateful position timeseries source unavailable"):
        await retrieve_stateful_contribution_source_input(
            settings=object(),
            stateful_input_service=service,
            calculation_id=uuid4(),
            portfolio_id="P1",
            as_of_date=date(2025, 1, 1),
            report_start_date=date(2025, 1, 1),
            report_end_date=date(2025, 1, 1),
            reporting_currency="USD",
            consumer_system="lotus-performance",
            dimensions=[],
            include_cash_flows=True,
            filters={},
        )


def test_build_stateful_contribution_input_builds_positions_and_currency_selection():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency=None,
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1010",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "POS_1",
                "security_id": "SEC_1",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "cash_flow_currency": "EUR",
                "position_to_portfolio_fx_rate": "1",
                "portfolio_to_reporting_fx_rate": "1",
                "beginning_market_value_reporting_currency": "900",
                "ending_market_value_reporting_currency": "909",
                "beginning_market_value_position_currency": "800",
                "ending_market_value_position_currency": "808",
                "cash_flows": [
                    {"amount": "5", "timing": "bod"},
                    {"amount": "-2", "timing": "eod"},
                    {"amount": "-1", "timing": "eod", "cash_flow_type": "fee"},
                ],
                "dimensions": {"sector": "Tech"},
            },
            {
                "position_id": "POS_2",
                "valuation_date": None,
            },
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        performance_component_economics_payload={
            "rows": [
                {
                    "transaction_id": "TXN_FEE_1",
                    "security_id": "SEC_1",
                    "transaction_date": "2025-01-01",
                    "trade_fee_components": [{"currency": "USD", "amount": "1", "evidence_count": 1}],
                    "source_lineage": {"contract_version": "performance_component_economics_v1"},
                },
                {
                    "transaction_id": "TXN_OTHER_1",
                    "security_id": "SEC_2",
                    "transaction_date": "2025-01-01",
                    "trade_fee_components": [{"currency": "USD", "amount": "1", "evidence_count": 1}],
                    "source_lineage": {"contract_version": "performance_component_economics_v1"},
                },
            ],
            "component_totals_scope": "consumed_pages",
            "lineage": {"source_system": "transactions", "contract_version": "performance_component_economics_v1"},
            "request_fingerprints": ["fingerprint-1"],
            "retrieval_metadata": {"chunk_count": 1, "page_count": 1},
            "supportability": {
                "state": "READY",
                "reason": "PERFORMANCE_COMPONENT_ECONOMICS_READY",
                "source_row_count": 3,
                "observed_component_families": ["income", "tax", "fee", "realized_fx_pnl"],
                "missing_component_families": ["realized_capital_pnl"],
                "supported_component_families": ["fee", "income", "tax", "realized_fx_pnl"],
            },
        },
        performance_component_economics_status=200,
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
        fx=None,
        portfolio_base_currency="EUR",
    )

    assert normalized.portfolio_data.metric_basis == "NET"
    assert normalized.portfolio_currency == "EUR"
    assert normalized.reporting_currency == "USD"
    assert normalized.valuation_currency == "USD"
    assert len(normalized.positions_data) == 1
    point = normalized.positions_data[0].valuation_points[0]
    assert point.begin_mv == Decimal("900")
    assert point.end_mv == Decimal("909")
    assert point.bod_cf == Decimal("5")
    assert point.eod_cf == Decimal("-2")
    assert point.mgmt_fees == Decimal("-1")
    assert normalized.positions_data[0].meta["sector"] == "Tech"
    component_context = normalized.positions_data[0].meta["_source_economics"]["performance_component_economics"]
    assert component_context["source_contract"] == "PerformanceComponentEconomics:v1"
    assert component_context["supportability_state"] == "READY"
    assert component_context["observed_component_families"] == ["fee", "income", "realized_fx_pnl", "tax"]
    assert component_context["position_source_row_count"] == 1
    assert component_context["source_rows"][0]["transaction_id"] == "TXN_FEE_1"
    assert component_context["component_totals_scope"] == "consumed_pages"
    assert component_context["lineage"]["contract_version"] == "performance_component_economics_v1"
    assert component_context["request_fingerprints"] == ["fingerprint-1"]
    assert component_context["retrieval_metadata"] == {"chunk_count": 1, "page_count": 1}


def test_build_stateful_contribution_input_uses_core_base_for_cash_flow_provenance():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="EUR",
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "100",
                    "ending_market_value": "101",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "EUR_POSITION",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "cash_flow_currency": "EUR",
                "position_to_portfolio_fx_rate": "1",
                "beginning_market_value_reporting_currency": "100",
                "ending_market_value_reporting_currency": "101",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"}],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency="EUR",
        fx=None,
        portfolio_base_currency="USD",
    )

    assert normalized.portfolio_currency == "EUR"
    assert normalized.source_preconverted_cash_flow_conversion is False


def test_stateful_base_only_valuation_currency_refuses_source_report_currency_mismatch():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="USD",
            observations=[],
        ),
        position_rows=[],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises(APIError) as exc_info:
        _stateful_base_only_valuation_currency(
            source_input=source_input,
            currency_mode="BASE_ONLY",
            requested_reporting_currency="SGD",
        )

    assert exc_info.value.error_code == "SOURCE_REPORTING_CURRENCY_MISMATCH"


def test_stateful_base_only_refuses_cross_currency_cash_flows_without_source_fx_rates():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="USD",
            observations=[],
        ),
        position_rows=[
            {
                "position_id": "EUR_CASH_FLOW",
                "valuation_date": "2025-01-01",
                "cash_flow_currency": "EUR",
                "beginning_market_value_reporting_currency": "120",
                "ending_market_value_reporting_currency": "132",
                "cash_flows": [{"amount": "5", "timing": "bod"}],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises(APIError) as exc_info:
        build_stateful_contribution_input(
            source_input=source_input,
            metric_basis="NET",
            currency_mode="BASE_ONLY",
            reporting_currency="USD",
            fx=None,
        )

    assert exc_info.value.error_code == "REPORTING_CURRENCY_CASH_FLOW_FX_INCOMPLETE"

    same_currency_portfolio_foreign_flow_source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="USD",
            reporting_currency="USD",
            observations=[],
        ),
        position_rows=[
            {
                "position_id": "EUR_FLOW_IN_USD_PORTFOLIO",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "cash_flow_currency": "EUR",
                "beginning_market_value_reporting_currency": "120",
                "ending_market_value_reporting_currency": "132",
                "cash_flows": [{"amount": "5", "timing": "bod"}],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises(APIError) as exc_info:
        build_stateful_contribution_input(
            source_input=same_currency_portfolio_foreign_flow_source_input,
            metric_basis="NET",
            currency_mode="BASE_ONLY",
            reporting_currency="USD",
            fx=None,
        )

    assert exc_info.value.error_code == "REPORTING_CURRENCY_CASH_FLOW_FX_INCOMPLETE"

    nonfinite_rate_source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="USD",
            observations=[],
        ),
        position_rows=[
            {
                "position_id": "EUR_NONFINITE_CASH_FLOW",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "cash_flow_currency": "EUR",
                "position_to_portfolio_fx_rate": "1",
                "portfolio_to_reporting_fx_rate": "Infinity",
                "beginning_market_value_reporting_currency": "120",
                "ending_market_value_reporting_currency": "132",
                "cash_flows": [{"amount": "5", "timing": "bod"}],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises(APIError) as exc_info:
        build_stateful_contribution_input(
            source_input=nonfinite_rate_source_input,
            metric_basis="NET",
            currency_mode="BASE_ONLY",
            reporting_currency="USD",
            fx=None,
        )

    assert exc_info.value.error_code == "REPORTING_CURRENCY_CASH_FLOW_FX_INCOMPLETE"


def test_stateful_base_only_ignores_unsupported_cash_flows_when_validating_source_fx():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "120",
                    "ending_market_value": "132",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "EUR_UNSUPPORTED_CASH_FLOW",
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "cash_flow_currency": "EUR",
                "beginning_market_value_reporting_currency": "120",
                "ending_market_value_reporting_currency": "132",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "coupon"}],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
        fx=None,
    )

    point = normalized.positions_data[0].valuation_points[0]
    assert point.bod_cf == Decimal("0")
    assert "_source_cash_flow_currencies" not in normalized.positions_data[0].meta


def test_stateful_base_only_ignores_unconsumed_rows_when_validating_reporting_coverage():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            portfolio_currency="EUR",
            reporting_currency="USD",
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "120",
                    "ending_market_value": "132",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "VALID",
                "valuation_date": "2025-01-01",
                "beginning_market_value_reporting_currency": "120",
                "ending_market_value_reporting_currency": "132",
                "cash_flows": [],
            },
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "1",
                "ending_market_value_portfolio_currency": "1",
            },
            {
                "position_id": "NO_VALUES",
                "valuation_date": "2025-01-01",
            },
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
        fx=None,
    )

    assert normalized.valuation_currency == "USD"
    assert [position.position_id for position in normalized.positions_data] == ["NO_VALUES", "VALID"]
    assert normalized.positions_data[0].valuation_points == []


def test_stateful_contribution_portfolio_data_preserves_metric_basis_and_valuation_points():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1010",
                    "cash_flows": [
                        {"amount": "5", "timing": "bod"},
                        {"amount": "-2", "timing": "eod"},
                    ],
                }
            ],
        ),
        position_rows=[],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    portfolio_data = _stateful_contribution_portfolio_data(
        source_input=source_input,
        metric_basis="GROSS",
    )

    assert portfolio_data.metric_basis == "GROSS"
    assert portfolio_data.valuation_points[0].begin_mv == Decimal("1000")
    assert portfolio_data.valuation_points[0].end_mv == Decimal("1010")
    assert portfolio_data.valuation_points[0].bod_cf == Decimal("5")
    assert portfolio_data.valuation_points[0].eod_cf == Decimal("-2")


def test_stateful_contribution_positions_data_sorts_positions_and_preserves_meta():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "POS_B",
                "security_id": "SEC_B",
                "valuation_date": "2025-01-01",
                "beginning_market_value_reporting_currency": "200",
                "ending_market_value_reporting_currency": "210",
                "dimensions": {"sector": "Healthcare"},
            },
            {
                "position_id": "POS_A",
                "security_id": "SEC_A",
                "valuation_date": "2025-01-01",
                "beginning_market_value_reporting_currency": "100",
                "ending_market_value_reporting_currency": "105",
                "dimensions": {"sector": "Technology"},
            },
        ],
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    positions_data = _stateful_contribution_positions_data(position_series)

    assert [position.position_id for position in positions_data] == ["POS_A", "POS_B"]
    assert positions_data[0].meta["sector"] == "Technology"
    assert positions_data[1].meta["sector"] == "Healthcare"
    assert positions_data[0].valuation_points[0].begin_mv == Decimal("100")
    assert positions_data[1].valuation_points[0].end_mv == Decimal("210")


def test_build_stateful_contribution_input_allows_currency_mode_both_for_same_currency_positions():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1010",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "POS_1",
                "security_id": "SEC_1",
                "position_currency": "USD",
                "valuation_date": "2025-01-01",
                "beginning_market_value_reporting_currency": "900",
                "ending_market_value_reporting_currency": "909",
                "beginning_market_value_position_currency": "900",
                "ending_market_value_position_currency": "909",
                "cash_flows": [],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BOTH",
        reporting_currency="USD",
        fx=None,
    )

    assert len(normalized.positions_data) == 1
    assert normalized.positions_data[0].meta["currency"] == "USD"


def test_build_stateful_contribution_input_rejects_invalid_both_currency_requests():
    base_source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1010",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "POS_1",
                "position_currency": "EUR",
                "valuation_date": "2025-01-01",
                "beginning_market_value_position_currency": "900",
                "ending_market_value_position_currency": "909",
                "cash_flows": [],
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises((HTTPException, APIError), match="requires report_ccy when currency_mode=BOTH"):
        build_stateful_contribution_input(
            source_input=base_source_input,
            metric_basis="NET",
            currency_mode="BOTH",
            reporting_currency=None,
            fx=None,
        )

    no_currency_rows = StatefulContributionSourceInput(
        portfolio_input=base_source_input.portfolio_input,
        position_rows=[
            {
                "position_id": "POS_1",
                "position_currency": " ",
                "valuation_date": "2025-01-01",
                "beginning_market_value_position_currency": "900",
                "ending_market_value_position_currency": "909",
                "cash_flows": [],
            }
        ],
        position_retrieval_metadata=base_source_input.position_retrieval_metadata,
    )
    with pytest.raises((HTTPException, APIError), match="requires position_currency"):
        build_stateful_contribution_input(
            source_input=no_currency_rows,
            metric_basis="NET",
            currency_mode="BOTH",
            reporting_currency="USD",
            fx=None,
        )

    with pytest.raises((HTTPException, APIError), match="requires fx.rates"):
        build_stateful_contribution_input(
            source_input=base_source_input,
            metric_basis="NET",
            currency_mode="BOTH",
            reporting_currency="USD",
            fx=None,
        )


def test_stateful_contribution_both_currency_requires_fx_only_for_non_reporting_currencies():
    assert (
        _stateful_both_currency_requires_fx(
            position_currencies={" usd ", "Usd"},
            reporting_currency="USD",
        )
        is False
    )
    assert (
        _stateful_both_currency_requires_fx(
            position_currencies={"usd", "EUR"},
            reporting_currency=" usd ",
        )
        is True
    )


def test_stateful_contribution_position_currencies_normalizes_codes_and_ignores_blank_values():
    assert _stateful_position_currencies(
        [
            {"position_id": "POS_1", "position_currency": " eur "},
            {"position_id": "POS_2", "position_currency": " "},
            {"position_id": "POS_3", "position_currency": ""},
            {"position_id": "POS_4", "position_currency": None},
            {"position_id": "POS_5", "position_currency": 123},
            {"position_id": "POS_6", "position_currency": "usd"},
        ]
    ) == {"EUR", "USD"}


def test_position_row_to_daily_point_falls_back_to_portfolio_values_when_reporting_values_are_missing():
    point = _position_row_to_daily_point(
        row={
            "valuation_date": "2025-01-01",
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "110",
            "cash_flows": [],
        },
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    assert point is not None
    assert point["begin_mv"] == Decimal("100")
    assert point["end_mv"] == Decimal("110")


def test_position_row_to_daily_point_uses_local_currency_values():
    point = _position_row_to_daily_point(
        row={
            "valuation_date": "2025-01-01",
            "beginning_market_value_position_currency": "10",
            "ending_market_value_position_currency": "11",
            "cash_flows": [{"amount": "2", "timing": "bod"}],
        },
        currency_mode="LOCAL_ONLY",
        reporting_currency="USD",
    )

    assert point is not None
    assert point["begin_mv"] == Decimal("10")
    assert point["bod_cf"] == Decimal("2")


def test_position_row_to_daily_point_converts_cash_flows_to_reporting_currency():
    point = _position_row_to_daily_point(
        row={
            "valuation_date": "2025-01-01",
            "position_currency": "EUR",
            "cash_flow_currency": "EUR",
            "position_to_portfolio_fx_rate": "1.20",
            "portfolio_to_reporting_fx_rate": "1.10",
            "beginning_market_value_reporting_currency": "132",
            "ending_market_value_reporting_currency": "145.2",
            "cash_flows": [
                {"amount": "5", "timing": "bod"},
                {"amount": "-2", "timing": "eod"},
                {"amount": "-1", "timing": "eod", "cash_flow_type": "fee"},
            ],
        },
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    assert point is not None
    assert point["begin_mv"] == Decimal("132")
    assert point["bod_cf"] == Decimal("6.60")
    assert point["eod_cf"] == Decimal("-2.6400")
    assert point["mgmt_fees"] == Decimal("-1.32")


def test_position_meta_from_row_preserves_source_metadata():
    assert _position_meta_from_row(
        {
            "security_id": "SEC_1",
            "cash_flow_currency": "EUR",
            "position_to_portfolio_fx_rate": "1.2",
            "portfolio_to_reporting_fx_rate": "1.1",
            "dimensions": {"sector": "Tech", "country": "US"},
        }
    ) == {
        "security_id": "SEC_1",
        "cash_flow_currency": "EUR",
        "position_to_portfolio_fx_rate": Decimal("1.2"),
        "portfolio_to_reporting_fx_rate": Decimal("1.1"),
        "sector": "Tech",
        "country": "US",
        "_source_economics": {
            "cash_flow_type_counts": {},
            "valuation_status": None,
            "source_contract": "PositionTimeseriesInput:v1",
        },
    }


def test_position_source_economics_counts_governed_cash_flow_taxonomy_edges():
    assert _position_source_economics_from_row(
        {
            "valuation_status": "READY",
            "cash_flows": [
                {"cash_flow_type": "fee"},
                {"cash_flow_type": " Management_Fee "},
                {"cash_flow_type": "coupon"},
                {"cash_flow_type": None},
                {"cash_flow_type": ""},
                {"cash_flow_type": "mystery_flow"},
                "ignored",
            ],
        }
    ) == {
        "cash_flow_type_counts": {
            "coupon": 1,
            "fee": 1,
            "management_fee": 1,
            "missing": 2,
            "mystery_flow": 1,
        },
        "valuation_status": "READY",
        "source_contract": "PositionTimeseriesInput:v1",
    }


def test_security_ids_filter_deduplicates_non_empty_source_security_ids():
    assert _security_ids_filter(
        {
            "security_ids": [
                "SEC_2",
                "",
                "SEC_1",
                None,
                "SEC_1",
                42,
            ]
        }
    ) == ["SEC_1", "SEC_2"]
    assert _security_ids_filter({"security_ids": ["", None, 42]}) is None
    assert _security_ids_filter({"security_ids": "SEC_1"}) is None


def test_position_contract_meta_from_row_normalizes_supported_source_fields():
    assert _position_contract_meta_from_row(
        {
            "security_id": "",
            "position_currency": "USD",
            "cash_flow_currency": "",
            "position_to_portfolio_fx_rate": "1.2",
            "portfolio_to_reporting_fx_rate": 1,
        }
    ) == {
        "security_id": "",
        "currency": "USD",
        "position_to_portfolio_fx_rate": Decimal("1.2"),
        "portfolio_to_reporting_fx_rate": Decimal("1"),
    }


def test_position_contract_fx_rate_meta_converts_available_rates_to_decimals():
    assert _position_contract_fx_rate_meta(
        {
            "position_to_portfolio_fx_rate": "1.2",
            "portfolio_to_reporting_fx_rate": 1,
        }
    ) == {
        "position_to_portfolio_fx_rate": Decimal("1.2"),
        "portfolio_to_reporting_fx_rate": Decimal("1"),
    }
    assert _position_contract_fx_rate_meta({"position_to_portfolio_fx_rate": None}) == {}


def test_build_stateful_contribution_input_retains_membership_without_usable_values():
    source_input = StatefulContributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1010",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "POS_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": None,
                "ending_market_value_portfolio_currency": "10",
            },
            {
                "position_id": "POS_2",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "20",
                "ending_market_value_portfolio_currency": None,
            },
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode=None,
        reporting_currency=None,
        fx=None,
    )

    assert [position.position_id for position in normalized.positions_data] == ["POS_1", "POS_2"]
    assert all(position.valuation_points == [] for position in normalized.positions_data)
    assert all(
        position.meta["_source_hierarchy_memberships"] == [{"perf_date": "2025-01-01"}]
        for position in normalized.positions_data
    )
    assert normalized.source_position_window_complete is False


def test_position_series_withholds_window_authority_when_an_earlier_core_row_is_dropped():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "POS_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": None,
                "ending_market_value_portfolio_currency": "0",
            },
            {
                "position_id": "POS_1",
                "valuation_date": "2025-01-02",
                "beginning_market_value_portfolio_currency": "0",
                "ending_market_value_portfolio_currency": "100",
                "cash_flows": [{"amount": "100", "timing": "bod"}],
            },
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    surviving_points = position_series.valuation_points_by_position_id["POS_1"]
    assert [point["perf_date"] for point in surviving_points] == ["2025-01-02"]
    assert position_series.source_rows_complete is False


@pytest.mark.asyncio
async def test_malformed_core_page_row_withholds_window_authority_before_normalization(monkeypatch):
    portfolio_input = StatefulPortfolioInput(
        performance_start_date=date(2025, 1, 1),
        portfolio_currency="USD",
        observations=[
            {"valuation_date": "2025-01-01", "beginning_market_value": "0", "ending_market_value": "0"},
            {"valuation_date": "2025-01-02", "beginning_market_value": "0", "ending_market_value": "100"},
        ],
    )

    async def _mock_retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
        return portfolio_input

    class _MalformedPositionPageCoreService:
        async def get_position_analytics_timeseries(self, **kwargs):  # noqa: ARG002
            return 200, {
                "rows": [
                    {
                        "position_id": "POS_1",
                        "beginning_market_value_portfolio_currency": "0",
                        "ending_market_value_portfolio_currency": "0",
                    },
                    {
                        "position_id": "POS_1",
                        "valuation_date": "2025-01-02",
                        "beginning_market_value_portfolio_currency": "0",
                        "ending_market_value_portfolio_currency": "100",
                        "cash_flows": [{"amount": "100", "timing": "bod"}],
                    },
                ]
            }

        async def get_performance_component_economics(self, **kwargs):  # noqa: ARG002
            return 503, {"detail": "not available in this focused source-row test"}

    monkeypatch.setattr(
        "app.services.stateful_contribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    source_input = await retrieve_stateful_contribution_source_input(
        settings=object(),
        stateful_input_service=StatefulInputService(core_service=_MalformedPositionPageCoreService()),
        calculation_id=None,
        portfolio_id="P1",
        as_of_date=date(2025, 1, 2),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 2),
        reporting_currency=None,
        consumer_system="lotus-performance",
        dimensions=[],
        include_cash_flows=True,
        filters={},
    )

    assert [row["valuation_date"] for row in source_input.position_rows] == ["2025-01-02"]
    assert source_input.position_source_rows_complete is False
    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency=None,
        fx=None,
    )
    assert normalized.source_position_window_complete is False


def test_stateful_contribution_position_series_groups_points_and_preserves_latest_meta():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "POS_2",
                "security_id": "SEC_2",
                "valuation_date": "2025-01-02",
                "beginning_market_value_portfolio_currency": "20",
                "ending_market_value_portfolio_currency": "21",
                "dimensions": {"sector": "Healthcare"},
            },
            {
                "position_id": "POS_1",
                "security_id": "SEC_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "10",
                "ending_market_value_portfolio_currency": "11",
                "cash_flows": [{"amount": "1", "timing": "bod"}],
                "cash_flow_currency": "EUR",
                "dimensions": {"sector": "Tech"},
            },
            {
                "position_id": "POS_1",
                "security_id": "SEC_1_UPDATED",
                "valuation_date": "2025-01-02",
                "beginning_market_value_portfolio_currency": "11",
                "ending_market_value_portfolio_currency": "12",
                "dimensions": {"sector": "Software"},
            },
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert list(position_series.valuation_points_by_position_id) == ["POS_2", "POS_1"]
    assert len(position_series.valuation_points_by_position_id["POS_1"]) == 2
    assert position_series.source_rows_complete is True
    assert position_series.valuation_points_by_position_id["POS_1"][0]["bod_cf"] == Decimal("1")
    assert position_series.meta_by_position_id["POS_1"]["security_id"] == "SEC_1_UPDATED"
    assert position_series.meta_by_position_id["POS_1"]["sector"] == "Software"
    assert position_series.meta_by_position_id["POS_1"]["_source_cash_flow_currencies"] == ["EUR"]
    assert _source_cash_flow_currencies(_stateful_contribution_positions_data(position_series)[0]) == ["EUR"]


def test_stateful_contribution_position_series_preserves_pairs_for_cancelled_source_cash_flows():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "POS_GBP",
                "valuation_date": "2025-01-01",
                "position_currency": "GBP",
                "cash_flow_currency": "GBP",
                "position_to_portfolio_fx_rate": "1.15",
                "portfolio_to_reporting_fx_rate": "1.10",
                "beginning_market_value_reporting_currency": "120",
                "ending_market_value_reporting_currency": "132",
                "cash_flows": [
                    {"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"},
                    {"amount": "-5", "timing": "bod", "cash_flow_type": "external_flow"},
                ],
            }
        ],
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    position = _stateful_contribution_positions_data(position_series)[0]
    assert position.valuation_points[0].bod_cf == Decimal("0")
    assert _source_cash_flow_currencies(position) == ["GBP"]
    assert _source_preconverted_cash_flow_pairs_for_position(
        position=position,
        portfolio_base_currency="EUR",
        reporting_currency="USD",
    ) == {"EUR/USD", "GBP/EUR"}


def test_stateful_contribution_position_series_preserves_source_position_grain():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "SEC_1",
                "source_position_key": "position_id=SEC_1|account_id=ACC_A|tax_lot_id=LOT_1",
                "account_id": "ACC_A",
                "tax_lot_id": "LOT_1",
                "security_id": "SEC_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "101",
            },
            {
                "position_id": "SEC_1",
                "source_position_key": "position_id=SEC_1|account_id=ACC_B|tax_lot_id=LOT_2",
                "account_id": "ACC_B",
                "tax_lot_id": "LOT_2",
                "security_id": "SEC_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "200",
                "ending_market_value_portfolio_currency": "202",
            },
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert list(position_series.valuation_points_by_position_id) == [
        "position_id=SEC_1|account_id=ACC_A|tax_lot_id=LOT_1",
        "position_id=SEC_1|account_id=ACC_B|tax_lot_id=LOT_2",
    ]
    first_meta = position_series.meta_by_position_id["position_id=SEC_1|account_id=ACC_A|tax_lot_id=LOT_1"]
    assert first_meta["business_position_id"] == "SEC_1"
    assert first_meta["source_position_key"] == "position_id=SEC_1|account_id=ACC_A|tax_lot_id=LOT_1"


def test_stateful_contribution_position_series_skips_invalid_or_unusable_rows():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": None,
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "10",
                "ending_market_value_portfolio_currency": "11",
            },
            {
                "position_id": "POS_1",
                "valuation_date": None,
                "beginning_market_value_portfolio_currency": "10",
                "ending_market_value_portfolio_currency": "11",
            },
            {
                "position_id": "POS_2",
                "valuation_date": "2025-01-02",
                "beginning_market_value_portfolio_currency": None,
                "ending_market_value_portfolio_currency": "12",
            },
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert position_series.valuation_points_by_position_id == {}
    assert list(position_series.meta_by_position_id) == ["POS_2"]
    assert position_series.meta_by_position_id["POS_2"]["_source_hierarchy_memberships"] == [
        {"perf_date": "2025-01-02"}
    ]
    assert position_series.source_rows_complete is False


def test_stateful_contribution_position_series_withholds_completeness_for_discarded_nested_cash_flow():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "POS_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "cash_flows": [{"amount": "5", "timing": "mid"}],
                "dimensions": {"sector": "Private Credit"},
            }
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert len(position_series.valuation_points_by_position_id["POS_1"]) == 1
    assert position_series.source_rows_complete is False


def test_stateful_contribution_position_series_withholds_completeness_for_nonfinite_cash_flow_fx():
    position_series = _stateful_contribution_position_series(
        rows=[
            {
                "position_id": "POS_1",
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "105",
                "position_to_portfolio_fx_rate": "NaN",
                "cash_flows": [{"amount": "5", "timing": "bod", "cash_flow_type": "external_flow"}],
                "dimensions": {"sector": "Private Credit"},
            }
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert len(position_series.valuation_points_by_position_id["POS_1"]) == 1
    assert position_series.valuation_points_by_position_id["POS_1"][0]["bod_cf"].is_zero()
    assert position_series.source_rows_complete is False


def test_position_value_inputs_selects_local_position_values():
    value_inputs = _position_value_inputs(
        row={
            "beginning_market_value_position_currency": "10",
            "ending_market_value_position_currency": "11",
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "110",
        },
        currency_mode="LOCAL_ONLY",
        reporting_currency="USD",
    )

    assert value_inputs is not None
    assert value_inputs.begin_value == "10"
    assert value_inputs.end_value == "11"
    assert value_inputs.value_basis == "position"


def test_position_value_inputs_uses_reporting_values_with_portfolio_fallback():
    reporting_inputs = _position_value_inputs(
        row={
            "beginning_market_value_reporting_currency": "90",
            "ending_market_value_reporting_currency": "91",
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "101",
        },
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )
    fallback_inputs = _position_value_inputs(
        row={
            "beginning_market_value_reporting_currency": None,
            "ending_market_value_reporting_currency": "91",
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "101",
        },
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    assert reporting_inputs is not None
    assert reporting_inputs.begin_value == "90"
    assert reporting_inputs.end_value == "91"
    assert reporting_inputs.value_basis == "reporting"
    assert fallback_inputs is not None
    assert fallback_inputs.begin_value == "100"
    assert fallback_inputs.end_value == "101"
    assert fallback_inputs.value_basis == "reporting"


def test_reporting_position_value_pair_prefers_complete_reporting_values_and_falls_back_to_portfolio_pair():
    assert _reporting_position_value_pair(
        {
            "beginning_market_value_reporting_currency": "90",
            "ending_market_value_reporting_currency": "91",
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "101",
        }
    ) == ("90", "91")
    assert _reporting_position_value_pair(
        {
            "beginning_market_value_reporting_currency": "90",
            "ending_market_value_reporting_currency": None,
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "101",
        }
    ) == ("100", "101")


def test_position_value_inputs_uses_portfolio_values_and_rejects_missing_values():
    portfolio_inputs = _position_value_inputs(
        row={
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "101",
        },
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )
    missing_inputs = _position_value_inputs(
        row={
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": None,
        },
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert portfolio_inputs is not None
    assert portfolio_inputs.begin_value == "100"
    assert portfolio_inputs.end_value == "101"
    assert portfolio_inputs.value_basis == "portfolio"
    assert missing_inputs is None


def test_position_row_to_daily_point_returns_none_when_date_or_values_are_missing():
    assert (
        _position_row_to_daily_point(
            row={
                "valuation_date": None,
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "110",
            },
            currency_mode="BASE_ONLY",
            reporting_currency=None,
        )
        is None
    )
    assert (
        _position_row_to_daily_point(
            row={
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": None,
                "ending_market_value_portfolio_currency": None,
            },
            currency_mode="BASE_ONLY",
            reporting_currency=None,
        )
        is None
    )
