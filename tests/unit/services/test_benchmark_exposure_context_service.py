from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_exposure_context import (
    BenchmarkExposureContextRequest,
    BenchmarkExposureGroupingDimension,
    BenchmarkExposureWindow,
)
from app.services.benchmark_exposure_context_service import build_benchmark_exposure_context


class _StatefulInputServiceStub:
    def __init__(self) -> None:
        self.assignment_calls: list[dict[str, object]] = []
        self.market_series_calls: list[dict[str, object]] = []
        self.index_catalog_calls: list[dict[str, object]] = []

    async def get_benchmark_assignment(self, **kwargs):
        self.assignment_calls.append(kwargs)
        return 200, {"benchmark_id": "BMK_GLOBAL_60_40"}

    async def get_index_catalog(self, **kwargs):
        self.index_catalog_calls.append(kwargs)
        return (
            200,
            {
                "records": [
                    {
                        "index_id": "IDX_TECH_A",
                        "classification_labels": {"sector": "Technology", "asset_class": "Equity"},
                    },
                    {
                        "index_id": "IDX_TECH_B",
                        "classification_labels": {"sector": "Technology", "asset_class": "Equity"},
                    },
                    {
                        "index_id": "IDX_BOND",
                        "classification_labels": {"sector": "Government Bonds", "asset_class": "Fixed Income"},
                    },
                ]
            },
        )

    async def get_benchmark_market_series(self, **kwargs):
        self.market_series_calls.append(kwargs)
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_TECH_A",
                        "points": [
                            {"series_date": "2026-01-02", "component_weight": "0.35"},
                            {"series_date": "2026-01-03", "component_weight": "0.36"},
                        ],
                    },
                    {
                        "index_id": "IDX_TECH_B",
                        "points": [
                            {"series_date": "2026-01-02", "component_weight": "0.25"},
                            {"series_date": "2026-01-03", "component_weight": "0.24"},
                        ],
                    },
                    {
                        "index_id": "IDX_BOND",
                        "points": [
                            {"series_date": "2026-01-02", "component_weight": "0.40"},
                            {"series_date": "2026-01-03", "component_weight": "0.40"},
                        ],
                    },
                ],
                "retrieval_metadata": {"chunk_count": 1, "page_count": 2},
            },
        )


def _request(**overrides) -> BenchmarkExposureContextRequest:
    payload = {
        "calculation_id": uuid4(),
        "portfolio_id": "PB_SG_GLOBAL_BAL_001",
        "as_of_date": date(2026, 1, 3),
        "window": BenchmarkExposureWindow(start_date=date(2026, 1, 2), end_date=date(2026, 1, 3)),
        "reporting_currency": "USD",
        "grouping_dimensions": [
            BenchmarkExposureGroupingDimension.POSITION,
            BenchmarkExposureGroupingDimension.SECTOR,
            BenchmarkExposureGroupingDimension.ASSET_CLASS,
        ],
    }
    payload.update(overrides)
    return BenchmarkExposureContextRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_groups_and_aligns_weights() -> None:
    service = _StatefulInputServiceStub()

    response = await build_benchmark_exposure_context(request=_request(), stateful_input_service=service)

    assert response.benchmark_id == "BMK_GLOBAL_60_40"
    assert response.metadata.source_system == "lotus-core"
    assert response.metadata.served_by == "lotus-performance"
    assert response.metadata.retrieval_metadata == {
        "benchmark_market_series_chunk_count": 1,
        "benchmark_market_series_page_count": 2,
        "index_catalog_page_count": 1,
    }
    weights = {
        (row.valuation_date.isoformat(), row.grouping_dimension.value, row.group_key): row.weight
        for row in response.rows
    }
    assert weights[("2026-01-02", "SECTOR", "SECTOR_Technology")] == Decimal("0.60")
    assert weights[("2026-01-02", "ASSET_CLASS", "ASSET_CLASS_Equity")] == Decimal("0.60")
    assert weights[("2026-01-02", "POSITION", "IDX_TECH_A")] == Decimal("0.35")
    assert service.assignment_calls[0]["portfolio_id"] == "PB_SG_GLOBAL_BAL_001"
    assert service.market_series_calls[0]["series_fields"] == ["component_weight"]
    assert service.market_series_calls[0]["target_currency"] == "USD"


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_uses_explicit_benchmark_without_assignment_or_catalog() -> None:
    service = _StatefulInputServiceStub()

    response = await build_benchmark_exposure_context(
        request=_request(
            benchmark_id="BMK_EXPLICIT",
            grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION],
        ),
        stateful_input_service=service,
    )

    assert response.benchmark_id == "BMK_EXPLICIT"
    assert service.assignment_calls == []
    assert service.index_catalog_calls == []
    assert service.market_series_calls[0]["benchmark_id"] == "BMK_EXPLICIT"


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_paginates_derived_rows() -> None:
    service = _StatefulInputServiceStub()

    response = await build_benchmark_exposure_context(
        request=_request(page={"page_size": 2, "page_token": None}),
        stateful_input_service=service,
    )

    assert len(response.rows) == 2
    assert response.page.next_page_token == "2"


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_bad_upstream_shapes() -> None:
    class _BadMarketSeriesService(_StatefulInputServiceStub):
        async def get_benchmark_market_series(self, **kwargs):  # noqa: ARG002
            return 200, {"component_series": "bad"}

    with pytest.raises(HTTPException, match="component_series list"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_BadMarketSeriesService(),
        )


def test_benchmark_exposure_context_rejects_issuer_until_semantics_exist() -> None:
    with pytest.raises(ValueError, match="does not yet support"):
        _request(grouping_dimensions=[BenchmarkExposureGroupingDimension.ISSUER])
