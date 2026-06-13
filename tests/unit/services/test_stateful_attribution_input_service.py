from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_requests import BenchmarkComponentObservation
from app.services.stateful_attribution_input_service import (
    StatefulAttributionSourceInput,
    _build_benchmark_groups,
    _build_group_key,
    _build_instruments_data,
    _distinct_source_currencies,
    _first_rows_by_position,
    _normalize_group_value,
    _normalized_position_dimensions,
    _parse_index_catalog,
    _parse_position_rows,
    _portfolio_market_values_by_date,
    _position_market_value_pair,
    _position_market_value_totals_by_date,
    _position_meta_from_row,
    _position_row_to_base_weight_point,
    _position_row_to_daily_point,
    _resolve_stateful_attribution_benchmark_id,
    _split_position_cash_flows,
    _stateful_portfolio_position_alignment_mismatches,
    _stateful_position_currencies,
    _summarize_benchmark_classification,
    _summarize_position_classification,
    _validate_stateful_both_currency_support,
    _validate_stateful_group_by,
    _validate_stateful_portfolio_position_alignment,
    _validate_stateful_position_inception_support,
    build_stateful_attribution_input,
    build_stateful_attribution_source_alignment_evidence,
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
        self.assignment_calls: list[dict[str, object]] = []
        self.index_catalog_calls: list[dict[str, object]] = []

    async def get_position_timeseries(self, **kwargs):
        return self.position_response

    async def get_benchmark_assignment(self, **kwargs):
        self.assignment_calls.append(kwargs)
        return self.assignment_response

    async def get_index_catalog(self, **kwargs):
        self.index_catalog_calls.append(kwargs)
        return self.index_response


def test_summarize_position_classification_counts_required_dimensions():
    rows = [
        {"dimensions": {"sector": "Technology", "region": "North America"}},
        {"dimensions": {"sector": "Healthcare", "region": "  "}},
        {"dimensions": {"sector": "Financials"}},
        {"dimensions": "invalid"},
    ]

    summary = _summarize_position_classification(rows=rows, dimensions=["sector", "region"])
    not_required_summary = _summarize_position_classification(rows=rows, dimensions=[])

    assert summary == {
        "status": "partial",
        "classified_row_count": 1,
        "unclassified_row_count": 3,
    }
    assert not_required_summary == {
        "status": "not_required",
        "classified_row_count": 4,
        "unclassified_row_count": 0,
    }


@pytest.mark.asyncio
async def test_resolve_stateful_attribution_benchmark_id_prefers_override_and_reads_assignment():
    service = _AttributionInputServiceStub()
    calculation_id = uuid4()

    override_id = await _resolve_stateful_attribution_benchmark_id(
        stateful_input_service=service,
        portfolio_id="P1",
        as_of_date=date(2025, 1, 1),
        reporting_currency="USD",
        calculation_id=calculation_id,
        benchmark_id_override="BMK_OVERRIDE",
    )
    assigned_id = await _resolve_stateful_attribution_benchmark_id(
        stateful_input_service=service,
        portfolio_id="P1",
        as_of_date=date(2025, 1, 1),
        reporting_currency="USD",
        calculation_id=calculation_id,
        benchmark_id_override=None,
    )

    assert override_id == "BMK_OVERRIDE"
    assert assigned_id == "BMK_1"
    assert service.assignment_calls == [
        {
            "portfolio_id": "P1",
            "as_of_date": date(2025, 1, 1),
            "reporting_currency": "USD",
            "calculation_id": calculation_id,
        }
    ]


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
                    perf_date=date(2025, 1, 1),
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

    calculation_id = uuid4()

    result = await retrieve_stateful_attribution_source_input(
        settings=object(),
        stateful_input_service=service,
        calculation_id=calculation_id,
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
    assert service.index_catalog_calls == [
        {
            "as_of_date": date(2025, 1, 1),
            "index_ids": ["IDX_1"],
            "calculation_id": calculation_id,
        }
    ]


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
                    perf_date=date(2025, 1, 1),
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


@pytest.mark.asyncio
async def test_retrieve_stateful_attribution_source_input_raises_for_assignment_payload_and_index_catalog_failures(
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

    async def _mock_build_benchmark_input(**kwargs):  # noqa: ARG001
        return StatefulBenchmarkNormalizedInput(
            benchmark_currency="USD",
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX_1",
                    component_currency="USD",
                    perf_date=date(2025, 1, 1),
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
        "app.services.stateful_attribution_input_service.retrieve_stateful_portfolio_input",
        _mock_retrieve_stateful_portfolio_input,
    )
    monkeypatch.setattr(
        "app.services.stateful_attribution_input_service.build_stateful_benchmark_input",
        _mock_build_benchmark_input,
    )

    service = _AttributionInputServiceStub()
    service.assignment_response = (200, {})
    with pytest.raises(HTTPException, match="payload missing benchmark_id"):
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
    service.assignment_response = (503, {})
    with pytest.raises(HTTPException, match="benchmark assignment source unavailable"):
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
    service.index_response = (503, {})
    with pytest.raises(HTTPException, match="index catalog source unavailable"):
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
                    "beginning_market_value": "900",
                    "ending_market_value": "909",
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
                perf_date=date(2025, 1, 1),
                weight_bop=0.5,
                component_return=0.01,
                component_return_local=0.01,
                component_return_fx=0.0,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_2",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
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
    assert normalized.instruments_data[0].meta["sector"] == "tech"
    assert normalized.instruments_data[0].valuation_points[0].bod_cf == 5
    assert normalized.benchmark_groups_data[0].key["sector"] == "tech"
    assert normalized.benchmark_groups_data[0].observations[0].return_base == pytest.approx(0.02)
    assert normalized.benchmark_groups_data[0].observations[0].return_local == pytest.approx(0.02)
    assert normalized.benchmark_groups_data[0].observations[0].return_fx == pytest.approx(0.0)
    assert normalized.source_alignment_evidence["position_classification"] == {
        "status": "complete",
        "classified_row_count": 1,
        "unclassified_row_count": 0,
    }
    assert normalized.source_alignment_evidence["benchmark_classification"] == {
        "status": "complete",
        "classified_component_count": 2,
        "unclassified_component_count": 0,
    }


def test_summarize_benchmark_classification_reports_partial_classification():
    summary = _summarize_benchmark_classification(
        component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_A",
                perf_date=date(2026, 3, 31),
                weight_bop=0.6,
                component_return=0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_B",
                perf_date=date(2026, 3, 31),
                weight_bop=0.4,
                component_return=0.02,
            ),
        ],
        index_records=[
            {"index_id": "IDX_A", "classification_labels": {"sector": "technology"}},
            {"index_id": "IDX_B", "classification_labels": {"sector": ""}},
            {"index_id": "IGNORED", "classification_labels": {"sector": "cash"}},
        ],
        dimensions=["sector"],
    )

    assert summary == {
        "status": "partial",
        "classified_component_count": 1,
        "unclassified_component_count": 1,
    }


def test_stateful_attribution_source_alignment_evidence_captures_source_limitations():
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
                "valuation_date": "2025-01-01",
                "position_currency": "EUR",
                "beginning_market_value_reporting_currency": "600",
                "ending_market_value_reporting_currency": "606",
                "dimensions": {"sector": "Technology"},
            },
            {
                "position_id": "POS_2",
                "valuation_date": "2025-01-01",
                "position_currency": "USD",
                "beginning_market_value_reporting_currency": "400",
                "ending_market_value_reporting_currency": "404",
                "dimensions": {},
            },
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=2, page_count=3),
        benchmark_id="BMK_PRIVATE_BANKING_BALANCED",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_EQUITY",
                component_currency="EUR",
                perf_date=date(2025, 1, 1),
                weight_bop=0.6,
                component_return=0.01,
                component_return_local=0.01,
                component_return_fx=0.0,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_BOND",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
                weight_bop=0.4,
                component_return=0.005,
                component_return_local=0.005,
                component_return_fx=0.0,
            ),
        ],
        benchmark_source_details={"benchmark_components": 2, "benchmark_chunk_count": 1, "benchmark_page_count": 2},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=2),
        index_records=[
            {"index_id": "IDX_EQUITY", "classification_labels": {"sector": "Technology"}},
            {"index_id": "IDX_BOND", "classification_labels": {}},
        ],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    evidence = build_stateful_attribution_source_alignment_evidence(
        source_input=source_input,
        group_by=["sector", "currency"],
        currency_mode="BOTH",
        fx={"rates": [{"date": "2024-12-31", "ccy": "EUR", "rate": 1.1}]},
        reporting_currency="USD",
    )

    assert evidence["benchmark_id"] == "BMK_PRIVATE_BANKING_BALANCED"
    assert evidence["classification_dimensions"] == ["sector"]
    assert evidence["position_classification"] == {
        "status": "partial",
        "classified_row_count": 1,
        "unclassified_row_count": 1,
    }
    assert evidence["benchmark_classification"] == {
        "status": "partial",
        "classified_component_count": 1,
        "unclassified_component_count": 1,
    }
    assert evidence["currency_source"] == {
        "status": "required",
        "reporting_currency": "USD",
        "position_currency_count": 2,
        "benchmark_component_currency_count": 2,
        "fx_required": True,
        "fx_supplied": True,
    }
    assert evidence["source_contract_limitations"] == {
        "benchmark_version": "not_available_from_current_lotus_core_contract",
        "classification_version": "not_available_from_current_lotus_core_contract",
        "calendar_policy": "not_available_from_current_lotus_core_contract",
        "off_benchmark_policy": "derived_by_lotus_performance_from_portfolio_and_benchmark_exposure",
        "derivative_or_short_flags": "not_available_from_current_lotus_core_contract",
        "fee_tax_income_breakout": "not_available_from_current_lotus_core_contract",
    }


def test_distinct_source_currencies_filters_deduplicates_and_sorts_values():
    assert _distinct_source_currencies(["USD", None, "", "EUR", "USD", 1]) == ["EUR", "USD"]


def test_build_stateful_attribution_input_rejects_missing_benchmark_observations():
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

    with pytest.raises(HTTPException, match="No normalized benchmark component observations"):
        build_stateful_attribution_input(
            source_input=source_input,
            mode="by_instrument",
            group_by=["sector"],
            metric_basis="NET",
            currency_mode="BASE_ONLY",
            fx=None,
            reporting_currency="USD",
        )


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
                    "beginning_market_value": "990",
                    "ending_market_value": "1009.8",
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
                "ending_market_value_reporting_currency": "1009.8",
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
                perf_date=date(2025, 1, 1),
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

    assert normalized.instruments_data[0].meta["currency"] == "eur"
    assert normalized.instruments_data[0].valuation_points[0].begin_mv == 900
    assert normalized.instruments_data[0].meta["base_weight_points"] == [
        {"perf_date": "2025-01-01", "begin_mv": 990, "bod_cf": 0}
    ]
    assert normalized.benchmark_groups_data[0].key["currency"] == "eur"
    assert normalized.benchmark_groups_data[0].observations[0].return_local == pytest.approx(0.02)
    assert normalized.benchmark_groups_data[0].observations[0].return_fx == pytest.approx(0.01)


def test_build_stateful_attribution_input_rejects_portfolio_position_alignment_gaps():
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
                "beginning_market_value_portfolio_currency": "900",
                "ending_market_value_portfolio_currency": "909",
                "cash_flows": [],
                "dimensions": {"sector": "Tech"},
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_1",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.01,
                component_return_local=0.01,
                component_return_fx=0.0,
            )
        ],
        benchmark_source_details={"benchmark_components": 1},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[{"index_id": "IDX_1", "classification_labels": {"sector": "Tech"}}],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    with pytest.raises(HTTPException, match="portfolio timeseries does not align with summed position timeseries"):
        build_stateful_attribution_input(
            source_input=source_input,
            mode="by_instrument",
            group_by=["sector"],
            metric_basis="NET",
            currency_mode="BASE_ONLY",
            fx=None,
            reporting_currency="USD",
        )


def test_build_stateful_attribution_input_allows_internal_trade_timing_alignment_gap():
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
                "position_to_portfolio_fx_rate": "1",
                "portfolio_to_reporting_fx_rate": "1",
                "beginning_market_value_portfolio_currency": "1100",
                "ending_market_value_portfolio_currency": "1010",
                "cash_flows": [
                    {
                        "amount": "-100",
                        "timing": "eod",
                        "cash_flow_type": "internal_trade_flow",
                    }
                ],
                "dimensions": {"sector": "Tech"},
            }
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_1",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.01,
                component_return_local=0.01,
                component_return_fx=0.0,
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
        group_by=["sector"],
        metric_basis="NET",
        currency_mode="BASE_ONLY",
        fx=None,
        reporting_currency="USD",
    )

    assert normalized.instruments_data[0].valuation_points[0].eod_cf == -100
    assert normalized.instruments_data[0].meta["sector"] == "tech"


def test_stateful_attribution_alignment_validator_tolerates_unusable_rows_and_internal_flow_noise():
    _validate_stateful_portfolio_position_alignment(
        portfolio_observations=[
            {"valuation_date": None, "beginning_market_value": "0", "ending_market_value": "0"},
            {"valuation_date": "2025-01-01", "beginning_market_value": "100", "ending_market_value": "110"},
        ],
        position_rows=[
            {"valuation_date": date(2025, 1, 1), "beginning_market_value_portfolio_currency": "1"},
            {"valuation_date": "2025-01-01", "cash_flows": []},
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "110",
                "cash_flows": [
                    "not-a-flow",
                    {"amount": None, "cash_flow_type": "internal_trade_flow"},
                    {"amount": "7", "cash_flow_type": "external_contribution"},
                    {"amount": "-5", "cash_flow_type": "internal_trade_flow"},
                ],
            },
            {
                "valuation_date": "2025-01-02",
                "beginning_market_value_portfolio_currency": "50",
                "ending_market_value_portfolio_currency": "51",
                "cash_flows": "not-a-list",
            },
        ],
        reporting_currency=None,
    )


def test_portfolio_market_values_by_date_skips_incomplete_observations():
    values_by_date = _portfolio_market_values_by_date(
        [
            {"valuation_date": None, "beginning_market_value": "1", "ending_market_value": "2"},
            {"valuation_date": "2025-01-01", "beginning_market_value": "100", "ending_market_value": "110"},
            {"valuation_date": "2025-01-02", "beginning_market_value": None, "ending_market_value": "120"},
        ]
    )

    assert values_by_date == {"2025-01-01": (Decimal("100"), Decimal("110"))}


def test_position_market_value_totals_prefer_reporting_currency_and_fallback_to_portfolio_currency():
    totals_by_date = _position_market_value_totals_by_date(
        position_rows=[
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value_reporting_currency": "100",
                "ending_market_value_reporting_currency": "110",
                "beginning_market_value_portfolio_currency": "999",
                "ending_market_value_portfolio_currency": "999",
                "cash_flows": [{"amount": "-5", "cash_flow_type": "internal_trade_flow"}],
            },
            {
                "valuation_date": "2025-01-01",
                "beginning_market_value_portfolio_currency": "20",
                "ending_market_value_portfolio_currency": "25",
                "cash_flows": [{"amount": "2", "cash_flow_type": "external_contribution"}],
            },
        ],
        reporting_currency="USD",
    )

    assert totals_by_date["2025-01-01"]["begin"] == Decimal("120")
    assert totals_by_date["2025-01-01"]["end"] == Decimal("135")
    assert totals_by_date["2025-01-01"]["internal_flow_abs"] == Decimal("5")


def test_position_market_value_pair_prefers_reporting_currency_and_skips_incomplete_rows():
    assert _position_market_value_pair(
        row={
            "beginning_market_value_reporting_currency": "100",
            "ending_market_value_reporting_currency": "110",
            "beginning_market_value_portfolio_currency": "999",
            "ending_market_value_portfolio_currency": "999",
        },
        reporting_currency="USD",
    ) == ("100", "110")
    assert _position_market_value_pair(
        row={
            "beginning_market_value_portfolio_currency": "200",
            "ending_market_value_portfolio_currency": "210",
        },
        reporting_currency="USD",
    ) == ("200", "210")
    assert _position_market_value_pair(
        row={
            "beginning_market_value_reporting_currency": "100",
            "beginning_market_value_portfolio_currency": "200",
            "ending_market_value_portfolio_currency": "210",
        },
        reporting_currency="USD",
    ) == ("200", "210")
    assert (
        _position_market_value_pair(
            row={"beginning_market_value_portfolio_currency": "200"},
            reporting_currency=None,
        )
        is None
    )


def test_first_rows_by_position_orders_by_position_and_valuation_date():
    rows = [
        {"position_id": "POS_B", "valuation_date": "2025-01-02", "marker": "b-late"},
        {"position_id": "POS_A", "valuation_date": "2025-01-02", "marker": "a-late"},
        {"position_id": "POS_A", "valuation_date": "2025-01-01", "marker": "a-first"},
        {"position_id": None, "valuation_date": "2025-01-01", "marker": "invalid"},
        {"position_id": "POS_B", "valuation_date": "2025-01-01", "marker": "b-first"},
    ]

    first_rows = _first_rows_by_position(rows)

    assert list(first_rows) == ["POS_A", "POS_B"]
    assert first_rows["POS_A"]["marker"] == "a-first"
    assert first_rows["POS_B"]["marker"] == "b-first"


def test_stateful_portfolio_position_alignment_mismatches_allows_internal_transfer_timing_noise():
    mismatches = _stateful_portfolio_position_alignment_mismatches(
        portfolio_by_date={"2025-01-01": (Decimal("100"), Decimal("100"))},
        position_totals_by_date={
            "2025-01-01": {
                "begin": Decimal("95"),
                "end": Decimal("95"),
                "internal_flow_abs": Decimal("5"),
            }
        },
    )

    assert mismatches == []


def test_stateful_portfolio_position_alignment_mismatches_reports_unexplained_gap():
    mismatches = _stateful_portfolio_position_alignment_mismatches(
        portfolio_by_date={"2025-01-01": (Decimal("100"), Decimal("110"))},
        position_totals_by_date={
            "2025-01-01": {
                "begin": Decimal("90"),
                "end": Decimal("105"),
                "internal_flow_abs": Decimal("1"),
            }
        },
    )

    assert mismatches == ["2025-01-01 (portfolio begin/end=100/110, positions begin/end=90/105)"]


def test_stateful_attribution_source_alignment_evidence_flags_unclassified_source_rows_and_benchmark_components():
    benchmark_component_observations = [
        BenchmarkComponentObservation(
            component_id="IDX_1",
            component_currency="USD",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.01,
            component_return_local=0.01,
            component_return_fx=0.0,
        ),
        BenchmarkComponentObservation(
            component_id="IDX_MISSING_LABELS",
            component_currency="USD",
            perf_date=date(2025, 1, 1),
            weight_bop=0.5,
            component_return=0.02,
            component_return_local=0.02,
            component_return_fx=0.0,
        ),
    ]
    source_input = StatefulAttributionSourceInput(
        portfolio_input=StatefulPortfolioInput(performance_start_date=date(2025, 1, 1), observations=[]),
        position_rows=[
            {"position_id": "POS_1", "dimensions": "not-a-dict"},
            {"position_id": "POS_2", "dimensions": {"sector": "Technology"}},
        ],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_1",
        benchmark_component_observations=benchmark_component_observations,
        benchmark_source_details={"benchmark_components": 2},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[{"index_id": "IDX_1", "classification_labels": {"sector": "Technology"}}],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )

    evidence = build_stateful_attribution_source_alignment_evidence(
        source_input=source_input,
        group_by=["sector"],
        currency_mode="BASE_ONLY",
        fx=None,
        reporting_currency="USD",
    )

    assert evidence["position_classification"] == {
        "status": "partial",
        "classified_row_count": 1,
        "unclassified_row_count": 1,
    }
    assert evidence["benchmark_classification"] == {
        "status": "partial",
        "classified_component_count": 1,
        "unclassified_component_count": 1,
    }


def test_stateful_attribution_rejects_unsupported_position_inception_window():
    with pytest.raises(HTTPException, match="cannot safely compute acquisition-day position returns"):
        _validate_stateful_position_inception_support(
            rows=[
                {
                    "position_id": None,
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "0",
                    "ending_market_value_portfolio_currency": "5",
                    "cash_flows": [],
                },
                {
                    "position_id": "POS_NEW",
                    "valuation_date": "2025-01-01",
                    "beginning_market_value_portfolio_currency": "0",
                    "ending_market_value_portfolio_currency": "5",
                    "cash_flows": [],
                },
                {
                    "position_id": "POS_NEW",
                    "valuation_date": "2025-01-02",
                    "beginning_market_value_portfolio_currency": "5",
                    "ending_market_value_portfolio_currency": "6",
                    "cash_flows": [],
                },
            ]
        )


def test_stateful_attribution_group_by_and_benchmark_validation_errors():
    with pytest.raises(HTTPException, match="Unsupported: issuer"):
        _validate_stateful_group_by(["issuer"])

    assert _build_group_key(labels={"sector": ""}, group_by=["sector"], index_id="IDX_1") == (("sector", "unknown"),)

    with pytest.raises(HTTPException, match="Benchmark component IDX_1 missing classification label for currency"):
        _build_group_key(labels={}, group_by=["currency"], index_id="IDX_1")

    with pytest.raises(HTTPException, match="missing classification labels"):
        _build_benchmark_groups(
            group_by=["sector"],
            component_observations=[
                BenchmarkComponentObservation(
                    component_id="IDX_1",
                    component_currency="USD",
                    perf_date=date(2025, 1, 1),
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


def test_stateful_attribution_builds_unknown_bucket_for_missing_benchmark_labels():
    groups = _build_benchmark_groups(
        group_by=["sector"],
        component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.01,
                component_return_local=0.01,
                component_return_fx=0.0,
            )
        ],
        index_records=[{"index_id": "IDX_1", "classification_labels": {}}],
    )

    assert groups[0].key == {"sector": "unknown"}


def test_stateful_attribution_aggregates_benchmark_components_by_group_and_date():
    groups = _build_benchmark_groups(
        group_by=["sector"],
        component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_TECH_A",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
                weight_bop=0.25,
                component_return=0.04,
                component_return_local=0.03,
                component_return_fx=0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_TECH_B",
                component_currency="USD",
                perf_date=date(2025, 1, 1),
                weight_bop=0.75,
                component_return=0.02,
                component_return_local=0.015,
                component_return_fx=0.005,
            ),
        ],
        index_records=[
            {"index_id": "IDX_TECH_A", "classification_labels": {"sector": "Technology"}},
            {"index_id": "IDX_TECH_B", "classification_labels": {"sector": "Technology"}},
        ],
    )

    assert len(groups) == 1
    assert groups[0].key == {"sector": "technology"}
    observation = groups[0].observations[0]
    assert observation.weight_bop == pytest.approx(1.0)
    assert observation.return_base == pytest.approx(0.025)
    assert observation.return_local == pytest.approx(0.01875)
    assert observation.return_fx == pytest.approx(0.00625)


def test_stateful_attribution_parsers_filter_invalid_rows():
    assert _split_position_cash_flows(None) == (0, 0)
    assert _split_position_cash_flows(["bad", {"amount": None, "timing": "bod"}]) == (0, 0)
    assert _split_position_cash_flows([{"amount": "4", "timing": "bod"}, {"amount": "-1", "timing": "eod"}]) == (
        Decimal("4"),
        Decimal("-1"),
    )
    assert _position_meta_from_row(
        {
            "security_id": "SEC_1",
            "cash_flow_currency": "EUR",
            "position_to_portfolio_fx_rate": "1.2",
            "portfolio_to_reporting_fx_rate": "1.1",
            "dimensions": {"sector": "Tech", "rank": 3},
        }
    ) == {
        "security_id": "SEC_1",
        "cash_flow_currency": "eur",
        "position_to_portfolio_fx_rate": Decimal("1.2"),
        "portfolio_to_reporting_fx_rate": Decimal("1.1"),
        "sector": "tech",
        "rank": 3,
    }
    assert _parse_position_rows({"rows": [{"position_id": "POS_1"}, "bad"]}) == [{"position_id": "POS_1"}]
    assert _parse_index_catalog({"records": [{"index_id": "IDX_1"}, "bad"]}) == [{"index_id": "IDX_1"}]


def test_stateful_attribution_normalizes_group_values():
    assert _normalize_group_value("Fixed Income") == "fixed_income"


def test_stateful_attribution_normalizes_position_dimensions():
    assert _normalized_position_dimensions(
        {
            "asset_class": "Fixed Income",
            "rank": 3,
            "nullable": None,
            7: "ignored",
        }
    ) == {
        "asset_class": "fixed_income",
        "rank": 3,
    }
    assert _normalized_position_dimensions(None) == {}


def test_stateful_attribution_builds_normalized_group_key():
    assert _build_group_key(
        labels={"asset_class": "Equity"},
        group_by=["asset_class"],
        index_id="IDX_1",
    ) == (("asset_class", "equity"),)


def test_stateful_attribution_position_row_to_daily_point_requires_market_values():
    assert (
        _position_row_to_daily_point(row={"valuation_date": None}, currency_mode="BASE_ONLY", reporting_currency=None)
        is None
    )
    assert (
        _position_row_to_daily_point(
            row={"valuation_date": "2025-01-01"},
            currency_mode="BASE_ONLY",
            reporting_currency="USD",
        )
        is None
    )


def test_stateful_attribution_position_row_to_daily_point_falls_back_from_null_reporting_currency_values():
    point = _position_row_to_daily_point(
        row={
            "valuation_date": "2025-01-01",
            "beginning_market_value_reporting_currency": None,
            "ending_market_value_reporting_currency": None,
            "beginning_market_value_portfolio_currency": "100",
            "ending_market_value_portfolio_currency": "101",
            "cash_flows": [],
        },
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    assert point == {
        "perf_date": "2025-01-01",
        "begin_mv": 100,
        "end_mv": 101,
        "bod_cf": 0,
        "eod_cf": 0,
    }


def test_stateful_attribution_position_row_to_daily_point_converts_cash_flows_to_reporting_currency():
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
            ],
        },
        currency_mode="BASE_ONLY",
        reporting_currency="USD",
    )

    assert point == {
        "perf_date": "2025-01-01",
        "begin_mv": Decimal("132"),
        "end_mv": Decimal("145.2"),
        "bod_cf": Decimal("6.60"),
        "eod_cf": Decimal("-2.64"),
    }


def test_stateful_attribution_base_weight_point_converts_bod_cash_flow_to_reporting_currency():
    point = _position_row_to_base_weight_point(
        row={
            "valuation_date": "2025-01-01",
            "position_currency": "EUR",
            "cash_flow_currency": "EUR",
            "position_to_portfolio_fx_rate": "1.20",
            "portfolio_to_reporting_fx_rate": "1.10",
            "beginning_market_value_reporting_currency": "132",
            "cash_flows": [{"amount": "5", "timing": "bod"}],
        },
        reporting_currency="USD",
    )

    assert point == {
        "perf_date": "2025-01-01",
        "begin_mv": Decimal("132"),
        "bod_cf": Decimal("6.60"),
    }


def test_stateful_attribution_base_weight_point_handles_missing_dates_and_fallback_values():
    assert _position_row_to_base_weight_point(row={"valuation_date": None}, reporting_currency="USD") is None
    assert (
        _position_row_to_base_weight_point(
            row={"valuation_date": "2025-01-01"},
            reporting_currency=None,
        )
        is None
    )
    assert _position_row_to_base_weight_point(
        row={
            "valuation_date": "2025-01-01",
            "beginning_market_value_reporting_currency": None,
            "beginning_market_value_portfolio_currency": "100",
            "cash_flows": [],
        },
        reporting_currency="USD",
    ) == {
        "perf_date": "2025-01-01",
        "begin_mv": Decimal("100"),
        "bod_cf": Decimal("0"),
    }


def test_stateful_attribution_build_instruments_data_skips_invalid_rows_and_none_points():
    instruments = _build_instruments_data(
        rows=[
            {"position_id": "POS_BAD", "valuation_date": None},
            {
                "position_id": "POS_MISSING_VALUES",
                "valuation_date": "2025-01-01",
            },
            {
                "position_id": "POS_OK",
                "valuation_date": "2025-01-01",
                "security_id": "SEC_1",
                "beginning_market_value_portfolio_currency": "100",
                "ending_market_value_portfolio_currency": "102",
                "cash_flows": [],
            },
        ],
        currency_mode="BASE_ONLY",
        reporting_currency=None,
    )

    assert len(instruments) == 1
    assert instruments[0].instrument_id == "POS_OK"
    assert instruments[0].valuation_points[0].begin_mv == Decimal("100")


def test_stateful_attribution_both_currency_validation_errors_are_explicit():
    with pytest.raises(HTTPException, match="requires report_ccy when currency_mode=BOTH"):
        _validate_stateful_both_currency_support(rows=[], reporting_currency=None, fx=None)

    with pytest.raises(HTTPException, match="requires position_currency"):
        _validate_stateful_both_currency_support(
            rows=[{"position_id": "POS_1"}],
            reporting_currency="USD",
            fx=None,
        )

    with pytest.raises(HTTPException, match="requires fx.rates"):
        _validate_stateful_both_currency_support(
            rows=[{"position_id": "POS_1", "position_currency": "EUR"}],
            reporting_currency="USD",
            fx=None,
        )


def test_stateful_position_currencies_preserves_non_empty_strings_and_ignores_missing_values():
    assert _stateful_position_currencies(
        [
            {"position_id": "POS_1", "position_currency": "EUR"},
            {"position_id": "POS_2", "position_currency": " "},
            {"position_id": "POS_3", "position_currency": ""},
            {"position_id": "POS_4", "position_currency": None},
            {"position_id": "POS_5", "position_currency": 123},
            {"position_id": "POS_6", "position_currency": "USD"},
        ]
    ) == {" ", "EUR", "USD"}
