from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest

from app.services.execution_registry import ExecutionRegistry
from app.services.stateful_input_service import (
    DateChunk,
    StatefulInputService,
    _component_index_points,
    _portfolio_identity_from_payload,
    _portfolio_observations_from_payload,
    _portfolio_timeseries_request_payload,
    _position_rows_from_payload,
    _position_timeseries_request_payload,
)


class _CoreServiceStub:
    def __init__(self) -> None:
        self.portfolio_calls: list[dict] = []
        self.position_calls: list[dict] = []
        self.benchmark_calls: list[dict] = []
        self.benchmark_market_calls: list[dict] = []
        self.fx_calls: list[dict] = []
        self.index_price_calls: list[dict] = []
        self.risk_free_calls: list[dict] = []

    async def get_portfolio_analytics_timeseries(self, **kwargs):
        self.portfolio_calls.append(kwargs)
        page_token = kwargs.get("page_token")
        start_date = kwargs["start_date"]
        if start_date == date(2026, 1, 1) and page_token is None:
            return (
                200,
                {
                    "portfolio_open_date": "2025-12-31",
                    "portfolio_currency": "EUR",
                    "reporting_currency": "USD",
                    "observations": [
                        {
                            "valuation_date": "2026-01-01",
                            "beginning_market_value": "100",
                            "ending_market_value": "101",
                        }
                    ],
                    "page": {"next_page_token": "page-2"},
                },
            )
        if start_date == date(2026, 1, 1) and page_token == "page-2":
            return (
                200,
                {
                    "portfolio_open_date": "2025-12-31",
                    "portfolio_currency": "EUR",
                    "reporting_currency": "USD",
                    "observations": [
                        {
                            "valuation_date": "2026-01-02",
                            "beginning_market_value": "101",
                            "ending_market_value": "102",
                        }
                    ],
                },
            )
        return (
            200,
            {
                "portfolio_open_date": "2025-12-31",
                "portfolio_currency": "EUR",
                "reporting_currency": "USD",
                "observations": [
                    {
                        "valuation_date": "2026-01-03",
                        "beginning_market_value": "102",
                        "ending_market_value": "103",
                    },
                    {
                        "valuation_date": "2026-01-03",
                        "beginning_market_value": "102",
                        "ending_market_value": "103",
                    },
                ],
            },
        )

    async def get_benchmark_assignment(self, **kwargs):
        return 200, {"benchmark_id": "BMK_1"}

    async def get_position_analytics_timeseries(self, **kwargs):
        self.position_calls.append(kwargs)
        page_token = kwargs.get("page_token")
        start_date = kwargs["start_date"]
        if start_date == date(2026, 1, 1) and page_token is None:
            return (
                200,
                {
                    "rows": [
                        {
                            "valuation_date": "2026-01-01",
                            "position_id": "SEC_1",
                            "beginning_market_value_portfolio_currency": "100",
                            "ending_market_value_portfolio_currency": "101",
                        }
                    ],
                    "page": {"next_page_token": "page-2"},
                },
            )
        if start_date == date(2026, 1, 1) and page_token == "page-2":
            return (
                200,
                {
                    "rows": [
                        {
                            "valuation_date": "2026-01-02",
                            "position_id": "SEC_1",
                            "beginning_market_value_portfolio_currency": "101",
                            "ending_market_value_portfolio_currency": "102",
                        }
                    ],
                },
            )
        return (
            200,
            {
                "rows": [
                    {
                        "valuation_date": "2026-01-03",
                        "position_id": "SEC_1",
                        "beginning_market_value_portfolio_currency": "102",
                        "ending_market_value_portfolio_currency": "103",
                    },
                    {
                        "valuation_date": "2026-01-03",
                        "position_id": "SEC_1",
                        "beginning_market_value_portfolio_currency": "102",
                        "ending_market_value_portfolio_currency": "103",
                    },
                ]
            },
        )

    async def get_benchmark_return_series(self, **kwargs):
        self.benchmark_calls.append(kwargs)
        return (
            200,
            {
                "points": [
                    {"series_date": str(kwargs["start_date"]), "benchmark_return": "0.0010"},
                    {"series_date": str(kwargs["end_date"]), "benchmark_return": "0.0020"},
                ]
            },
        )

    async def get_benchmark_definition(self, **kwargs):
        return 200, {"benchmark_id": kwargs["benchmark_id"]}

    async def get_benchmark_composition_window(self, **kwargs):
        return (
            200,
            {
                "benchmark_id": kwargs["benchmark_id"],
                "benchmark_currency": "USD",
                "segments": [
                    {
                        "index_id": "IDX_1",
                        "composition_weight": "1.0",
                        "composition_effective_from": str(kwargs["start_date"]),
                        "composition_effective_to": str(kwargs["end_date"]),
                    }
                ],
            },
        )

    async def get_benchmark_market_series(self, **kwargs):
        self.benchmark_market_calls.append(kwargs)
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        return (
            200,
            {
                "component_series": [
                    {
                        "index_id": "IDX_1",
                        "points": [
                            {"series_date": str(start_date), "index_return": "0.0010"},
                            {"series_date": str(end_date), "index_return": "0.0020"},
                        ],
                    },
                    {
                        "index_id": "IDX_2",
                        "points": [
                            {"series_date": str(start_date), "index_return": "0.0030"},
                            {"series_date": str(end_date), "index_return": "0.0040"},
                        ],
                    },
                ]
            },
        )

    async def get_fx_rates(self, **kwargs):
        self.fx_calls.append(kwargs)
        return (
            200,
            {
                "rates": [
                    {"rate_date": str(kwargs["start_date"]), "rate": "1.1000"},
                    {"rate_date": str(kwargs["end_date"]), "rate": "1.2000"},
                ]
            },
        )

    async def get_portfolio_analytics_reference(self, **kwargs):
        return (
            200,
            {
                "portfolio_id": kwargs["portfolio_id"],
                "portfolio_open_date": "2025-12-31",
                "base_currency": "USD",
            },
        )

    async def get_index_catalog(self, **kwargs):
        return (
            200,
            {
                "indices": [
                    {"index_id": "IDX_1", "currency": "USD"},
                    {"index_id": "IDX_2", "currency": "EUR"},
                ],
                "as_of_date": str(kwargs["as_of_date"]),
            },
        )

    async def get_index_price_series(self, **kwargs):
        self.index_price_calls.append(kwargs)
        return (
            200,
            {
                "points": [
                    {"series_date": str(kwargs["start_date"]), "index_price": "100", "series_currency": "USD"},
                    {"series_date": str(kwargs["end_date"]), "index_price": "101", "series_currency": "USD"},
                ]
            },
        )

    async def get_risk_free_series(self, **kwargs):
        self.risk_free_calls.append(kwargs)
        return (
            200,
            {
                "points": [
                    {"series_date": str(kwargs["start_date"]), "value": "0.0001"},
                    {"series_date": str(kwargs["end_date"]), "value": "0.0002"},
                ]
            },
        )


def test_plan_chunks_splits_window_deterministically():
    service = StatefulInputService(core_service=_CoreServiceStub(), portfolio_chunk_days=3)
    chunks = service.plan_chunks(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        chunk_days=3,
    )
    assert [(chunk.start_date, chunk.end_date) for chunk in chunks] == [
        (date(2026, 1, 1), date(2026, 1, 3)),
        (date(2026, 1, 4), date(2026, 1, 6)),
        (date(2026, 1, 7), date(2026, 1, 7)),
    ]


def test_total_retrieval_page_count_defaults_missing_metadata_and_coerces_numeric_counts():
    service = StatefulInputService(core_service=_CoreServiceStub())

    assert (
        service._total_retrieval_page_count(
            [
                (200, {"retrieval_metadata": {"page_count": "2"}}),
                (200, {"retrieval_metadata": {"page_count": 3.0}}),
                (200, {"retrieval_metadata": None}),
                (200, {}),
            ]
        )
        == 5
    )


def test_portfolio_chunk_helper_contracts_preserve_request_identity_and_payload_filtering():
    request_payload = _portfolio_timeseries_request_payload(
        portfolio_id="PORT_1",
        chunk=DateChunk(start_date=date(2026, 1, 1), end_date=date(2026, 1, 3)),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        page_token="page-2",
    )
    portfolio_open_date, portfolio_currency, reporting_currency = _portfolio_identity_from_payload(
        payload={
            "portfolio_open_date": "2025-12-31",
            "portfolio_currency": "EUR",
            "reporting_currency": "USD",
        },
        portfolio_open_date=None,
        portfolio_currency=None,
        reporting_currency=None,
    )
    preserved_identity = _portfolio_identity_from_payload(
        payload={
            "portfolio_open_date": "2024-01-01",
            "portfolio_currency": "GBP",
            "reporting_currency": "CHF",
        },
        portfolio_open_date=portfolio_open_date,
        portfolio_currency=portfolio_currency,
        reporting_currency=reporting_currency,
    )
    ignored_non_string_identity = _portfolio_identity_from_payload(
        payload={
            "portfolio_open_date": date(2025, 12, 31),
            "portfolio_currency": 123,
            "reporting_currency": None,
        },
        portfolio_open_date=None,
        portfolio_currency=None,
        reporting_currency=None,
    )

    assert request_payload == {
        "portfolio_id": "PORT_1",
        "start_date": "2026-01-01",
        "end_date": "2026-01-03",
        "reporting_currency": "USD",
        "consumer_system": "lotus-performance",
        "page_token": "page-2",
    }
    assert (portfolio_open_date, portfolio_currency, reporting_currency) == ("2025-12-31", "EUR", "USD")
    assert preserved_identity == ("2025-12-31", "EUR", "USD")
    assert ignored_non_string_identity == (None, None, None)
    assert _portfolio_observations_from_payload({"observations": [{"valuation_date": "2026-01-01"}, "bad"]}) == [
        {"valuation_date": "2026-01-01"}
    ]
    assert _portfolio_observations_from_payload({"observations": "bad"}) == []


def test_build_portfolio_timeseries_payload_normalizes_chunk_responses():
    service = StatefulInputService(core_service=_CoreServiceStub())

    payload = service._build_portfolio_timeseries_payload(
        responses=[
            (
                200,
                {
                    "portfolio_open_date": "2025-12-31",
                    "portfolio_currency": "EUR",
                    "reporting_currency": "USD",
                    "observations": [
                        {"valuation_date": "2026-01-02", "ending_market_value": "102"},
                        {"valuation_date": "2026-01-01", "ending_market_value": "101"},
                    ],
                    "retrieval_metadata": {"page_count": "2"},
                },
            ),
            (
                200,
                {
                    "portfolio_open_date": "2024-01-01",
                    "portfolio_currency": "GBP",
                    "reporting_currency": "USD",
                    "observations": [
                        {"valuation_date": "2026-01-02", "ending_market_value": "replacement"},
                        "bad-row",
                    ],
                    "retrieval_metadata": {"page_count": 1},
                },
            ),
            (200, {"observations": "bad-shape", "retrieval_metadata": None}),
        ],
        chunk_count=3,
    )

    assert payload == {
        "portfolio_open_date": "2024-01-01",
        "portfolio_currency": None,
        "reporting_currency": "USD",
        "observations": [
            {"valuation_date": "2026-01-01", "ending_market_value": "101"},
            {"valuation_date": "2026-01-02", "ending_market_value": "replacement"},
        ],
        "retrieval_metadata": {"chunk_count": 3, "page_count": 3},
    }


@pytest.mark.asyncio
async def test_get_portfolio_timeseries_merges_chunked_and_paginated_observations():
    core_service = _CoreServiceStub()
    service = StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=2,
        reference_chunk_days=10,
        max_concurrent_chunks=2,
    )

    status_code, payload = await service.get_portfolio_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
    )

    assert status_code == 200
    assert payload["portfolio_open_date"] == "2025-12-31"
    assert payload["portfolio_currency"] == "EUR"
    assert payload["reporting_currency"] == "USD"
    assert [item["valuation_date"] for item in payload["observations"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 3}
    assert len(core_service.portfolio_calls) == 3


@pytest.mark.asyncio
async def test_reference_series_merge_chunked_points():
    core_service = _CoreServiceStub()
    service = StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=10,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    benchmark_status, benchmark_payload = await service.get_benchmark_return_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )
    risk_free_status, risk_free_payload = await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )

    assert benchmark_status == 200
    assert risk_free_status == 200
    assert [point["series_date"] for point in benchmark_payload["points"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
    ]
    assert benchmark_payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 2}
    assert [point["series_date"] for point in risk_free_payload["points"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
    ]
    assert risk_free_payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 2}


@pytest.mark.asyncio
async def test_stateful_input_service_records_risk_free_snapshots_once_per_chunk(tmp_path):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BenchmarkAnalytics",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        reference_chunk_days=2,
    )

    status_code, payload = await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    assert status_code == 200
    assert payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 2}
    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    risk_free_snapshots = [snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "risk_free_series"]
    assert len(risk_free_snapshots) == 2
    assert {snapshot.source_identifier for snapshot in risk_free_snapshots} == {"USD"}
    assert len(core_service.risk_free_calls) == 4


@pytest.mark.asyncio
async def test_stateful_input_service_fetches_reference_payloads_and_records_snapshots(tmp_path):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BenchmarkAnalytics",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        portfolio_chunk_days=10,
        reference_chunk_days=10,
    )

    portfolio_status, portfolio_payload = await service.get_portfolio_reference(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        calculation_id=calculation_id,
    )
    definition_status, definition_payload = await service.get_benchmark_definition(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 3),
        calculation_id=calculation_id,
    )
    composition_status, composition_payload = await service.get_benchmark_composition_window(
        benchmark_id="BMK_1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        calculation_id=calculation_id,
    )
    catalog_status, catalog_payload = await service.get_index_catalog(
        as_of_date=date(2026, 1, 3),
        index_ids=["IDX_2", "IDX_1"],
        calculation_id=calculation_id,
    )

    assert portfolio_status == 200
    assert definition_status == 200
    assert composition_status == 200
    assert catalog_status == 200
    assert portfolio_payload["base_currency"] == "USD"
    assert definition_payload["benchmark_id"] == "BMK_1"
    assert composition_payload["benchmark_currency"] == "USD"
    assert catalog_payload["indices"][1]["index_id"] == "IDX_2"

    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    assert {snapshot.upstream_endpoint for snapshot in snapshots} >= {
        "portfolio_reference",
        "benchmark_definition",
        "benchmark_composition_window",
        "index_catalog",
    }
    index_catalog_snapshots = [snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "index_catalog"]
    assert len(index_catalog_snapshots) == 1
    assert index_catalog_snapshots[0].source_identifier == "IDX_1|IDX_2"
    assert index_catalog_snapshots[0].paging_metadata["index_ids"] == ["IDX_1", "IDX_2"]


@pytest.mark.asyncio
async def test_stateful_input_service_merges_chunked_market_series_and_fx_rates():
    core_service = _CoreServiceStub()
    service = StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=10,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    market_status, market_payload = await service.get_benchmark_market_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        target_currency="USD",
        series_fields=["index_return"],
    )
    fx_status, fx_payload = await service.get_fx_rates(
        from_currency="EUR",
        to_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )

    assert market_status == 200
    assert fx_status == 200
    assert market_payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 2}
    assert fx_payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 2}
    assert market_payload["component_series"] == [
        {
            "index_id": "IDX_1",
            "points": [
                {"series_date": "2026-01-01", "index_return": "0.0010"},
                {"series_date": "2026-01-02", "index_return": "0.0020"},
                {"series_date": "2026-01-03", "index_return": "0.0010"},
                {"series_date": "2026-01-04", "index_return": "0.0020"},
            ],
        },
        {
            "index_id": "IDX_2",
            "points": [
                {"series_date": "2026-01-01", "index_return": "0.0030"},
                {"series_date": "2026-01-02", "index_return": "0.0040"},
                {"series_date": "2026-01-03", "index_return": "0.0030"},
                {"series_date": "2026-01-04", "index_return": "0.0040"},
            ],
        },
    ]
    assert fx_payload["points"] == [
        {"series_date": "2026-01-01", "fx_rate": "1.1000"},
        {"series_date": "2026-01-02", "fx_rate": "1.2000"},
        {"series_date": "2026-01-03", "fx_rate": "1.1000"},
        {"series_date": "2026-01-04", "fx_rate": "1.2000"},
    ]
    assert len(core_service.benchmark_market_calls) == 2
    assert len(core_service.fx_calls) == 2


@pytest.mark.asyncio
async def test_stateful_input_service_merges_chunked_index_price_series_and_skips_duplicate_snapshots(tmp_path):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BenchmarkAnalytics",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        reference_chunk_days=2,
    )

    status_code, payload = await service.get_index_price_series(
        index_id="IDX_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_index_price_series(
        index_id="IDX_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    assert status_code == 200
    assert payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 2}
    assert payload["points"] == [
        {"series_date": "2026-01-01", "index_price": "100", "series_currency": "USD"},
        {"series_date": "2026-01-02", "index_price": "101", "series_currency": "USD"},
        {"series_date": "2026-01-03", "index_price": "100", "series_currency": "USD"},
        {"series_date": "2026-01-04", "index_price": "101", "series_currency": "USD"},
    ]
    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    index_snapshots = [snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "index_price_series"]
    assert len(index_snapshots) == 2
    assert {snapshot.source_identifier for snapshot in index_snapshots} == {"IDX_1"}
    assert len(core_service.index_price_calls) == 4


@pytest.mark.asyncio
async def test_stateful_input_service_returns_first_failure_for_reference_chunks():
    class _FailingReferenceCoreService(_CoreServiceStub):
        async def get_benchmark_market_series(self, **kwargs):
            if kwargs["start_date"] == date(2026, 1, 3):
                return 503, {"detail": "reference unavailable"}
            return await super().get_benchmark_market_series(**kwargs)

        async def get_index_price_series(self, **kwargs):
            return 404, {"detail": "missing index"}

    service = StatefulInputService(
        core_service=_FailingReferenceCoreService(),
        reference_chunk_days=2,
    )

    market_status, market_payload = await service.get_benchmark_market_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )
    index_status, index_payload = await service.get_index_price_series(
        index_id="IDX_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
    )

    assert market_status == 503
    assert market_payload == {"detail": "reference unavailable"}
    assert index_status == 404
    assert index_payload == {"detail": "missing index"}


@pytest.mark.asyncio
async def test_stateful_input_service_records_reference_snapshots_even_when_chunked_request_fails(tmp_path):
    class _FailingReferenceCoreService(_CoreServiceStub):
        async def get_benchmark_market_series(self, **kwargs):
            if kwargs["start_date"] == date(2026, 1, 3):
                return 503, {"detail": "reference unavailable"}
            return await super().get_benchmark_market_series(**kwargs)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BenchmarkAnalytics",
        portfolio_id="BMK_1",
    )
    service = StatefulInputService(
        core_service=_FailingReferenceCoreService(),
        execution_store=execution_store,
        reference_chunk_days=2,
    )

    status_code, payload = await service.get_benchmark_market_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_benchmark_market_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    assert status_code == 503
    assert payload == {"detail": "reference unavailable"}
    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    assert len([snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "benchmark_market_series"]) == 2


@pytest.mark.asyncio
async def test_stateful_input_service_records_fx_snapshots_even_when_chunked_request_fails(tmp_path):
    class _FailingFxCoreService(_CoreServiceStub):
        async def get_fx_rates(self, **kwargs):
            if kwargs["start_date"] == date(2026, 1, 3):
                return 503, {"detail": "fx unavailable"}
            return await super().get_fx_rates(**kwargs)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BenchmarkAnalytics",
        portfolio_id="BMK_1",
    )
    service = StatefulInputService(
        core_service=_FailingFxCoreService(),
        execution_store=execution_store,
        reference_chunk_days=2,
    )

    status_code, payload = await service.get_fx_rates(
        from_currency="EUR",
        to_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_fx_rates(
        from_currency="EUR",
        to_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    assert status_code == 503
    assert payload == {"detail": "fx unavailable"}
    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    assert len([snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "fx_rates"]) == 2


@pytest.mark.asyncio
async def test_stateful_input_service_records_upstream_snapshots(tmp_path):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        portfolio_chunk_days=2,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    await service.get_portfolio_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        calculation_id=calculation_id,
    )
    await service.get_benchmark_return_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_benchmark_return_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    benchmark_snapshots = [
        snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "benchmark_return_series"
    ]

    assert len(snapshots) >= 5
    assert len(benchmark_snapshots) == 2
    assert {snapshot.upstream_endpoint for snapshot in snapshots} >= {
        "portfolio_timeseries",
        "benchmark_return_series",
    }


@pytest.mark.asyncio
async def test_stateful_input_service_records_position_upstream_snapshots(tmp_path):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        portfolio_chunk_days=2,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    await service.get_position_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["sector"],
        calculation_id=calculation_id,
    )

    snapshots = execution_store.list_upstream_snapshots(calculation_id)

    assert len(snapshots) >= 3
    assert {snapshot.upstream_endpoint for snapshot in snapshots} >= {"position_timeseries"}


@pytest.mark.asyncio
async def test_get_position_timeseries_reports_chunk_and_page_counts():
    core_service = _CoreServiceStub()
    service = StatefulInputService(
        core_service=core_service,
        portfolio_chunk_days=2,
        reference_chunk_days=10,
        max_concurrent_chunks=2,
    )

    status_code, payload = await service.get_position_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
    )

    assert status_code == 200
    assert [item["valuation_date"] for item in payload["rows"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert payload["retrieval_metadata"] == {"chunk_count": 2, "page_count": 3}


@pytest.mark.asyncio
async def test_stateful_input_service_skips_duplicate_snapshot_builds_for_existing_calculation(tmp_path, mocker):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="ReturnsSeries",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        portfolio_chunk_days=2,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    await service.get_portfolio_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        calculation_id=calculation_id,
    )

    snapshot_builder = mocker.patch.object(service, "_build_snapshot", wraps=service._build_snapshot)

    await service.get_portfolio_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        calculation_id=calculation_id,
    )

    assert snapshot_builder.call_count == 0


@pytest.mark.asyncio
async def test_stateful_input_service_skips_duplicate_reference_snapshot_builds_for_market_and_fx(tmp_path, mocker):
    core_service = _CoreServiceStub()
    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="BenchmarkAnalytics",
        portfolio_id="BMK_1",
    )
    service = StatefulInputService(
        core_service=core_service,
        execution_store=execution_store,
        reference_chunk_days=2,
        max_concurrent_chunks=2,
    )

    await service.get_benchmark_market_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_fx_rates(
        from_currency="EUR",
        to_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    service._snapshot_id_cache[calculation_id] = execution_store.list_upstream_snapshot_ids(calculation_id)

    snapshot_builder = mocker.patch.object(service, "_build_snapshot", wraps=service._build_snapshot)

    await service.get_benchmark_market_series(
        benchmark_id="BMK_1",
        as_of_date=date(2026, 1, 4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )
    await service.get_fx_rates(
        from_currency="EUR",
        to_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        calculation_id=calculation_id,
    )

    assert snapshot_builder.call_count == 0


@pytest.mark.asyncio
async def test_stateful_input_service_records_position_snapshots_before_chunk_failure(tmp_path):
    class _FailingPositionCoreService(_CoreServiceStub):
        async def get_position_analytics_timeseries(self, **kwargs):
            if kwargs["start_date"] == date(2026, 1, 3):
                return 503, {"detail": "position unavailable"}
            return await super().get_position_analytics_timeseries(**kwargs)

    execution_store = ExecutionRegistry(f"sqlite:///{tmp_path / 'execution.db'}")
    execution_store.create_schema()
    calculation_id = uuid4()
    execution_store.create_execution(
        calculation_id=calculation_id,
        analytics_type="Contribution",
        portfolio_id="PORT_1",
    )
    service = StatefulInputService(
        core_service=_FailingPositionCoreService(),
        execution_store=execution_store,
        portfolio_chunk_days=2,
    )

    status_code, payload = await service.get_position_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        calculation_id=calculation_id,
    )

    assert status_code == 503
    assert payload == {"detail": "position unavailable"}
    snapshots = execution_store.list_upstream_snapshots(calculation_id)
    position_snapshots = [snapshot for snapshot in snapshots if snapshot.upstream_endpoint == "position_timeseries"]
    assert len(position_snapshots) == 3
    assert {snapshot.source_identifier for snapshot in position_snapshots} == {"PORT_1"}


@pytest.mark.asyncio
async def test_stateful_input_service_returns_first_failure_for_position_chunks():
    class _FailingCoreService(_CoreServiceStub):
        async def get_position_analytics_timeseries(self, **kwargs):
            return 503, {"detail": "unavailable"}

    service = StatefulInputService(core_service=_FailingCoreService())

    status_code, payload = await service.get_position_timeseries(
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        reporting_currency="USD",
        consumer_system="lotus-performance",
    )

    assert status_code == 503
    assert payload == {"detail": "unavailable"}


def test_stateful_input_service_deduplicates_records_and_component_series():
    service = StatefulInputService(core_service=_CoreServiceStub())

    deduped = service._merge_dedup_records_by_fields(
        records=[
            {"valuation_date": "2026-01-01", "position_id": "POS_1", "value": 1},
            {"valuation_date": "2026-01-01", "position_id": "POS_1", "value": 2},
            {"valuation_date": "2026-01-02", "position_id": 7},
        ],
        key_fields=("valuation_date", "position_id"),
    )
    merged_series = service._merge_component_series(
        payloads=[
            {"component_series": [{"index_id": "IDX_1", "points": [{"series_date": "2026-01-01"}]}]},
            {"component_series": [{"index_id": None}, "bad", {"index_id": "IDX_1", "points": "bad"}]},
        ]
    )
    component_points = service._component_points_by_index(
        [
            {"component_series": [{"index_id": "IDX_2", "points": [{"series_date": "2026-01-02"}, None]}]},
            {"component_series": "bad"},
            {"component_series": [{"index_id": None, "points": [{"series_date": "ignored"}]}, "bad"]},
        ]
    )

    assert deduped == [{"valuation_date": "2026-01-01", "position_id": "POS_1", "value": 2}]
    assert merged_series == [{"index_id": "IDX_1", "points": [{"series_date": "2026-01-01"}]}]
    assert component_points == {"IDX_2": [{"series_date": "2026-01-02"}]}
    assert _component_index_points({"index_id": "IDX_3", "points": [{"series_date": "2026-01-03"}, None]}) == (
        "IDX_3",
        [{"series_date": "2026-01-03"}],
    )
    assert _component_index_points({"index_id": "IDX_4", "points": "bad-shape"}) == ("IDX_4", [])
    assert _component_index_points({"index_id": None}) is None
    assert _component_index_points("bad-component") is None


def test_stateful_input_service_builds_position_timeseries_payload():
    service = StatefulInputService(core_service=_CoreServiceStub())

    payload = service._build_position_timeseries_payload(
        responses=[
            (
                200,
                {
                    "rows": [
                        {"valuation_date": "2026-01-01", "position_id": "POS_1", "value": 1},
                        "ignored",
                    ],
                    "retrieval_metadata": {"page_count": 1},
                },
            ),
            (
                200,
                {
                    "rows": [
                        {"valuation_date": "2026-01-01", "position_id": "POS_1", "value": 2},
                        {"valuation_date": "2026-01-02", "position_id": "POS_2", "value": 3},
                        {"valuation_date": "2026-01-03", "position_id": None, "value": 4},
                    ],
                    "retrieval_metadata": {"page_count": 2},
                },
            ),
        ],
        chunk_count=2,
    )

    assert payload == {
        "rows": [
            {"valuation_date": "2026-01-01", "position_id": "POS_1", "value": 2},
            {"valuation_date": "2026-01-02", "position_id": "POS_2", "value": 3},
        ],
        "retrieval_metadata": {"chunk_count": 2, "page_count": 3},
    }


def test_stateful_input_service_helper_contracts_cover_page_tokens_failures_and_snapshot_identity():
    service = StatefulInputService(core_service=_CoreServiceStub())
    calculation_id = UUID("00000000-0000-0000-0000-000000000001")
    chunk = DateChunk(start_date=date(2026, 1, 1), end_date=date(2026, 1, 3))

    assert service._first_failure([(200, {}), (201, {"ok": True})]) is None
    assert service._next_page_token({"next_page_token": "top-level-token"}) == "top-level-token"
    assert service._next_page_token({"page": {"next_page_token": "nested-token"}}) == "nested-token"
    assert service._next_page_token({"next_page_token": ""}) is None
    assert service._merge_dedup_records(
        records=[
            {"series_date": "2026-01-02", "value": 2},
            {"series_date": "2026-01-01", "value": 1},
            {"series_date": 3, "value": 3},
        ],
        date_key="series_date",
    ) == [
        {"series_date": "2026-01-01", "value": 1},
        {"series_date": "2026-01-02", "value": 2},
    ]
    assert service._merge_dedup_points_from_responses(
        [
            (200, {"points": [{"series_date": "2026-01-02", "value": 2}, "ignored"]}),
            (200, {"points": [{"series_date": "2026-01-01", "value": 1}]}),
            (200, {"rows": [{"series_date": "2026-01-03", "value": 3}]}),
        ]
    ) == [
        {"series_date": "2026-01-01", "value": 1},
        {"series_date": "2026-01-02", "value": 2},
    ]
    assert _position_timeseries_request_payload(
        portfolio_id="PORT_1",
        chunk=chunk,
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["asset_class", "region"],
        include_cash_flows=True,
        filters={"asset_class": "Equity"},
        page_token="page-2",
    ) == {
        "portfolio_id": "PORT_1",
        "start_date": "2026-01-01",
        "end_date": "2026-01-03",
        "reporting_currency": "USD",
        "consumer_system": "lotus-performance",
        "dimensions": ["asset_class", "region"],
        "include_cash_flows": True,
        "filters": {"asset_class": "Equity"},
        "page_token": "page-2",
    }
    assert _position_rows_from_payload(
        {"rows": [{"valuation_date": "2026-01-01", "position_id": "POS_1"}, "bad-row"]}
    ) == [{"valuation_date": "2026-01-01", "position_id": "POS_1"}]
    assert _position_rows_from_payload({"rows": "bad-shape"}) == []

    snapshot_id, request_fingerprint = service._build_snapshot_identity(
        calculation_id=calculation_id,
        upstream_endpoint="fx_rates",
        source_identifier="EUR/USD",
        request_payload={"from_currency": "EUR", "to_currency": "USD"},
    )
    snapshot = service._build_snapshot(
        calculation_id=calculation_id,
        upstream_endpoint="fx_rates",
        source_identifier="EUR/USD",
        as_of_date=date(2026, 1, 3),
        request_payload={"from_currency": "EUR", "to_currency": "USD"},
        response=(200, {"rates": [{"rate": "1.2"}]}),
        snapshot_id=snapshot_id,
        request_fingerprint=request_fingerprint,
    )

    assert snapshot["snapshot_id"] == snapshot_id
    assert snapshot["request_fingerprint"] == request_fingerprint
    assert snapshot["retrieval_status"] == "200"
    assert snapshot["paging_metadata"] == {"from_currency": "EUR", "to_currency": "USD"}

    auto_snapshot = service._build_snapshot(
        calculation_id=calculation_id,
        upstream_endpoint="benchmark_market_series",
        source_identifier="BMK_1",
        as_of_date=date(2026, 1, 3),
        request_payload={"benchmark_id": "BMK_1"},
        response=(200, {"component_series": []}),
    )
    assert auto_snapshot["snapshot_id"]
    assert auto_snapshot["request_fingerprint"]

    request_payload = _position_timeseries_request_payload(
        portfolio_id="PORT_1",
        chunk=chunk,
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=[],
        include_cash_flows=False,
        filters={},
        page_token=None,
    )
    snapshot_batch: list[dict] = []
    existing_snapshot_ids: set[str] = set()
    service._append_position_timeseries_snapshot_if_new(
        calculation_id=calculation_id,
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        request_payload=request_payload,
        response=(200, {"rows": []}),
        snapshot_batch=snapshot_batch,
        existing_snapshot_ids=existing_snapshot_ids,
    )
    service._append_position_timeseries_snapshot_if_new(
        calculation_id=calculation_id,
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        request_payload=request_payload,
        response=(200, {"rows": []}),
        snapshot_batch=snapshot_batch,
        existing_snapshot_ids=existing_snapshot_ids,
    )
    service._append_position_timeseries_snapshot_if_new(
        calculation_id=None,
        portfolio_id="PORT_1",
        as_of_date=date(2026, 1, 3),
        request_payload=request_payload,
        response=(200, {"rows": []}),
        snapshot_batch=snapshot_batch,
        existing_snapshot_ids=existing_snapshot_ids,
    )
    assert len(snapshot_batch) == 1
    assert snapshot_batch[0]["upstream_endpoint"] == "position_timeseries"
    assert snapshot_batch[0]["source_identifier"] == "PORT_1"
    assert snapshot_batch[0]["paging_metadata"] == request_payload
