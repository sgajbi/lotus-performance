from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.stateful_contribution_input_service import (
    StatefulContributionSourceInput,
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
    assert point.eod_cf == Decimal("-2")
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

    with pytest.raises(HTTPException, match="requires report_ccy when currency_mode=BOTH"):
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
                "valuation_date": "2025-01-01",
                "beginning_market_value_position_currency": "900",
                "ending_market_value_position_currency": "909",
                "cash_flows": [],
            }
        ],
        position_retrieval_metadata=base_source_input.position_retrieval_metadata,
    )
    with pytest.raises(HTTPException, match="requires position_currency"):
        build_stateful_contribution_input(
            source_input=no_currency_rows,
            metric_basis="NET",
            currency_mode="BOTH",
            reporting_currency="USD",
            fx=None,
        )

    with pytest.raises(HTTPException, match="requires fx.rates"):
        build_stateful_contribution_input(
            source_input=base_source_input,
            metric_basis="NET",
            currency_mode="BOTH",
            reporting_currency="USD",
            fx=None,
        )


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


def test_split_position_cash_flows_ignores_invalid_rows():
    bod_cf, eod_cf, fees = _split_position_cash_flows(["bad", {"amount": None, "timing": "bod"}])

    assert (bod_cf, eod_cf, fees) == (Decimal("0"), Decimal("0"), Decimal("0"))


def test_split_position_cash_flows_handles_non_list_and_fee_accumulation():
    assert _split_position_cash_flows(None) == (Decimal("0"), Decimal("0"), Decimal("0"))

    bod_cf, eod_cf, fees = _split_position_cash_flows(
        [
            {"amount": "4.5", "timing": "bod"},
            {"amount": "-2.0", "timing": "eod"},
            {"amount": "-0.5", "timing": "eod", "cash_flow_type": "fee"},
        ]
    )

    assert bod_cf == Decimal("4.5")
    assert eod_cf == Decimal("-2.5")
    assert fees == Decimal("-0.5")


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


def test_build_stateful_contribution_input_skips_rows_without_usable_values():
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

    assert normalized.positions_data == []


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
