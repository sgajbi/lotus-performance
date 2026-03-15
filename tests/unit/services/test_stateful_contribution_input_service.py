from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.stateful_contribution_input_service import (
    StatefulContributionSourceInput,
    _parse_retrieval_metadata,
    _position_meta_from_row,
    _position_row_to_daily_point,
    _split_position_cash_flows,
    build_stateful_contribution_input,
    retrieve_stateful_contribution_source_input,
)
from app.services.stateful_input_service import RetrievalMetadata
from app.services.stateful_performance_input_service import StatefulPortfolioInput


class _ContributionInputServiceStub:
    def __init__(self, status_code: int = 200, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {"rows": []}
        self.calls: list[dict[str, object]] = []

    async def get_position_timeseries(self, **kwargs):
        self.calls.append(kwargs)
        return self.status_code, self.payload


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

    async def _mock_retrieve_stateful_portfolio_input(**kwargs):  # noqa: ARG001
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
            "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
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
    assert len(result.position_rows) == 1
    assert result.position_retrieval_metadata == RetrievalMetadata(chunk_count=2, page_count=3)
    assert service.calls[0]["dimensions"] == ["sector"]
    assert service.calls[0]["include_cash_flows"] is False


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

    with pytest.raises(HTTPException, match="stateful position timeseries source unavailable"):
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
    )

    normalized = build_stateful_contribution_input(
        source_input=source_input,
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
        fx=None,
    )

    assert normalized.portfolio_data.metric_basis == "NET"
    assert len(normalized.positions_data) == 1
    point = normalized.positions_data[0].valuation_points[0]
    assert point.begin_mv == Decimal("900")
    assert point.end_mv == Decimal("909")
    assert point.bod_cf == Decimal("5")
    assert point.eod_cf == Decimal("-3")
    assert point.mgmt_fees == Decimal("-1")
    assert normalized.positions_data[0].meta["sector"] == "Tech"


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


def test_split_position_cash_flows_ignores_invalid_rows():
    bod_cf, eod_cf, fees = _split_position_cash_flows(["bad", {"amount": None, "timing": "bod"}])

    assert (bod_cf, eod_cf, fees) == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_position_meta_and_retrieval_metadata_defaults():
    assert _position_meta_from_row({"security_id": "SEC_1", "dimensions": {"sector": "Tech", "country": "US"}}) == {
        "security_id": "SEC_1",
        "sector": "Tech",
        "country": "US",
    }
    assert _parse_retrieval_metadata({}) == RetrievalMetadata(chunk_count=1, page_count=1)
