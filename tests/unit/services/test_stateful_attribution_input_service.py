from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.stateful_attribution_input_service import (
    StatefulAttributionSourceInput,
    _build_benchmark_groups,
    _build_group_key,
    _parse_component_series,
    _parse_index_catalog,
    _parse_position_rows,
    _parse_retrieval_metadata,
    _position_meta_from_row,
    _position_row_to_daily_point,
    _split_position_cash_flows,
    _validate_stateful_group_by,
    build_stateful_attribution_input,
    retrieve_stateful_attribution_source_input,
)
from app.services.stateful_input_service import RetrievalMetadata
from app.services.stateful_performance_input_service import StatefulPortfolioInput


class _AttributionInputServiceStub:
    def __init__(self) -> None:
        self.position_response = (200, {"rows": []})
        self.assignment_response = (200, {"benchmark_id": "BMK_1"})
        self.market_response = (200, {"component_series": []})
        self.index_response = (200, {"records": []})

    async def get_position_timeseries(self, **kwargs):
        return self.position_response

    async def get_benchmark_assignment(self, **kwargs):
        return self.assignment_response

    async def get_benchmark_market_series(self, **kwargs):
        return self.market_response

    async def get_index_catalog(self, **kwargs):
        return self.index_response


@pytest.mark.asyncio
async def test_retrieve_stateful_attribution_source_input_uses_override_benchmark(monkeypatch):
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
        "app.services.stateful_attribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )

    service = _AttributionInputServiceStub()
    service.position_response = (
        200,
        {
            "rows": [{"position_id": "POS_1", "valuation_date": "2025-01-01"}],
            "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
        },
    )
    service.market_response = (
        200,
        {
            "component_series": [{"index_id": "IDX_1", "points": []}],
            "retrieval_metadata": {"chunk_count": 4, "page_count": 5},
        },
    )
    service.index_response = (200, {"records": [{"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}}]})

    result = await retrieve_stateful_attribution_source_input(
        settings=object(),
        stateful_input_service=service,
        calculation_id=uuid4(),
        portfolio_id="P1",
        as_of_date=date(2025, 1, 1),
        report_start_date=date(2025, 1, 1),
        report_end_date=date(2025, 1, 1),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        group_by=["sector"],
        dimensions=[],
        include_cash_flows=False,
        filters={},
        benchmark_id_override="BMK_OVERRIDE",
    )

    assert result.portfolio_input is portfolio_input
    assert result.benchmark_id == "BMK_OVERRIDE"
    assert result.position_retrieval_metadata == RetrievalMetadata(chunk_count=2, page_count=3)
    assert result.benchmark_retrieval_metadata == RetrievalMetadata(chunk_count=4, page_count=5)
    assert result.index_retrieval_metadata == RetrievalMetadata(chunk_count=1, page_count=1)


@pytest.mark.asyncio
async def test_retrieve_stateful_attribution_source_input_raises_for_upstream_failures(monkeypatch):
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
        "app.services.stateful_attribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )

    service = _AttributionInputServiceStub()
    service.position_response = (503, {})
    with pytest.raises(HTTPException, match="stateful position timeseries source unavailable"):
        await retrieve_stateful_attribution_source_input(
            settings=object(),
            stateful_input_service=service,
            calculation_id=uuid4(),
            portfolio_id="P1",
            as_of_date=date(2025, 1, 1),
            report_start_date=date(2025, 1, 1),
            report_end_date=date(2025, 1, 1),
            reporting_currency="USD",
            consumer_system="lotus-performance",
            group_by=["sector"],
            dimensions=[],
            include_cash_flows=True,
            filters={},
            benchmark_id_override=None,
        )

    service = _AttributionInputServiceStub()
    service.assignment_response = (404, {})
    with pytest.raises(HTTPException, match="requires a benchmark assignment"):
        await retrieve_stateful_attribution_source_input(
            settings=object(),
            stateful_input_service=service,
            calculation_id=uuid4(),
            portfolio_id="P1",
            as_of_date=date(2025, 1, 1),
            report_start_date=date(2025, 1, 1),
            report_end_date=date(2025, 1, 1),
            reporting_currency="USD",
            consumer_system="lotus-performance",
            group_by=["sector"],
            dimensions=[],
            include_cash_flows=True,
            filters={},
            benchmark_id_override=None,
        )


def test_build_stateful_attribution_input_builds_instruments_and_benchmark_groups():
    source_input = StatefulAttributionSourceInput(
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
                "cash_flows": [{"amount": "5", "timing": "bod"}, {"amount": "-2", "timing": "eod"}],
                "dimensions": {"sector": "Tech"},
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_1",
        benchmark_component_series=[
            {
                "index_id": "IDX_1",
                "points": [
                    {"series_date": "2025-01-01", "component_weight": "0.5", "index_return": "0.01"},
                    {"series_date": "2025-01-01", "component_weight": "0.5", "index_return": "0.03"},
                ],
            }
        ],
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[{"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}}],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_attribution_input(
        source_input=source_input,
        mode="by_instrument",
        group_by=["sector"],
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    assert normalized.portfolio_data.metric_basis == "NET"
    assert normalized.instruments_data[0].meta["sector"] == "Tech"
    assert normalized.instruments_data[0].valuation_points[0].bod_cf == 5
    assert normalized.benchmark_groups_data[0].key["sector"] == "Tech"
    assert normalized.benchmark_groups_data[0].observations[0].return_base == pytest.approx(0.02)


def test_build_stateful_attribution_input_rejects_mode_and_currency_fences():
    source_input = StatefulAttributionSourceInput(
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
        position_rows=[],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_1",
        benchmark_component_series=[],
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises(HTTPException, match="mode=by_instrument only"):
        build_stateful_attribution_input(
            source_input=source_input,
            mode="by_group",
            group_by=["sector"],
            metric_basis="NET",
            currency_mode="BASE_ONLY",
            reporting_currency="USD",
        )

    with pytest.raises(HTTPException, match="currency_mode=BASE_ONLY only"):
        build_stateful_attribution_input(
            source_input=source_input,
            mode="by_instrument",
            group_by=["sector"],
            metric_basis="NET",
            currency_mode="BOTH",
            reporting_currency="USD",
        )


def test_stateful_attribution_group_by_and_benchmark_validation_errors():
    with pytest.raises(HTTPException, match="Unsupported: issuer"):
        _validate_stateful_group_by(["issuer"])

    with pytest.raises(HTTPException, match="missing classification label"):
        _build_group_key(labels={"sector": ""}, group_by=["sector"], index_id="IDX_1")

    with pytest.raises(HTTPException, match="missing classification labels"):
        _build_benchmark_groups(
            group_by=["sector"],
            component_series=[{"index_id": "IDX_1", "points": []}],
            index_records=[],
        )

    with pytest.raises(HTTPException, match="missing index_return or component_weight"):
        _build_benchmark_groups(
            group_by=["sector"],
            component_series=[{"index_id": "IDX_1", "points": [{"series_date": "2025-01-01"}]}],
            index_records=[{"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}}],
        )


def test_stateful_attribution_parsers_filter_invalid_rows():
    assert _split_position_cash_flows(["bad", {"amount": None, "timing": "bod"}]) == (0, 0)
    assert _position_meta_from_row({"security_id": "SEC_1", "dimensions": {"sector": "Tech"}}) == {
        "security_id": "SEC_1",
        "sector": "Tech",
    }
    assert _parse_position_rows({"rows": [{"position_id": "POS_1"}, "bad"]}) == [{"position_id": "POS_1"}]
    assert _parse_component_series({"component_series": [{"index_id": "IDX_1"}, "bad"]}) == [{"index_id": "IDX_1"}]
    assert _parse_index_catalog({"records": [{"index_id": "IDX_1"}, "bad"]}) == [{"index_id": "IDX_1"}]
    assert _parse_retrieval_metadata({}) == RetrievalMetadata(chunk_count=1, page_count=1)


def test_stateful_attribution_position_row_to_daily_point_requires_market_values():
    assert _position_row_to_daily_point(row={"valuation_date": None}, reporting_currency=None) is None
    assert _position_row_to_daily_point(row={"valuation_date": "2025-01-01"}, reporting_currency="USD") is None
