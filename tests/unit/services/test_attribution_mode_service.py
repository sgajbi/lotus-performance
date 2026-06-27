from __future__ import annotations

from datetime import date
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.attribution_requests import AttributionPortfolioData, BenchmarkGroup, InstrumentData
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.models.requests import DailyInputData
from app.services.attribution_mode_service import (
    _attribution_normalization_stage_details,
    _attribution_retrieval_stage_details,
    _retrieve_attribution_source_input,
    resolve_attribution_request,
)
from app.services.stateful_attribution_input_service import (
    StatefulAttributionNormalizedInput,
    StatefulAttributionSourceInput,
)
from app.services.stateful_input_service import RetrievalMetadata, StatefulInputService
from app.services.stateful_performance_input_service import StatefulPortfolioInput


@pytest.mark.asyncio
async def test_resolve_attribution_request_passthroughs_stateless_mode():
    request = AttributionAnalyticsRequest.model_validate(
        {
            "portfolio_id": "ATTRIB_STATELESS",
            "mode": "by_group",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "benchmark_groups_data": [
                {
                    "key": {"sector": "Tech"},
                    "observations": [{"date": "2025-01-01", "return_base": 0.01, "weight_bop": 1.0}],
                }
            ],
        }
    )

    resolved = await resolve_attribution_request(request, settings=object())

    assert resolved.input_mode == AttributionInputMode.STATELESS
    assert resolved.attribution_request.group_by == ["sector"]


@pytest.mark.asyncio
async def test_resolve_attribution_request_fails_retrieval_stage(monkeypatch):
    failed: list[tuple] = []

    async def _boom(**kwargs):  # noqa: ARG001
        raise HTTPException(status_code=503, detail="source unavailable")

    monkeypatch.setattr("app.services.attribution_mode_service.build_stateful_input_service", lambda settings: object())
    monkeypatch.setattr("app.services.attribution_mode_service.retrieve_stateful_attribution_source_input", _boom)
    monkeypatch.setattr(
        "app.services.attribution_mode_service.execution_registry.start_stage", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "app.services.attribution_mode_service.execution_registry.complete_stage", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "app.services.attribution_mode_service.execution_registry.fail_stage",
        lambda *args, **kwargs: failed.append(args),
    )

    request = AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "ATTRIB_STATEFUL",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    with pytest.raises(HTTPException, match="source unavailable"):
        await resolve_attribution_request(request, settings=object())

    assert failed and failed[0][1] == "retrieval"


@pytest.mark.asyncio
async def test_resolve_attribution_request_fails_normalization_stage(monkeypatch):
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
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                perf_date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.01,
            )
        ],
        benchmark_source_details={"benchmark_components": 1},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )
    failed: list[tuple] = []

    monkeypatch.setattr("app.services.attribution_mode_service.build_stateful_input_service", lambda settings: object())

    async def _mock_retrieve(**kwargs):  # noqa: ARG001
        return source_input

    monkeypatch.setattr(
        "app.services.attribution_mode_service.retrieve_stateful_attribution_source_input", _mock_retrieve
    )
    monkeypatch.setattr(
        "app.services.attribution_mode_service.build_stateful_attribution_input",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("bad normalization")),
    )
    monkeypatch.setattr(
        "app.services.attribution_mode_service.execution_registry.start_stage", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "app.services.attribution_mode_service.execution_registry.complete_stage", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "app.services.attribution_mode_service.execution_registry.fail_stage",
        lambda *args, **kwargs: failed.append(args),
    )

    request = AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": str(uuid4()),
            "portfolio_id": "ATTRIB_STATEFUL",
            "mode": "by_instrument",
            "group_by": ["sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-01",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {},
        }
    )

    with pytest.raises(ValueError, match="bad normalization"):
        await resolve_attribution_request(request, settings=object())

    assert failed and failed[0][1] == "normalization"


def test_attribution_retrieval_stage_details_preserve_source_counts():
    source_input = StatefulAttributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[{"valuation_date": "2025-01-01"}, {"valuation_date": "2025-01-02"}],
            retrieval_metadata=RetrievalMetadata(chunk_count=3, page_count=4),
        ),
        position_rows=[{"instrument_id": "AAPL"}, {"instrument_id": "MSFT"}],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=5, page_count=6),
        benchmark_id="BMK_1",
        benchmark_component_observations=[
            BenchmarkComponentObservation(
                component_id="IDX_1",
                perf_date=date(2025, 1, 1),
                weight_bop=1.0,
                component_return=0.01,
            ),
            BenchmarkComponentObservation(
                component_id="IDX_2",
                perf_date=date(2025, 1, 1),
                weight_bop=0.0,
                component_return=0.0,
            ),
        ],
        benchmark_source_details={
            "benchmark_components": 2,
            "fx_pair_count": 1,
            "fx_chunk_count": 7,
            "fx_page_count": 8,
        },
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=9, page_count=10),
        index_records=[{"component_id": "IDX_1"}],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=11, page_count=12),
    )

    assert _attribution_retrieval_stage_details(source_input) == {
        "portfolio_observations": 2,
        "position_rows": 2,
        "benchmark_components": 2,
        "benchmark_component_observations": 2,
        "portfolio_chunk_count": 3,
        "portfolio_page_count": 4,
        "position_chunk_count": 5,
        "position_page_count": 6,
        "benchmark_chunk_count": 9,
        "benchmark_page_count": 10,
        "fx_pair_count": 1,
        "fx_chunk_count": 7,
        "fx_page_count": 8,
        "index_request_count": 12,
    }


@pytest.mark.asyncio
async def test_retrieve_attribution_source_input_forwards_stateful_request_contract(monkeypatch):
    source_input = StatefulAttributionSourceInput(
        portfolio_input=StatefulPortfolioInput(
            performance_start_date=date(2025, 1, 1),
            observations=[{"valuation_date": "2025-01-01"}],
        ),
        position_rows=[],
        position_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        benchmark_id="BMK_PRIVATE_BANKING_BALANCED",
        benchmark_component_observations=[],
        benchmark_source_details={},
        benchmark_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
        index_records=[],
        index_retrieval_metadata=RetrievalMetadata(chunk_count=1, page_count=1),
    )
    captured: dict[str, object] = {}

    async def _capture_source_input(**kwargs):
        captured.update(kwargs)
        return source_input

    monkeypatch.setattr(
        "app.services.attribution_mode_service.retrieve_stateful_attribution_source_input",
        _capture_source_input,
    )
    calculation_id = str(uuid4())
    request = AttributionAnalyticsRequest.model_validate(
        {
            "calculation_id": calculation_id,
            "portfolio_id": "PB_SG_GLOBAL_BAL_001",
            "mode": "by_instrument",
            "group_by": ["asset_class", "sector"],
            "linking": "none",
            "frequency": "daily",
            "report_start_date": "2025-01-01",
            "report_end_date": "2025-01-31",
            "report_ccy": "USD",
            "analyses": [{"period": "ITD", "frequencies": ["daily"]}],
            "input_mode": "stateful",
            "stateful_input": {
                "benchmark_id": "BMK_PRIVATE_BANKING_BALANCED",
                "dimensions": ["asset_class", "sector"],
                "include_cash_flows": False,
                "filters": {"security_ids": ["SEC_PRIVATE_BANKING_EQ_01"]},
            },
        }
    )

    assert request.stateful_input is not None
    result = await _retrieve_attribution_source_input(
        request=request,
        stateful_input=request.stateful_input,
        settings=cast(Settings, object()),
        stateful_input_service=cast(StatefulInputService, object()),
    )

    assert result is source_input
    assert str(captured["calculation_id"]) == calculation_id
    assert captured["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert captured["as_of_date"] == date(2025, 1, 31)
    assert captured["report_start_date"] == date(2025, 1, 1)
    assert captured["report_end_date"] == date(2025, 1, 31)
    assert captured["reporting_currency"] == "USD"
    assert captured["consumer_system"] == "lotus-performance"
    assert captured["group_by"] == ["asset_class", "sector"]
    assert captured["dimensions"] == ["asset_class", "sector"]
    assert captured["include_cash_flows"] is False
    assert captured["filters"] == {
        "security_ids": ["SEC_PRIVATE_BANKING_EQ_01"],
        "position_ids": [],
        "dimension_filters": [],
    }
    assert captured["benchmark_id_override"] == "BMK_PRIVATE_BANKING_BALANCED"


def test_attribution_normalization_stage_details_preserve_alignment_evidence():
    normalized_input = StatefulAttributionNormalizedInput(
        portfolio_data=AttributionPortfolioData(
            metric_basis="NET",
            valuation_points=[
                DailyInputData(
                    perf_date=date(2025, 1, 1),
                    begin_mv=100.0,
                    end_mv=101.0,
                )
            ],
        ),
        instruments_data=[
            InstrumentData(
                instrument_id="AAPL",
                meta={"sector": "Technology"},
                valuation_points=[
                    DailyInputData(
                        perf_date=date(2025, 1, 1),
                        begin_mv=50.0,
                        end_mv=51.0,
                    )
                ],
            )
        ],
        benchmark_groups_data=[
            BenchmarkGroup(
                key={"sector": "Technology"},
                observations=[{"date": date(2025, 1, 1), "weight_bop": 1.0, "return_base": 0.01}],
            )
        ],
        source_alignment_evidence={"position_classification": {"missing": 0}},
    )

    assert _attribution_normalization_stage_details(normalized_input) == {
        "portfolio_points": 1,
        "instruments": 1,
        "benchmark_groups": 1,
        "source_alignment": {"position_classification": {"missing": 0}},
    }
