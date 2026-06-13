from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.benchmark_exposure_context import (
    BenchmarkExposureContextRequest,
    BenchmarkExposureGroupingDimension,
    BenchmarkExposureRow,
    BenchmarkExposureWindow,
)
from app.services.benchmark_exposure_context_service import (
    _accumulate_exposure_point,
    _build_exposure_rows,
    _classification_labels_from_catalog_record,
    _classification_map_from_catalog_records,
    _group_identity,
    _index_ids_for_component_series,
    _page_rows,
    _requires_index_catalog,
    build_benchmark_exposure_context,
)


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
                        "classification_labels": {
                            "sector": "Technology",
                            "asset_class": "Equity",
                            "issuer_id": "ISSUER_TECH",
                            "issuer_name": "Technology Issuer Basket",
                        },
                    },
                    {
                        "index_id": "IDX_TECH_B",
                        "classification_labels": {
                            "sector": "Technology",
                            "asset_class": "Equity",
                            "issuer_id": "ISSUER_TECH",
                            "issuer_name": "Technology Issuer Basket",
                        },
                    },
                    {
                        "index_id": "IDX_BOND",
                        "classification_labels": {
                            "sector": "Government Bonds",
                            "asset_class": "Fixed Income",
                            "issuer_id": "ISSUER_GOVT",
                            "issuer_name": "Government Bond Issuer Basket",
                        },
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
            BenchmarkExposureGroupingDimension.ISSUER,
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
    assert service.index_catalog_calls == [
        {
            "calculation_id": response.calculation_id,
            "as_of_date": date(2026, 1, 3),
            "index_ids": ["IDX_BOND", "IDX_TECH_A", "IDX_TECH_B"],
        }
    ]
    weights = {
        (row.valuation_date.isoformat(), row.grouping_dimension.value, row.group_key): row.weight
        for row in response.rows
    }
    assert weights[("2026-01-02", "SECTOR", "SECTOR_Technology")] == Decimal("0.60")
    assert weights[("2026-01-02", "ASSET_CLASS", "ASSET_CLASS_Equity")] == Decimal("0.60")
    assert weights[("2026-01-02", "ISSUER", "ISSUER_ISSUER_TECH")] == Decimal("0.60")
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


def test_benchmark_exposure_context_accepts_issuer_grouping() -> None:
    request = _request(grouping_dimensions=[BenchmarkExposureGroupingDimension.ISSUER])

    assert request.grouping_dimensions == [BenchmarkExposureGroupingDimension.ISSUER]


def test_benchmark_exposure_context_classification_helpers_normalize_inputs() -> None:
    assert _requires_index_catalog([BenchmarkExposureGroupingDimension.POSITION]) is False
    assert (
        _requires_index_catalog(
            [
                BenchmarkExposureGroupingDimension.POSITION,
                BenchmarkExposureGroupingDimension.SECTOR,
            ]
        )
        is True
    )

    assert _index_ids_for_component_series(
        [
            {"index_id": "IDX_B"},
            {"index_id": ""},
            {"index_id": None},
            {"index_id": "IDX_A"},
            {"index_id": "IDX_B"},
        ]
    ) == ["IDX_A", "IDX_B"]

    assert _classification_map_from_catalog_records(
        [
            None,
            {"index_id": "", "classification_labels": {"sector": "Preserved"}},
            {"index_id": "IDX_A", "classification_labels": "bad"},
            {
                "index_id": "IDX_B",
                "classification_labels": {
                    "sector": "Technology",
                    "asset_class": None,
                    "issuer_id": 123,
                },
            },
        ]
    ) == {"": {"sector": "Preserved"}, "IDX_B": {"sector": "Technology", "issuer_id": "123"}}
    assert _classification_labels_from_catalog_record(None) is None
    assert _classification_labels_from_catalog_record({"classification_labels": {"sector": "Technology"}}) is None
    assert _classification_labels_from_catalog_record({"index_id": "IDX_A", "classification_labels": "bad"}) is None
    assert _classification_labels_from_catalog_record(
        {"index_id": "IDX_B", "classification_labels": {"sector": "Technology", "rank": 1, "ignored": None}}
    ) == ("IDX_B", {"sector": "Technology", "rank": "1"})


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_missing_assignment() -> None:
    class _NoAssignmentService(_StatefulInputServiceStub):
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 404, {}

    with pytest.raises(HTTPException, match="requires a benchmark assignment"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_NoAssignmentService(),
        )


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_assignment_source_failure() -> None:
    class _AssignmentSourceFailureService(_StatefulInputServiceStub):
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 503, {}

    with pytest.raises(HTTPException, match="assignment source unavailable"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_AssignmentSourceFailureService(),
        )


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_assignment_payload_without_benchmark_id() -> None:
    class _MissingAssignmentBenchmarkService(_StatefulInputServiceStub):
        async def get_benchmark_assignment(self, **kwargs):  # noqa: ARG002
            return 200, {"benchmark_id": ""}

    with pytest.raises(HTTPException, match="payload missing benchmark_id"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_MissingAssignmentBenchmarkService(),
        )


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_catalog_source_failure() -> None:
    class _CatalogSourceFailureService(_StatefulInputServiceStub):
        async def get_index_catalog(self, **kwargs):  # noqa: ARG002
            return 503, {}

    with pytest.raises(HTTPException, match="index catalog source unavailable"):
        await build_benchmark_exposure_context(
            request=_request(), stateful_input_service=_CatalogSourceFailureService()
        )


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_catalog_without_records_list() -> None:
    class _CatalogShapeFailureService(_StatefulInputServiceStub):
        async def get_index_catalog(self, **kwargs):  # noqa: ARG002
            return 200, {"records": "bad"}

    with pytest.raises(HTTPException, match="records list"):
        await build_benchmark_exposure_context(request=_request(), stateful_input_service=_CatalogShapeFailureService())


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_maps_market_series_404_to_not_found() -> None:
    class _MissingMarketSeriesService(_StatefulInputServiceStub):
        async def get_benchmark_market_series(self, **kwargs):  # noqa: ARG002
            return 404, {}

    with pytest.raises(HTTPException, match="No benchmark market-series found"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_MissingMarketSeriesService(),
        )


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_maps_market_series_source_failure() -> None:
    class _MarketSeriesSourceFailureService(_StatefulInputServiceStub):
        async def get_benchmark_market_series(self, **kwargs):  # noqa: ARG002
            return 503, {}

    with pytest.raises(HTTPException, match="market-series source unavailable"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_MarketSeriesSourceFailureService(),
        )


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_rejects_empty_usable_rows() -> None:
    class _NoUsableRowsService(_StatefulInputServiceStub):
        async def get_benchmark_market_series(self, **kwargs):  # noqa: ARG002
            return 200, {"component_series": [{"index_id": "", "points": "bad"}]}

    with pytest.raises(HTTPException, match="No usable benchmark exposure rows returned"):
        await build_benchmark_exposure_context(
            request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
            stateful_input_service=_NoUsableRowsService(),
        )


def test_build_exposure_rows_skips_invalid_component_shapes_and_rejects_invalid_weights() -> None:
    rows = _build_exposure_rows(
        component_series=[
            {"index_id": "", "points": [{"series_date": "2026-01-02", "component_weight": "0.10"}]},
            {"index_id": "IDX", "points": "bad"},
            {
                "index_id": "IDX",
                "points": [None, {"series_date": None, "component_weight": "0.10"}, {"series_date": "2026-01-02"}],
            },
            {"index_id": "IDX", "points": [{"series_date": "2026-01-02", "component_weight": "0.10"}]},
        ],
        grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION],
        classification_map={},
    )

    assert len(rows) == 1
    assert rows[0].group_key == "IDX"
    assert rows[0].weight == Decimal("0.10")

    with pytest.raises(HTTPException, match="invalid component_weight"):
        _build_exposure_rows(
            component_series=[
                {"index_id": "IDX", "points": [{"series_date": "2026-01-02", "component_weight": "not-a-number"}]}
            ],
            grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION],
            classification_map={},
        )


def test_accumulate_exposure_point_groups_valid_points_and_skips_invalid_shapes() -> None:
    grouped_weights: dict[tuple[str, BenchmarkExposureGroupingDimension, str], Decimal] = {}
    labels: dict[tuple[BenchmarkExposureGroupingDimension, str], str] = {}
    component_ids: dict[tuple[BenchmarkExposureGroupingDimension, str], str | None] = {}

    _accumulate_exposure_point(
        index_id="IDX",
        point=None,
        grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION],
        classification_map={},
        grouped_weights=grouped_weights,
        labels=labels,
        component_ids=component_ids,
    )
    _accumulate_exposure_point(
        index_id="IDX",
        point={"series_date": "2026-01-02", "component_weight": "0.25"},
        grouping_dimensions=[
            BenchmarkExposureGroupingDimension.POSITION,
            BenchmarkExposureGroupingDimension.SECTOR,
        ],
        classification_map={"IDX": {"sector": "Technology"}},
        grouped_weights=grouped_weights,
        labels=labels,
        component_ids=component_ids,
    )

    assert grouped_weights[("2026-01-02", BenchmarkExposureGroupingDimension.POSITION, "IDX")] == Decimal("0.25")
    assert grouped_weights[("2026-01-02", BenchmarkExposureGroupingDimension.SECTOR, "SECTOR_Technology")] == Decimal(
        "0.25"
    )
    assert labels[(BenchmarkExposureGroupingDimension.SECTOR, "SECTOR_Technology")] == "Technology"
    assert component_ids[(BenchmarkExposureGroupingDimension.POSITION, "IDX")] == "IDX"


def test_group_identity_uses_unknown_defaults_for_classification_groups() -> None:
    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.SECTOR,
        classification_map={},
    ) == ("SECTOR_UNKNOWN", "UNKNOWN", None)
    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.ASSET_CLASS,
        classification_map={},
    ) == ("ASSET_CLASS_UNKNOWN", "UNKNOWN", None)

    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.ISSUER,
        classification_map={},
    ) == ("ISSUER_UNKNOWN", "UNKNOWN", None)

    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.ISSUER,
        classification_map={"IDX": {"issuer_id": "ISSUER_A", "issuer_name": "Issuer A"}},
    ) == ("ISSUER_ISSUER_A", "Issuer A", None)


def test_group_identity_projects_position_and_classification_labels() -> None:
    classification_map = {"IDX": {"sector": "Technology", "asset_class": "Equity"}}

    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.POSITION,
        classification_map=classification_map,
    ) == ("IDX", "IDX", "IDX")
    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.SECTOR,
        classification_map=classification_map,
    ) == ("SECTOR_Technology", "Technology", None)
    assert _group_identity(
        index_id="IDX",
        grouping_dimension=BenchmarkExposureGroupingDimension.ASSET_CLASS,
        classification_map=classification_map,
    ) == ("ASSET_CLASS_Equity", "Equity", None)


def test_page_rows_rejects_invalid_page_token_inputs() -> None:
    rows = [
        BenchmarkExposureRow(
            valuation_date=date(2026, 1, 2),
            component_id="IDX_A",
            grouping_dimension=BenchmarkExposureGroupingDimension.POSITION,
            group_key="IDX_A",
            group_label="IDX_A",
            weight=Decimal("0.10"),
        )
    ]

    with pytest.raises(HTTPException, match="numeric offset token"):
        _page_rows(rows=rows, page_size=10, page_token="bad")

    with pytest.raises(HTTPException, match="must be non-negative"):
        _page_rows(rows=rows, page_size=10, page_token="-1")


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_ignores_non_dict_catalog_records() -> None:
    class _NoisyCatalogService(_StatefulInputServiceStub):
        async def get_index_catalog(self, **kwargs):  # noqa: ARG002
            return 200, {
                "records": [None, {"index_id": "IDX_TECH_A", "classification_labels": {"sector": "Technology"}}]
            }

    response = await build_benchmark_exposure_context(
        request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.SECTOR]),
        stateful_input_service=_NoisyCatalogService(),
    )

    assert any(row.group_key == "SECTOR_Technology" for row in response.rows)


@pytest.mark.asyncio
async def test_build_benchmark_exposure_context_skips_catalog_for_position_only_grouping() -> None:
    service = _StatefulInputServiceStub()

    response = await build_benchmark_exposure_context(
        request=_request(grouping_dimensions=[BenchmarkExposureGroupingDimension.POSITION]),
        stateful_input_service=service,
    )

    assert response.rows
    assert service.index_catalog_calls == []
