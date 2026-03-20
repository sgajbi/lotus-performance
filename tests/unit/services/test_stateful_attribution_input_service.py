from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_requests import BenchmarkComponentObservation
from app.services.stateful_attribution_input_service import (
    StatefulAttributionSourceInput,
    _build_benchmark_groups,
    _build_group_key,
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
from app.services.stateful_benchmark_input_service import StatefulBenchmarkNormalizedInput
from app.services.stateful_input_service import RetrievalMetadata
from app.services.stateful_performance_input_service import StatefulPortfolioInput


class _AttributionInputServiceStub:
    def __init__(self) -> None:
        self.position_response = (200, {"rows": []})
        self.assignment_response = (200, {"benchmark_id": "BMK_1"})
        self.index_response = (200, {"records": []})

    async def get_position_timeseries(self, **kwargs):
        return self.position_response

    async def get_benchmark_assignment(self, **kwargs):
        return self.assignment_response

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
    async def _mock_build_benchmark_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX_1",
                    component_currency="USD",
                    date=date(2025, 1, 1),
                    weight_bop=1.0,
                    component_return=0.01,
                    component_return_local=0.01,
                    component_return_fx=0.0,
                )
            ],
            benchmark_return_points=[],
            source_details={"benchmark_components": 1, "benchmark_chunk_count": 4, "benchmark_page_count": 5},
        )
    monkeypatch.setattr(
        "app.services.stateful_attribution_input_service.build_stateful_benchmark_input",
        _mock_build_benchmark_input,
    )

    service = _AttributionInputServiceStub()
    service.position_response = (
        200,
        {
            "rows": [{"position_id": "POS_1", "valuation_date": "2025-01-01"}],
            "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
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
    async def _mock_build_benchmark_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX_1",
                    component_currency="USD",
                    date=date(2025, 1, 1),
                    weight_bop=1.0,
                    component_return=0.01,
                    component_return_local=0.01,
                    component_return_fx=0.0,
                )
            ],
            benchmark_return_points=[],
            source_details={"benchmark_components": 1, "benchmark_chunk_count": 1, "benchmark_page_count": 1},
        )
    monkeypatch.setattr(
        "app.services.stateful_attribution_input_service.build_stateful_benchmark_input",
        _mock_build_benchmark_input,
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
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                component_currency="USD",
                date=date(2025, 1, 1),
                weight_bop=0.5,
                component_return=0.01,
                component_return_local=0.01,
                component_return_fx=0.0,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_2",
                component_currency="USD",
                date=date(2025, 1, 1),
                weight_bop=0.5,
                component_return=0.03,
                component_return_local=0.03,
                component_return_fx=0.0,
            ),
        ],
        benchmark_source_details={"benchmark_components": 2},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[
            {"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}},
            {"index_id": "IDX_2", "classification_labels": {"sector": "Tech"}},
        ],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_attribution_input(
        source_input=source_input,
        mode="by_instrument",
        group_by=["sector"],
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        fx=None,
        reporting_currency="USD",
    )

    assert normalized.portfolio_data.metric_basis == "NET"
    assert normalized.instruments_data[0].meta["sector"] == "Tech"
    assert normalized.instruments_data[0].valuation_points[0].bod_cf == 5
    assert normalized.benchmark_groups_data[0].key["sector"] == "Tech"
    assert normalized.benchmark_groups_data[0].observations[0].return_base == pytest.approx(0.02)
    assert normalized.benchmark_groups_data[0].observations[0].return_local == pytest.approx(0.02)
    assert normalized.benchmark_groups_data[0].observations[0].return_fx == pytest.approx(0.0)


def test_build_stateful_attribution_input_rejects_mode_fence():
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
        benchmark_component_observations=[],
        benchmark_source_details={},
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
            fx=None,
            reporting_currency="USD",
        )


def test_build_stateful_attribution_input_supports_currency_mode_both():
    source_input = StatefulAttributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[
                {
                    "valuation_date": "2025-01-01",
                    "beginning_market_value": "1000",
                    "ending_market_value": "1020",
                }
            ],
        ),
        position_rows=[
            {
                "position_id": "POS_1",
                "security_id": "SEC_1",
                "position_currency": "EUR",
                "valuation_date": "2025-01-01",
                "beginning_market_value_reporting_currency": "990",
                "beginning_market_value_position_currency": "900",
                "ending_market_value_position_currency": "918",
                "cash_flows": [],
                "dimensions": {"sector": "Tech"},
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_1",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                component_currency="EUR",
                date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.0302,
                component_return_local=0.02,
                component_return_fx=0.01,
            )
        ],
        benchmark_source_details={"benchmark_components": 1},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[{"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}}],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    normalized = build_stateful_attribution_input(
        source_input=source_input,
        mode="by_instrument",
        group_by=["currency"],
        metric_basis="NET",
        currency_mode="BOTH",
        fx={"rates": [{"date": "2024-12-31", "ccy": "EUR", "rate": 1.1}]},
        reporting_currency="USD",
    )

    assert normalized.instruments_data[0].meta["currency"] == "EUR"
    assert normalized.instruments_data[0].valuation_points[0].begin_mv == 900
    assert normalized.instruments_data[0].meta["base_weight_points"] == [
        {"perf_date": "2025-01-01", "begin_mv": 990, "bod_cf": 0}
    ]
    assert normalized.benchmark_groups_data[0].key["currency"] == "EUR"
    assert normalized.benchmark_groups_data[0].observations[0].return_local == pytest.approx(0.02)
    assert normalized.benchmark_groups_data[0].observations[0].return_fx == pytest.approx(0.01)


def test_stateful_attribution_group_by_and_benchmark_validation_errors():
    with pytest.raises(HTTPException, match="Unsupported: issuer"):
        _validate_stateful_group_by(["issuer"])

    with pytest.raises(HTTPException, match="missing classification label"):
        _build_group_key(labels={"sector": ""}, group_by=["sector"], index_id="IDX_1")

    with pytest.raises(HTTPException, match="missing classification labels"):
        _build_benchmark_groups(
            group_by=["sector"],
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX_1",
                    component_currency="USD",
                    date=date(2025, 1, 1),
                    weight_bop=1.0,
                    component_return=0.01,
                    component_return_local=0.01,
                    component_return_fx=0.0,
                )
            ],
            index_records=[],
        )

    with pytest.raises(HTTPException, match="No normalized benchmark component observations"):
        _build_benchmark_groups(
            group_by=["sector"],
            component_observations=[],
            index_records=[{"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}}],
        )


def test_stateful_attribution_parsers_filter_invalid_rows():
    assert _split_position_cash_flows(["bad", {"amount": None, "timing": "bod"}]) == (0, 0)
    assert _position_meta_from_row({"security_id": "SEC_1", "dimensions": {"sector": "Tech"}}) == {
        "security_id": "SEC_1",
        "sector": "Tech",
    }
    assert _parse_position_rows({"rows": [{"position_id": "POS_1"}, "bad"]}) == [{"position_id": "POS_1"}]
    assert _parse_index_catalog({"records": [{"index_id": "IDX_1"}, "bad"]}) == [{"index_id": "IDX_1"}]
    assert _parse_retrieval_metadata({}) == RetrievalMetadata(chunk_count=1, page_count=1)


def test_stateful_attribution_position_row_to_daily_point_requires_market_values():
    assert _position_row_to_daily_point(row={"valuation_date": None}, currency_mode="BASE_ONLY", reporting_currency=None) is None
    assert _position_row_to_daily_point(
        row={"valuation_date": "2025-01-01"},
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    ) is None
