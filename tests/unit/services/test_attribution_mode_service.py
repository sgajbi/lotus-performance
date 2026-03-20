from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.attribution_analytics_requests import AttributionAnalyticsRequest, AttributionInputMode
from app.models.benchmark_requests import BenchmarkComponentObservation
from app.services.attribution_mode_service import resolve_attribution_request
from app.services.stateful_attribution_input_service import StatefulAttributionSourceInput
from app.services.stateful_input_service import RetrievalMetadata
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
                date=date(2025, 1, 1),
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
