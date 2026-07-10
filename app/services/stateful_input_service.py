from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, TypeGuard
from uuid import UUID

from app.services.core_integration_service import CoreIntegrationService
from app.services.execution_registry import ExecutionRegistry, execution_registry
from app.services.stateful_portfolio_source_port import (
    CoreStatefulPortfolioSourceAdapter,
    StatefulPortfolioSourcePort,
)

STATEFUL_UPSTREAM_PAGE_LIMIT_EXCEEDED_REASON = "stateful_upstream_page_limit_exceeded"
STATEFUL_UPSTREAM_REPEATED_PAGE_CURSOR_REASON = "stateful_upstream_repeated_page_cursor"
POSITION_SOURCE_GRAIN_FIELDS: tuple[str, ...] = (
    "account_id",
    "sub_account_id",
    "custody_account_id",
    "book_id",
    "strategy_id",
    "mandate_id",
    "sleeve_id",
    "tax_lot_id",
    "lot_id",
)


@dataclass(frozen=True)
class DateChunk:
    start_date: date
    end_date: date


@dataclass(frozen=True)
class RetrievalMetadata:
    chunk_count: int
    page_count: int


@dataclass
class _PortfolioChunkAccumulator:
    observations: list[dict[str, Any]]
    portfolio_open_date: str | None = None
    portfolio_currency: str | None = None
    reporting_currency: str | None = None
    page_count: int = 0


@dataclass
class _PositionChunkAccumulator:
    rows: list[dict[str, Any]]
    page_count: int = 0


@dataclass(frozen=True)
class _PositionChunkPageResult:
    status_code: int
    payload: dict[str, Any]


@dataclass
class _PerformanceComponentEconomicsAccumulator:
    observed_component_families: set[str]
    supported_component_families: set[str]
    missing_component_families: set[str]
    rows: list[dict[str, Any]] = dataclass_field(default_factory=list)
    component_totals: list[dict[str, Any]] = dataclass_field(default_factory=list)
    lineage_values: list[dict[str, Any]] = dataclass_field(default_factory=list)
    request_fingerprints: list[str] = dataclass_field(default_factory=list)
    source_row_count: int = 0
    ready_chunk_count: int = 0
    unavailable_chunk_count: int = 0
    page_count: int = 0


@dataclass(frozen=True)
class _PortfolioReferenceRequest:
    portfolio_id: str
    as_of_date: date


@dataclass(frozen=True)
class _BenchmarkDefinitionRequest:
    benchmark_id: str
    as_of_date: date


@dataclass(frozen=True)
class _BenchmarkMarketSeriesRequest:
    benchmark_id: str
    as_of_date: date
    start_date: date
    end_date: date
    frequency: str
    target_currency: str | None
    series_fields: list[str]


@dataclass(frozen=True)
class _IndexPriceSeriesRequest:
    index_id: str
    as_of_date: date
    start_date: date
    end_date: date
    frequency: str
    target_currency: str | None


@dataclass(frozen=True)
class _RiskFreeSeriesRequest:
    currency: str
    as_of_date: date
    start_date: date
    end_date: date
    frequency: str
    series_mode: str


class StatefulInputService:
    def __init__(
        self,
        *,
        core_service: CoreIntegrationService,
        execution_store: ExecutionRegistry | None = None,
        portfolio_source_port: StatefulPortfolioSourcePort | None = None,
        portfolio_chunk_days: int = 90,
        reference_chunk_days: int = 365,
        max_concurrent_chunks: int = 4,
        max_pages_per_chunk: int = 25,
    ) -> None:
        self._core_service = core_service
        self._portfolio_source_port = portfolio_source_port or CoreStatefulPortfolioSourceAdapter(
            core_service=core_service,
        )
        self._execution_store = execution_store or execution_registry
        self._portfolio_chunk_days = max(1, portfolio_chunk_days)
        self._reference_chunk_days = max(1, reference_chunk_days)
        self._max_concurrent_chunks = max(1, max_concurrent_chunks)
        self._max_pages_per_chunk = max(1, max_pages_per_chunk)
        self._snapshot_id_cache: dict[UUID, set[str]] = {}

    def plan_chunks(self, *, start_date: date, end_date: date, chunk_days: int) -> list[DateChunk]:
        bounded_chunk_days = max(1, chunk_days)
        chunks: list[DateChunk] = []
        cursor = start_date
        while cursor <= end_date:
            chunk_end = min(cursor + timedelta(days=bounded_chunk_days - 1), end_date)
            chunks.append(DateChunk(start_date=cursor, end_date=chunk_end))
            cursor = chunk_end + timedelta(days=1)
        return chunks

    async def get_portfolio_timeseries(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._portfolio_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._fetch_portfolio_chunk(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                chunk=chunk,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                calculation_id=calculation_id,
            ),
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        return 200, self._build_portfolio_timeseries_payload(
            responses=responses,
            chunk_count=len(chunks),
        )

    async def get_position_timeseries(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        dimensions: list[str] | None = None,
        include_cash_flows: bool = True,
        filters: dict[str, Any] | None = None,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._portfolio_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._fetch_position_chunk(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                chunk=chunk,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                dimensions=dimensions or [],
                include_cash_flows=include_cash_flows,
                filters=filters or {},
                calculation_id=calculation_id,
            ),
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        return 200, self._build_position_timeseries_payload(
            responses=responses,
            chunk_count=len(chunks),
        )

    async def get_performance_component_economics(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        security_ids: list[str] | None = None,
        transaction_types: list[str] | None = None,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=366,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._fetch_performance_component_economics_chunk(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                chunk=chunk,
                security_ids=security_ids,
                transaction_types=transaction_types,
            ),
        )
        self._record_performance_component_economics_snapshots(
            calculation_id=calculation_id,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            chunks=chunks,
            security_ids=security_ids,
            transaction_types=transaction_types,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        return 200, self._build_performance_component_economics_payload(
            responses=responses,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            chunk_count=len(chunks),
        )

    async def get_benchmark_assignment(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        reporting_currency: str | None = None,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        response = await self._core_service.get_benchmark_assignment(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            reporting_currency=reporting_currency,
        )
        if calculation_id is not None:
            request_payload = {
                "portfolio_id": portfolio_id,
                "reporting_currency": reporting_currency,
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="benchmark_assignment",
                source_identifier=portfolio_id,
                request_payload=request_payload,
            )
            existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
            if snapshot_id not in existing_snapshot_ids:
                self._execution_store.record_upstream_snapshots(
                    calculation_id=calculation_id,
                    snapshots=[
                        self._build_snapshot(
                            calculation_id=calculation_id,
                            upstream_endpoint="benchmark_assignment",
                            source_identifier=portfolio_id,
                            as_of_date=as_of_date,
                            request_payload=request_payload,
                            response=response,
                            snapshot_id=snapshot_id,
                            request_fingerprint=request_fingerprint,
                        )
                    ],
                )
                existing_snapshot_ids.add(snapshot_id)
        return response

    async def get_portfolio_reference(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = _PortfolioReferenceRequest(portfolio_id=portfolio_id, as_of_date=as_of_date)
        return await self._get_single_reference_payload(request=request, calculation_id=calculation_id)

    async def get_benchmark_return_series(
        self,
        *,
        benchmark_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._core_service.get_benchmark_return_series(
                benchmark_id=benchmark_id,
                as_of_date=as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                frequency=frequency,
            ),
        )
        self._record_benchmark_return_series_snapshots(
            calculation_id=calculation_id,
            benchmark_id=benchmark_id,
            as_of_date=as_of_date,
            frequency=frequency,
            chunks=chunks,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        points = self._merge_dedup_points_from_responses(responses)
        return 200, {
            "points": points,
            "retrieval_metadata": {
                "chunk_count": len(chunks),
                "page_count": len(chunks),
            },
        }

    async def _get_single_reference_payload(
        self,
        *,
        request: _PortfolioReferenceRequest | _BenchmarkDefinitionRequest,
        calculation_id: UUID | None,
    ) -> tuple[int, dict[str, Any]]:
        response = await self._fetch_single_reference_payload(request)
        self._record_single_reference_snapshot(
            request=request,
            calculation_id=calculation_id,
            response=response,
        )
        return response

    async def _fetch_single_reference_payload(
        self, request: _PortfolioReferenceRequest | _BenchmarkDefinitionRequest
    ) -> tuple[int, dict[str, Any]]:
        if isinstance(request, _PortfolioReferenceRequest):
            return await self._portfolio_source_port.fetch_reference(
                portfolio_id=request.portfolio_id,
                as_of_date=request.as_of_date,
            )
        return await self._core_service.get_benchmark_definition(
            benchmark_id=request.benchmark_id,
            as_of_date=request.as_of_date,
        )

    def _record_single_reference_snapshot(
        self,
        *,
        request: _PortfolioReferenceRequest | _BenchmarkDefinitionRequest,
        calculation_id: UUID | None,
        response: tuple[int, dict[str, Any]],
    ) -> None:
        if isinstance(request, _PortfolioReferenceRequest):
            upstream_endpoint = "portfolio_reference"
            source_identifier = request.portfolio_id
            request_payload = {
                "portfolio_id": request.portfolio_id,
                "as_of_date": str(request.as_of_date),
            }
        else:
            upstream_endpoint = "benchmark_definition"
            source_identifier = request.benchmark_id
            request_payload = {
                "benchmark_id": request.benchmark_id,
                "as_of_date": str(request.as_of_date),
            }
        self._record_single_response_snapshot(
            calculation_id=calculation_id,
            upstream_endpoint=upstream_endpoint,
            source_identifier=source_identifier,
            as_of_date=request.as_of_date,
            request_payload=request_payload,
            response=response,
        )

    def _record_benchmark_return_series_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        benchmark_id: str,
        as_of_date: date,
        frequency: str,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        for chunk, response in zip(chunks, responses):
            request_payload = {
                "benchmark_id": benchmark_id,
                "start_date": str(chunk.start_date),
                "end_date": str(chunk.end_date),
                "frequency": frequency,
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="benchmark_return_series",
                source_identifier=benchmark_id,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="benchmark_return_series",
                    source_identifier=benchmark_id,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            )
            existing_snapshot_ids.add(snapshot_id)
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

    async def get_benchmark_definition(
        self,
        *,
        benchmark_id: str,
        as_of_date: date,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = _BenchmarkDefinitionRequest(benchmark_id=benchmark_id, as_of_date=as_of_date)
        return await self._get_single_reference_payload(request=request, calculation_id=calculation_id)

    async def get_benchmark_composition_window(
        self,
        *,
        benchmark_id: str,
        start_date: date,
        end_date: date,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        response = await self._core_service.get_benchmark_composition_window(
            benchmark_id=benchmark_id,
            start_date=start_date,
            end_date=end_date,
        )
        if calculation_id is not None:
            request_payload = {
                "benchmark_id": benchmark_id,
                "start_date": str(start_date),
                "end_date": str(end_date),
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="benchmark_composition_window",
                source_identifier=benchmark_id,
                request_payload=request_payload,
            )
            existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
            if snapshot_id not in existing_snapshot_ids:
                self._execution_store.record_upstream_snapshots(
                    calculation_id=calculation_id,
                    snapshots=[
                        self._build_snapshot(
                            calculation_id=calculation_id,
                            upstream_endpoint="benchmark_composition_window",
                            source_identifier=benchmark_id,
                            as_of_date=end_date,
                            request_payload=request_payload,
                            response=response,
                            snapshot_id=snapshot_id,
                            request_fingerprint=request_fingerprint,
                        )
                    ],
                )
                existing_snapshot_ids.add(snapshot_id)
        return response

    async def get_benchmark_market_series(
        self,
        *,
        benchmark_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
        target_currency: str | None = None,
        series_fields: list[str] | None = None,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = _BenchmarkMarketSeriesRequest(
            benchmark_id=benchmark_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            target_currency=target_currency,
            series_fields=series_fields or ["index_return", "component_weight"],
        )
        return await self._get_benchmark_market_series(request=request, calculation_id=calculation_id)

    async def _get_benchmark_market_series(
        self,
        *,
        request: _BenchmarkMarketSeriesRequest,
        calculation_id: UUID | None,
    ) -> tuple[int, dict[str, Any]]:
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=request.start_date,
            end_date=request.end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._fetch_benchmark_market_series_chunk(request=request, chunk=chunk),
        )
        self._record_benchmark_market_series_snapshots(
            calculation_id=calculation_id,
            request=request,
            chunks=chunks,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        return self._benchmark_market_series_response_payload(chunks=chunks, responses=responses)

    async def _fetch_benchmark_market_series_chunk(
        self,
        *,
        request: _BenchmarkMarketSeriesRequest,
        chunk: DateChunk,
    ) -> tuple[int, dict[str, Any]]:
        return await self._core_service.get_benchmark_market_series(
            benchmark_id=request.benchmark_id,
            as_of_date=request.as_of_date,
            start_date=chunk.start_date,
            end_date=chunk.end_date,
            frequency=request.frequency,
            target_currency=request.target_currency,
            series_fields=request.series_fields,
        )

    def _benchmark_market_series_response_payload(
        self,
        *,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
    ) -> tuple[int, dict[str, Any]]:
        component_series = self._merge_component_series(
            payloads=[payload for _, payload in responses if isinstance(payload, dict)]
        )
        return 200, {
            "component_series": component_series,
            "retrieval_metadata": {
                "chunk_count": len(chunks),
                "page_count": len(chunks),
            },
        }

    def _record_benchmark_market_series_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        request: _BenchmarkMarketSeriesRequest,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        for chunk, response in zip(chunks, responses):
            request_payload = _benchmark_market_series_request_payload(request=request, chunk=chunk)
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="benchmark_market_series",
                source_identifier=request.benchmark_id,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="benchmark_market_series",
                    source_identifier=request.benchmark_id,
                    as_of_date=request.as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            )
            existing_snapshot_ids.add(snapshot_id)
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

    async def get_fx_rates(
        self,
        *,
        from_currency: str,
        to_currency: str,
        start_date: date,
        end_date: date,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._core_service.get_fx_rates(
                from_currency=from_currency,
                to_currency=to_currency,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
            ),
        )
        self._record_fx_rate_snapshots(
            calculation_id=calculation_id,
            from_currency=from_currency,
            to_currency=to_currency,
            as_of_date=end_date,
            chunks=chunks,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        merged_rates = self._merge_dedup_fx_rates_from_responses(responses)
        return 200, {
            "points": merged_rates,
            "retrieval_metadata": {
                "chunk_count": len(chunks),
                "page_count": len(chunks),
            },
        }

    def _record_fx_rate_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        source_identifier = f"{from_currency}/{to_currency}"
        for chunk, response in zip(chunks, responses):
            request_payload = {
                "from_currency": from_currency,
                "to_currency": to_currency,
                "start_date": str(chunk.start_date),
                "end_date": str(chunk.end_date),
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="fx_rates",
                source_identifier=source_identifier,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="fx_rates",
                    source_identifier=source_identifier,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            )
            existing_snapshot_ids.add(snapshot_id)
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

    async def get_index_catalog(
        self,
        *,
        as_of_date: date,
        index_ids: list[str] | None = None,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        response = await self._core_service.get_index_catalog(
            as_of_date=as_of_date,
            index_ids=index_ids,
        )
        self._record_index_catalog_snapshot(
            calculation_id=calculation_id,
            as_of_date=as_of_date,
            index_ids=index_ids,
            response=response,
        )
        return response

    def _record_index_catalog_snapshot(
        self,
        *,
        calculation_id: UUID | None,
        as_of_date: date,
        index_ids: list[str] | None,
        response: tuple[int, dict[str, Any]],
    ) -> None:
        if calculation_id is None:
            return
        sorted_index_ids = sorted(set(index_ids or []))
        source_identifier = "|".join(sorted_index_ids) if sorted_index_ids else "all_indices"
        request_payload = {
            "as_of_date": str(as_of_date),
            "index_ids": sorted_index_ids,
        }
        snapshot_id, request_fingerprint = self._build_snapshot_identity(
            calculation_id=calculation_id,
            upstream_endpoint="index_catalog",
            source_identifier=source_identifier,
            request_payload=request_payload,
        )
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        if snapshot_id in existing_snapshot_ids:
            return
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=[
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="index_catalog",
                    source_identifier=source_identifier,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            ],
        )
        existing_snapshot_ids.add(snapshot_id)

    async def get_index_price_series(
        self,
        *,
        index_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
        target_currency: str | None = None,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = _IndexPriceSeriesRequest(
            index_id=index_id,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            target_currency=target_currency,
        )
        return await self._get_chunked_points_series(request=request, calculation_id=calculation_id)

    async def get_risk_free_series(
        self,
        *,
        currency: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
        series_mode: str = "return_series",
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request = _RiskFreeSeriesRequest(
            currency=currency,
            as_of_date=as_of_date,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            series_mode=series_mode,
        )
        return await self._get_chunked_points_series(request=request, calculation_id=calculation_id)

    async def _get_chunked_points_series(
        self,
        *,
        request: _IndexPriceSeriesRequest | _RiskFreeSeriesRequest,
        calculation_id: UUID | None,
    ) -> tuple[int, dict[str, Any]]:
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=request.start_date,
            end_date=request.end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._fetch_chunked_points_series(request=request, chunk=chunk),
        )
        self._record_chunked_points_series_snapshots(
            request=request,
            calculation_id=calculation_id,
            chunks=chunks,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        points = self._merge_dedup_points_from_responses(responses)
        return 200, {
            "points": points,
            "retrieval_metadata": {
                "chunk_count": len(chunks),
                "page_count": len(chunks),
            },
        }

    async def _fetch_chunked_points_series(
        self,
        *,
        request: _IndexPriceSeriesRequest | _RiskFreeSeriesRequest,
        chunk: DateChunk,
    ) -> tuple[int, dict[str, Any]]:
        if isinstance(request, _IndexPriceSeriesRequest):
            return await self._core_service.get_index_price_series(
                index_id=request.index_id,
                as_of_date=request.as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                frequency=request.frequency,
                target_currency=request.target_currency,
            )
        return await self._core_service.get_risk_free_series(
            currency=request.currency,
            as_of_date=request.as_of_date,
            start_date=chunk.start_date,
            end_date=chunk.end_date,
            frequency=request.frequency,
            series_mode=request.series_mode,
        )

    def _record_chunked_points_series_snapshots(
        self,
        *,
        request: _IndexPriceSeriesRequest | _RiskFreeSeriesRequest,
        calculation_id: UUID | None,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if isinstance(request, _IndexPriceSeriesRequest):
            upstream_endpoint = "index_price_series"
            source_identifier = request.index_id

            def request_payload_factory(chunk: DateChunk) -> dict[str, Any]:
                return _index_price_series_request_payload(
                    index_id=request.index_id,
                    chunk=chunk,
                    frequency=request.frequency,
                    target_currency=request.target_currency,
                )

        else:
            upstream_endpoint = "risk_free_series"
            source_identifier = request.currency

            def request_payload_factory(chunk: DateChunk) -> dict[str, Any]:
                return _risk_free_series_request_payload(
                    currency=request.currency,
                    chunk=chunk,
                    frequency=request.frequency,
                    series_mode=request.series_mode,
                )

        self._record_chunked_series_snapshots(
            calculation_id=calculation_id,
            upstream_endpoint=upstream_endpoint,
            source_identifier=source_identifier,
            as_of_date=request.as_of_date,
            chunks=chunks,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
            request_payload_factory=request_payload_factory,
        )

    def _record_chunked_series_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        upstream_endpoint: str,
        source_identifier: str,
        as_of_date: date,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
        request_payload_factory: Callable[[DateChunk], dict[str, Any]],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        for chunk, response in zip(chunks, responses):
            request_payload = request_payload_factory(chunk)
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint=upstream_endpoint,
                source_identifier=source_identifier,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint=upstream_endpoint,
                    source_identifier=source_identifier,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            )
            existing_snapshot_ids.add(snapshot_id)
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

    async def _fetch_portfolio_chunk(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        reporting_currency: str | None,
        consumer_system: str,
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        chunk_accumulator = _PortfolioChunkAccumulator(observations=[])
        snapshot_batch: list[dict[str, Any]] = []
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)

        while True:
            status_code, payload, request_payload = await self._fetch_portfolio_timeseries_page(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                chunk=chunk,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                page_token=page_token,
            )
            self._append_portfolio_timeseries_snapshot_if_new(
                calculation_id=calculation_id,
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                request_payload=request_payload,
                response=(status_code, payload),
                snapshot_batch=snapshot_batch,
                existing_snapshot_ids=existing_snapshot_ids,
            )
            if status_code >= 400:
                self._record_upstream_snapshot_batch(
                    calculation_id=calculation_id,
                    snapshots=snapshot_batch,
                )
                return status_code, payload
            _record_portfolio_chunk_payload(accumulator=chunk_accumulator, payload=payload)

            page_token = self._next_page_token(payload)
            if not page_token:
                break
            pagination_failure = self._page_traversal_failure_payload(
                chunk=chunk,
                page_count=chunk_accumulator.page_count,
                next_page_token=page_token,
                seen_page_tokens=seen_page_tokens,
            )
            if pagination_failure is not None:
                failure_request_payload = _portfolio_timeseries_request_payload(
                    portfolio_id=portfolio_id,
                    chunk=chunk,
                    reporting_currency=reporting_currency,
                    consumer_system=consumer_system,
                    page_token=page_token,
                )
                self._record_pagination_failure_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="portfolio_timeseries",
                    source_identifier=portfolio_id,
                    as_of_date=as_of_date,
                    request_payload=failure_request_payload,
                    pagination_failure=pagination_failure,
                    snapshot_batch=snapshot_batch,
                    existing_snapshot_ids=existing_snapshot_ids,
                )
                return 503, pagination_failure
            seen_page_tokens.add(page_token)

        self._record_upstream_snapshot_batch(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

        return 200, self._build_portfolio_chunk_payload(accumulator=chunk_accumulator)

    def _build_portfolio_chunk_payload(
        self,
        *,
        accumulator: _PortfolioChunkAccumulator,
    ) -> dict[str, Any]:
        return {
            "portfolio_open_date": accumulator.portfolio_open_date,
            "portfolio_currency": accumulator.portfolio_currency,
            "reporting_currency": accumulator.reporting_currency,
            "observations": self._merge_dedup_records(
                records=accumulator.observations,
                date_key="valuation_date",
            ),
            "retrieval_metadata": {
                "page_count": accumulator.page_count,
            },
        }

    async def _fetch_portfolio_timeseries_page(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        reporting_currency: str | None,
        consumer_system: str,
        page_token: str | None,
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        response = await self._portfolio_source_port.fetch_timeseries_page(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=chunk.start_date,
            end_date=chunk.end_date,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
            page_token=page_token,
        )
        return (
            response[0],
            response[1],
            _portfolio_timeseries_request_payload(
                portfolio_id=portfolio_id,
                chunk=chunk,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                page_token=page_token,
            ),
        )

    def _append_portfolio_timeseries_snapshot_if_new(
        self,
        *,
        calculation_id: UUID | None,
        portfolio_id: str,
        as_of_date: date,
        request_payload: dict[str, Any],
        response: tuple[int, dict[str, Any]],
        snapshot_batch: list[dict[str, Any]],
        existing_snapshot_ids: set[str],
    ) -> None:
        self._append_timeseries_snapshot_if_new(
            calculation_id=calculation_id,
            upstream_endpoint="portfolio_timeseries",
            source_identifier=portfolio_id,
            as_of_date=as_of_date,
            request_payload=request_payload,
            response=response,
            snapshot_batch=snapshot_batch,
            existing_snapshot_ids=existing_snapshot_ids,
        )

    async def _fetch_position_chunk(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        reporting_currency: str | None,
        consumer_system: str,
        dimensions: list[str],
        include_cash_flows: bool,
        filters: dict[str, Any],
        calculation_id: UUID | None = None,
    ) -> tuple[int, dict[str, Any]]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        accumulator = _PositionChunkAccumulator(rows=[])
        snapshot_batch: list[dict[str, Any]] = []
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)

        while True:
            page_result = await self._fetch_and_record_position_page(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                chunk=chunk,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                dimensions=dimensions,
                include_cash_flows=include_cash_flows,
                filters=filters,
                page_token=page_token,
                calculation_id=calculation_id,
                snapshot_batch=snapshot_batch,
                existing_snapshot_ids=existing_snapshot_ids,
            )
            if page_result.status_code >= 400:
                self._record_upstream_snapshot_batch(
                    calculation_id=calculation_id,
                    snapshots=snapshot_batch,
                )
                return page_result.status_code, page_result.payload
            _record_position_chunk_payload(accumulator=accumulator, payload=page_result.payload)

            page_token = self._next_page_token(page_result.payload)
            if not page_token:
                break
            pagination_failure = self._page_traversal_failure_payload(
                chunk=chunk,
                page_count=accumulator.page_count,
                next_page_token=page_token,
                seen_page_tokens=seen_page_tokens,
            )
            if pagination_failure is not None:
                failure_request_payload = _position_timeseries_request_payload(
                    portfolio_id=portfolio_id,
                    chunk=chunk,
                    reporting_currency=reporting_currency,
                    consumer_system=consumer_system,
                    dimensions=dimensions,
                    include_cash_flows=include_cash_flows,
                    filters=filters,
                    page_token=page_token,
                )
                self._record_pagination_failure_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="position_timeseries",
                    source_identifier=portfolio_id,
                    as_of_date=as_of_date,
                    request_payload=failure_request_payload,
                    pagination_failure=pagination_failure,
                    snapshot_batch=snapshot_batch,
                    existing_snapshot_ids=existing_snapshot_ids,
                )
                return 503, pagination_failure
            seen_page_tokens.add(page_token)

        self._record_upstream_snapshot_batch(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

        return 200, self._build_position_chunk_payload(accumulator=accumulator)

    async def _fetch_and_record_position_page(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        reporting_currency: str | None,
        consumer_system: str,
        dimensions: list[str],
        include_cash_flows: bool,
        filters: dict[str, Any],
        page_token: str | None,
        calculation_id: UUID | None,
        snapshot_batch: list[dict[str, Any]],
        existing_snapshot_ids: set[str],
    ) -> _PositionChunkPageResult:
        status_code, payload, request_payload = await self._fetch_position_timeseries_page(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            chunk=chunk,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
            dimensions=dimensions,
            include_cash_flows=include_cash_flows,
            filters=filters,
            page_token=page_token,
        )
        self._append_position_timeseries_snapshot_if_new(
            calculation_id=calculation_id,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            request_payload=request_payload,
            response=(status_code, payload),
            snapshot_batch=snapshot_batch,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        return _PositionChunkPageResult(status_code=status_code, payload=payload)

    def _build_position_chunk_payload(
        self,
        *,
        accumulator: _PositionChunkAccumulator,
    ) -> dict[str, Any]:
        return {
            "rows": self._merge_dedup_records_by_fields(
                records=_position_rows_with_source_keys(accumulator.rows),
                key_fields=("valuation_date", "position_id", "source_position_key"),
            ),
            "retrieval_metadata": {
                "page_count": accumulator.page_count,
            },
        }

    async def _fetch_position_timeseries_page(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        reporting_currency: str | None,
        consumer_system: str,
        dimensions: list[str],
        include_cash_flows: bool,
        filters: dict[str, Any],
        page_token: str | None,
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        response = await self._core_service.get_position_analytics_timeseries(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            start_date=chunk.start_date,
            end_date=chunk.end_date,
            reporting_currency=reporting_currency,
            consumer_system=consumer_system,
            dimensions=dimensions,
            include_cash_flows=include_cash_flows,
            filters=filters,
            page_token=page_token,
        )
        return (
            response[0],
            response[1],
            _position_timeseries_request_payload(
                portfolio_id=portfolio_id,
                chunk=chunk,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                dimensions=dimensions,
                include_cash_flows=include_cash_flows,
                filters=filters,
                page_token=page_token,
            ),
        )

    async def _fetch_performance_component_economics_chunk(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        security_ids: list[str] | None,
        transaction_types: list[str] | None,
    ) -> tuple[int, dict[str, Any]]:
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        accumulator = _PerformanceComponentEconomicsAccumulator(
            observed_component_families=set(),
            supported_component_families=set(),
            missing_component_families=set(),
            rows=[],
            component_totals=[],
        )
        while True:
            status_code, payload = await self._core_service.get_performance_component_economics(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                security_ids=security_ids,
                transaction_types=transaction_types,
                page_token=page_token,
            )
            if status_code >= 400:
                return status_code, payload
            _record_performance_component_economics_payload(accumulator=accumulator, payload=payload)

            page_token = self._next_page_token(payload)
            if not page_token:
                break
            pagination_failure = self._page_traversal_failure_payload(
                chunk=chunk,
                page_count=accumulator.page_count,
                next_page_token=page_token,
                seen_page_tokens=seen_page_tokens,
            )
            if pagination_failure is not None:
                return 503, pagination_failure
            seen_page_tokens.add(page_token)

        return 200, _build_performance_component_economics_chunk_payload(
            accumulator=accumulator,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            chunk=chunk,
        )

    def _record_performance_component_economics_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        portfolio_id: str,
        as_of_date: date,
        chunks: list[DateChunk],
        security_ids: list[str] | None,
        transaction_types: list[str] | None,
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        for chunk, response in zip(chunks, responses):
            request_payload = _performance_component_economics_request_payload(
                portfolio_id=portfolio_id,
                chunk=chunk,
                security_ids=security_ids,
                transaction_types=transaction_types,
            )
            self._append_timeseries_snapshot_if_new(
                calculation_id=calculation_id,
                upstream_endpoint="performance_component_economics",
                source_identifier=portfolio_id,
                as_of_date=as_of_date,
                request_payload=request_payload,
                response=response,
                snapshot_batch=snapshot_batch,
                existing_snapshot_ids=existing_snapshot_ids,
            )
        self._record_upstream_snapshot_batch(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

    def _record_upstream_snapshot_batch(
        self,
        *,
        calculation_id: UUID | None,
        snapshots: list[dict[str, Any]],
    ) -> None:
        if calculation_id is None:
            return
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=snapshots,
        )

    def _append_position_timeseries_snapshot_if_new(
        self,
        *,
        calculation_id: UUID | None,
        portfolio_id: str,
        as_of_date: date,
        request_payload: dict[str, Any],
        response: tuple[int, dict[str, Any]],
        snapshot_batch: list[dict[str, Any]],
        existing_snapshot_ids: set[str],
    ) -> None:
        self._append_timeseries_snapshot_if_new(
            calculation_id=calculation_id,
            upstream_endpoint="position_timeseries",
            source_identifier=portfolio_id,
            as_of_date=as_of_date,
            request_payload=request_payload,
            response=response,
            snapshot_batch=snapshot_batch,
            existing_snapshot_ids=existing_snapshot_ids,
        )

    def _record_pagination_failure_snapshot(
        self,
        *,
        calculation_id: UUID | None,
        upstream_endpoint: str,
        source_identifier: str,
        as_of_date: date,
        request_payload: dict[str, Any],
        pagination_failure: dict[str, Any],
        snapshot_batch: list[dict[str, Any]],
        existing_snapshot_ids: set[str],
    ) -> None:
        request_payload["pagination_guard_reason"] = pagination_failure["reason"]
        self._append_timeseries_snapshot_if_new(
            calculation_id=calculation_id,
            upstream_endpoint=upstream_endpoint,
            source_identifier=source_identifier,
            as_of_date=as_of_date,
            request_payload=request_payload,
            response=(503, pagination_failure),
            snapshot_batch=snapshot_batch,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        self._record_upstream_snapshot_batch(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

    def _append_timeseries_snapshot_if_new(
        self,
        *,
        calculation_id: UUID | None,
        upstream_endpoint: str,
        source_identifier: str,
        as_of_date: date,
        request_payload: dict[str, Any],
        response: tuple[int, dict[str, Any]],
        snapshot_batch: list[dict[str, Any]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_id, request_fingerprint = self._build_snapshot_identity(
            calculation_id=calculation_id,
            upstream_endpoint=upstream_endpoint,
            source_identifier=source_identifier,
            request_payload=request_payload,
        )
        if snapshot_id not in existing_snapshot_ids:
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint=upstream_endpoint,
                    source_identifier=source_identifier,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            )
            existing_snapshot_ids.add(snapshot_id)

    async def _gather_chunked(
        self,
        *,
        chunks: list[DateChunk],
        fetcher: Callable[[DateChunk], Awaitable[tuple[int, dict[str, Any]]]],
    ) -> list[tuple[int, dict[str, Any]]]:
        semaphore = asyncio.Semaphore(self._max_concurrent_chunks)

        async def _run(chunk: DateChunk) -> tuple[int, dict[str, Any]]:
            async with semaphore:
                return await fetcher(chunk)

        return list(await asyncio.gather(*[_run(chunk) for chunk in chunks]))

    def _first_failure(self, responses: list[tuple[int, dict[str, Any]]]) -> tuple[int, dict[str, Any]] | None:
        for status_code, payload in responses:
            if status_code >= 400:
                return status_code, payload
        return None

    def _total_retrieval_page_count(self, responses: list[tuple[int, dict[str, Any]]]) -> int:
        return sum(_retrieval_page_count(payload) for _, payload in responses)

    def _build_portfolio_timeseries_payload(
        self,
        *,
        responses: list[tuple[int, dict[str, Any]]],
        chunk_count: int,
    ) -> dict[str, Any]:
        open_dates = _string_payload_values(responses=responses, field_name="portfolio_open_date")
        return {
            "portfolio_open_date": min(open_dates) if open_dates else None,
            "portfolio_currency": _single_value_or_none(
                set(_string_payload_values(responses=responses, field_name="portfolio_currency"))
            ),
            "reporting_currency": _single_value_or_none(
                set(_string_payload_values(responses=responses, field_name="reporting_currency"))
            ),
            "observations": self._merge_dedup_records(
                records=_dict_list_payload_items(responses=responses, field_name="observations"),
                date_key="valuation_date",
            ),
            "retrieval_metadata": {
                "chunk_count": chunk_count,
                "page_count": self._total_retrieval_page_count(responses),
            },
        }

    def _build_position_timeseries_payload(
        self,
        *,
        responses: list[tuple[int, dict[str, Any]]],
        chunk_count: int,
    ) -> dict[str, Any]:
        return {
            "rows": self._merge_dedup_records_by_fields(
                records=_position_rows_from_responses(responses),
                key_fields=("valuation_date", "position_id", "source_position_key"),
            ),
            "retrieval_metadata": {
                "chunk_count": chunk_count,
                "page_count": self._total_retrieval_page_count(responses),
            },
        }

    def _build_performance_component_economics_payload(
        self,
        *,
        responses: list[tuple[int, dict[str, Any]]],
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        chunk_count: int,
    ) -> dict[str, Any]:
        accumulator = _performance_component_economics_accumulator(responses)
        return {
            "product_name": "PerformanceComponentEconomics",
            "product_version": "v1",
            "portfolio_id": portfolio_id,
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "rows": self._merge_dedup_records_by_fields(
                records=_performance_component_economics_rows_from_responses(responses),
                key_fields=("security_id", "transaction_date", "transaction_id"),
            ),
            "component_totals": _performance_component_economics_component_totals_from_responses(responses),
            "component_totals_scope": "consumed_pages",
            "supportability": _performance_component_economics_supportability(
                accumulator=accumulator,
                chunk_count=chunk_count,
            ),
            "lineage": _performance_component_economics_lineage_from_responses(responses),
            "request_fingerprints": _performance_component_economics_request_fingerprints(responses),
            "retrieval_metadata": {
                "chunk_count": chunk_count,
                "page_count": self._total_retrieval_page_count(responses),
            },
        }

    def _next_page_token(self, payload: dict[str, Any]) -> str | None:
        next_page_token = payload.get("next_page_token")
        if _non_empty_string(next_page_token):
            return next_page_token
        page_block = payload.get("page")
        if isinstance(page_block, dict):
            nested_token = page_block.get("next_page_token")
            if _non_empty_string(nested_token):
                return nested_token
        return None

    def _page_traversal_failure_payload(
        self,
        *,
        chunk: DateChunk,
        page_count: int,
        next_page_token: str,
        seen_page_tokens: set[str],
    ) -> dict[str, Any] | None:
        if next_page_token in seen_page_tokens:
            reason = STATEFUL_UPSTREAM_REPEATED_PAGE_CURSOR_REASON
        elif page_count >= self._max_pages_per_chunk:
            reason = STATEFUL_UPSTREAM_PAGE_LIMIT_EXCEEDED_REASON
        else:
            return None
        return {
            "error": "Stateful upstream pagination is unhealthy.",
            "reason": reason,
            "retrieval_metadata": {
                "chunk_start_date": str(chunk.start_date),
                "chunk_end_date": str(chunk.end_date),
                "page_count": page_count,
                "max_pages_per_chunk": self._max_pages_per_chunk,
            },
        }

    def _merge_dedup_records(self, *, records: list[dict[str, Any]], date_key: str) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for record in records:
            record_date = record.get(date_key)
            if isinstance(record_date, str):
                deduped[record_date] = record
        return [deduped[key] for key in sorted(deduped)]

    def _merge_dedup_points_from_responses(self, responses: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
        return self._merge_dedup_records(
            records=[
                point
                for _, payload in responses
                for point in (payload.get("points", []) if isinstance(payload, dict) else [])
                if isinstance(point, dict)
            ],
            date_key="series_date",
        )

    def _merge_dedup_fx_rates_from_responses(self, responses: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
        return self._merge_dedup_records(
            records=[
                {"series_date": rate.get("rate_date"), "fx_rate": rate.get("rate")}
                for _, payload in responses
                for rate in (payload.get("rates", []) if isinstance(payload, dict) else [])
                if isinstance(rate, dict)
            ],
            date_key="series_date",
        )

    def _merge_dedup_records_by_fields(
        self,
        *,
        records: list[dict[str, Any]],
        key_fields: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        deduped: dict[tuple[str, ...], dict[str, Any]] = {}
        for record in records:
            record_key = _record_key_by_fields(record=record, key_fields=key_fields)
            if record_key is None:
                continue
            deduped[record_key] = record
        return [deduped[key] for key in sorted(deduped)]

    def _merge_component_series(self, *, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged_by_index = self._component_points_by_index(payloads)
        merged_components: list[dict[str, Any]] = []
        for index_id in sorted(merged_by_index):
            merged_components.append(
                {
                    "index_id": index_id,
                    "points": self._merge_dedup_records(
                        records=merged_by_index[index_id],
                        date_key="series_date",
                    ),
                }
            )
        return merged_components

    def _component_points_by_index(self, payloads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        merged_by_index: dict[str, list[dict[str, Any]]] = {}
        for payload in payloads:
            component_series_raw = payload.get("component_series")
            if not isinstance(component_series_raw, list):
                continue
            for component in component_series_raw:
                component_points = _component_index_points(component)
                if component_points is None:
                    continue
                index_id, points = component_points
                merged_by_index.setdefault(index_id, []).extend(points)
        return merged_by_index

    def _build_snapshot(
        self,
        *,
        calculation_id: UUID,
        upstream_endpoint: str,
        source_identifier: str,
        as_of_date: date,
        request_payload: dict[str, Any],
        response: tuple[int, dict[str, Any]],
        snapshot_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        status_code, payload = response
        if snapshot_id is None or request_fingerprint is None:
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint=upstream_endpoint,
                source_identifier=source_identifier,
                request_payload=request_payload,
            )
        response_json = json.dumps(payload, sort_keys=True)
        response_fingerprint = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
        return {
            "snapshot_id": snapshot_id,
            "upstream_endpoint": upstream_endpoint,
            "source_identifier": source_identifier,
            "as_of_date": str(as_of_date),
            "request_fingerprint": request_fingerprint,
            "response_fingerprint": response_fingerprint,
            "retrieval_status": str(status_code),
            "paging_metadata": request_payload,
        }

    def _record_single_response_snapshot(
        self,
        *,
        calculation_id: UUID | None,
        upstream_endpoint: str,
        source_identifier: str,
        as_of_date: date,
        request_payload: dict[str, Any],
        response: tuple[int, dict[str, Any]],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_id, request_fingerprint = self._build_snapshot_identity(
            calculation_id=calculation_id,
            upstream_endpoint=upstream_endpoint,
            source_identifier=source_identifier,
            request_payload=request_payload,
        )
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        if snapshot_id in existing_snapshot_ids:
            return
        self._execution_store.record_upstream_snapshots(
            calculation_id=calculation_id,
            snapshots=[
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint=upstream_endpoint,
                    source_identifier=source_identifier,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            ],
        )
        existing_snapshot_ids.add(snapshot_id)

    def _build_snapshot_identity(
        self,
        *,
        calculation_id: UUID,
        upstream_endpoint: str,
        source_identifier: str,
        request_payload: dict[str, Any],
    ) -> tuple[str, str]:
        request_json = json.dumps(request_payload, sort_keys=True)
        request_fingerprint = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        snapshot_id = hashlib.sha256(
            f"{calculation_id}:{upstream_endpoint}:{source_identifier}:{request_fingerprint}".encode("utf-8")
        ).hexdigest()
        return snapshot_id, request_fingerprint

    def _existing_snapshot_ids(self, calculation_id: UUID | None) -> set[str]:
        if calculation_id is None:
            return set()
        cached_snapshot_ids = self._snapshot_id_cache.get(calculation_id)
        if cached_snapshot_ids is None:
            cached_snapshot_ids = self._execution_store.list_upstream_snapshot_ids(calculation_id)
            self._snapshot_id_cache[calculation_id] = cached_snapshot_ids
        return cached_snapshot_ids


def _single_value_or_none(values: set[str]) -> str | None:
    return next(iter(values)) if len(values) == 1 else None


def _portfolio_timeseries_request_payload(
    *,
    portfolio_id: str,
    chunk: DateChunk,
    reporting_currency: str | None,
    consumer_system: str,
    page_token: str | None,
) -> dict[str, Any]:
    return {
        "portfolio_id": portfolio_id,
        "start_date": str(chunk.start_date),
        "end_date": str(chunk.end_date),
        "reporting_currency": reporting_currency,
        "consumer_system": consumer_system,
        "page_token": page_token,
    }


def _index_price_series_request_payload(
    *,
    index_id: str,
    chunk: DateChunk,
    frequency: str,
    target_currency: str | None,
) -> dict[str, Any]:
    return {
        "index_id": index_id,
        "start_date": str(chunk.start_date),
        "end_date": str(chunk.end_date),
        "frequency": frequency,
        "target_currency": target_currency,
    }


def _benchmark_market_series_request_payload(
    *,
    request: _BenchmarkMarketSeriesRequest,
    chunk: DateChunk,
) -> dict[str, Any]:
    return {
        "benchmark_id": request.benchmark_id,
        "start_date": str(chunk.start_date),
        "end_date": str(chunk.end_date),
        "frequency": request.frequency,
        "target_currency": request.target_currency,
        "series_fields": request.series_fields,
    }


def _risk_free_series_request_payload(
    *,
    currency: str,
    chunk: DateChunk,
    frequency: str,
    series_mode: str,
) -> dict[str, Any]:
    return {
        "currency": currency,
        "start_date": str(chunk.start_date),
        "end_date": str(chunk.end_date),
        "frequency": frequency,
        "series_mode": series_mode,
    }


def _position_timeseries_request_payload(
    *,
    portfolio_id: str,
    chunk: DateChunk,
    reporting_currency: str | None,
    consumer_system: str,
    dimensions: list[str],
    include_cash_flows: bool,
    filters: dict[str, Any],
    page_token: str | None,
) -> dict[str, Any]:
    return {
        "portfolio_id": portfolio_id,
        "start_date": str(chunk.start_date),
        "end_date": str(chunk.end_date),
        "reporting_currency": reporting_currency,
        "consumer_system": consumer_system,
        "dimensions": dimensions,
        "include_cash_flows": include_cash_flows,
        "filters": filters,
        "page_token": page_token,
    }


def _performance_component_economics_request_payload(
    *,
    portfolio_id: str,
    chunk: DateChunk,
    security_ids: list[str] | None,
    transaction_types: list[str] | None,
) -> dict[str, Any]:
    return {
        "portfolio_id": portfolio_id,
        "start_date": str(chunk.start_date),
        "end_date": str(chunk.end_date),
        "security_ids": sorted(set(security_ids or [])),
        "transaction_types": sorted(set(transaction_types or [])),
    }


def _build_performance_component_economics_chunk_payload(
    *,
    accumulator: _PerformanceComponentEconomicsAccumulator,
    portfolio_id: str,
    as_of_date: date,
    chunk: DateChunk,
) -> dict[str, Any]:
    state, reason = _performance_component_economics_chunk_state_reason(accumulator)
    return {
        "product_name": "PerformanceComponentEconomics",
        "product_version": "v1",
        "portfolio_id": portfolio_id,
        "as_of_date": str(as_of_date),
        "window": {"start_date": str(chunk.start_date), "end_date": str(chunk.end_date)},
        "rows": _dedup_performance_component_economics_rows(accumulator.rows),
        "component_totals": _merge_performance_component_economics_totals(accumulator.component_totals),
        "component_totals_scope": "consumed_pages",
        "lineage": _merge_performance_component_economics_lineage(accumulator.lineage_values),
        "request_fingerprints": sorted(set(accumulator.request_fingerprints)),
        "supportability": {
            "state": state,
            "reason": reason,
            "source_owner": "lotus-core",
            "downstream_consumer": "lotus-performance",
            "source_row_count": accumulator.source_row_count,
            "ready_chunk_count": 1 if state == "READY" else 0,
            "unavailable_chunk_count": 0 if state == "READY" else 1,
            "supported_component_families": sorted(accumulator.supported_component_families),
            "observed_component_families": sorted(accumulator.observed_component_families),
            "missing_component_families": _performance_component_economics_missing_families(accumulator),
        },
        "retrieval_metadata": {"page_count": accumulator.page_count},
    }


def _performance_component_economics_chunk_state_reason(
    accumulator: _PerformanceComponentEconomicsAccumulator,
) -> tuple[str, str]:
    if accumulator.source_row_count > 0:
        return "READY", "PERFORMANCE_COMPONENT_ECONOMICS_READY"
    return "UNAVAILABLE", "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE"


def _record_performance_component_economics_payload(
    *,
    accumulator: _PerformanceComponentEconomicsAccumulator,
    payload: dict[str, Any],
) -> None:
    accumulator.page_count += 1
    rows = _dict_list_payload_items_from_payload(payload, "rows")
    accumulator.rows.extend(rows)
    accumulator.component_totals.extend(_dict_list_payload_items_from_payload(payload, "component_totals"))
    lineage = payload.get("lineage")
    if isinstance(lineage, dict):
        accumulator.lineage_values.append(lineage)
    request_fingerprint = _string_or_none(payload.get("request_fingerprint"))
    if request_fingerprint is not None:
        accumulator.request_fingerprints.append(request_fingerprint)
    supportability = payload.get("supportability")
    if not isinstance(supportability, dict):
        accumulator.unavailable_chunk_count += 1
        return
    accumulator.source_row_count += len(rows)
    accumulator.observed_component_families.update(_string_list(supportability.get("observed_component_families")))
    accumulator.supported_component_families.update(_string_list(supportability.get("supported_component_families")))
    accumulator.missing_component_families.update(_string_list(supportability.get("missing_component_families")))


def _performance_component_economics_accumulator(
    responses: list[tuple[int, dict[str, Any]]],
) -> _PerformanceComponentEconomicsAccumulator:
    accumulator = _PerformanceComponentEconomicsAccumulator(
        observed_component_families=set(),
        supported_component_families=set(),
        missing_component_families=set(),
    )
    for status_code, payload in responses:
        if status_code != 200:
            accumulator.unavailable_chunk_count += 1
            continue
        supportability = payload.get("supportability")
        if not isinstance(supportability, dict):
            accumulator.unavailable_chunk_count += 1
            continue
        is_ready = supportability.get("state") == "READY"
        if is_ready:
            accumulator.ready_chunk_count += 1
            accumulator.source_row_count += _non_negative_int(supportability.get("source_row_count"))
            accumulator.observed_component_families.update(
                _string_list(supportability.get("observed_component_families"))
            )
        else:
            accumulator.unavailable_chunk_count += 1
        accumulator.supported_component_families.update(
            _string_list(supportability.get("supported_component_families"))
        )
        accumulator.missing_component_families.update(_string_list(supportability.get("missing_component_families")))
        accumulator.rows.extend(_dict_list_payload_items_from_payload(payload, "rows"))
        accumulator.component_totals.extend(_dict_list_payload_items_from_payload(payload, "component_totals"))
        accumulator.page_count += _retrieval_page_count(payload)
    return accumulator


def _performance_component_economics_supportability(
    *,
    accumulator: _PerformanceComponentEconomicsAccumulator,
    chunk_count: int,
) -> dict[str, Any]:
    state, reason = _performance_component_economics_supportability_state_reason(
        accumulator=accumulator,
        chunk_count=chunk_count,
    )
    return {
        "state": state,
        "reason": reason,
        "source_owner": "lotus-core",
        "downstream_consumer": "lotus-performance",
        "source_row_count": accumulator.source_row_count,
        "ready_chunk_count": accumulator.ready_chunk_count,
        "unavailable_chunk_count": accumulator.unavailable_chunk_count,
        "supported_component_families": sorted(accumulator.supported_component_families),
        "observed_component_families": sorted(accumulator.observed_component_families),
        "missing_component_families": _performance_component_economics_missing_families(accumulator),
    }


def _performance_component_economics_supportability_state_reason(
    *,
    accumulator: _PerformanceComponentEconomicsAccumulator,
    chunk_count: int,
) -> tuple[str, str]:
    if chunk_count > 0 and accumulator.ready_chunk_count == chunk_count:
        return "READY", "PERFORMANCE_COMPONENT_ECONOMICS_READY"
    if accumulator.ready_chunk_count > 0:
        return "UNAVAILABLE", "PERFORMANCE_COMPONENT_ECONOMICS_PARTIAL"
    return "UNAVAILABLE", "PERFORMANCE_COMPONENT_ECONOMICS_UNAVAILABLE"


def _performance_component_economics_missing_families(
    accumulator: _PerformanceComponentEconomicsAccumulator,
) -> list[str]:
    if accumulator.supported_component_families:
        return sorted(accumulator.supported_component_families - accumulator.observed_component_families)
    return sorted(accumulator.missing_component_families)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _non_negative_int(value: Any) -> int:
    if type(value) is int and value > 0:
        return value
    return 0


def _performance_component_economics_rows_from_responses(
    responses: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [
        row
        for status_code, payload in responses
        if status_code == 200
        for row in _dict_list_payload_items_from_payload(payload, "rows")
    ]


def _performance_component_economics_component_totals_from_responses(
    responses: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    return _merge_performance_component_economics_totals(
        [
            total
            for status_code, payload in responses
            if status_code == 200
            for total in _dict_list_payload_items_from_payload(payload, "component_totals")
        ]
    )


def _performance_component_economics_lineage_from_responses(
    responses: list[tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    lineage_values = [
        payload["lineage"]
        for status_code, payload in responses
        if status_code == 200 and isinstance(payload.get("lineage"), dict)
    ]
    return _merge_performance_component_economics_lineage(lineage_values)


def _merge_performance_component_economics_lineage(lineage_values: list[dict[str, Any]]) -> dict[str, Any]:
    if not lineage_values:
        return {}
    merged: dict[str, set[str]] = {}
    for lineage in lineage_values:
        for key, value in _lineage_string_items(lineage):
            merged.setdefault(key, set()).add(value)
    return {key: ",".join(sorted(values)) for key, values in sorted(merged.items())}


def _lineage_string_items(lineage: dict[str, Any]) -> list[tuple[str, str]]:
    return [(key, value) for key, value in lineage.items() if isinstance(key, str) and isinstance(value, str) and value]


def _performance_component_economics_request_fingerprints(
    responses: list[tuple[int, dict[str, Any]]],
) -> list[str]:
    return sorted(
        {
            fingerprint
            for status_code, payload in responses
            if status_code == 200
            for fingerprint in [
                *_string_list(payload.get("request_fingerprints")),
                *[_string_or_none(payload.get("request_fingerprint"))],
            ]
            if fingerprint is not None
        }
    )


def _dedup_performance_component_economics_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _performance_component_economics_row_key(row)
        if key is not None:
            deduped[key] = row
    return [deduped[key] for key in sorted(deduped)]


def _performance_component_economics_row_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    security_id = _string_or_none(row.get("security_id"))
    transaction_date = _string_or_none(row.get("transaction_date"))
    transaction_id = _string_or_none(row.get("transaction_id"))
    if security_id is None or transaction_date is None or transaction_id is None:
        return None
    return security_id, transaction_date, transaction_id


def _merge_performance_component_economics_totals(totals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for total in totals:
        family = _string_or_none(total.get("component_family"))
        currency = _string_or_none(total.get("currency"))
        amount = _decimal_or_none(total.get("amount"))
        if family is None or currency is None or amount is None:
            continue
        key = (family, currency)
        current = grouped.setdefault(
            key,
            {"component_family": family, "currency": currency, "amount": Decimal("0"), "evidence_count": 0},
        )
        current["amount"] += amount
        current["evidence_count"] += _non_negative_int(total.get("evidence_count"))
    return [
        {
            "component_family": total["component_family"],
            "currency": total["currency"],
            "amount": str(total["amount"]),
            "evidence_count": total["evidence_count"],
        }
        for _, total in sorted(grouped.items())
    ]


def _dict_list_payload_items_from_payload(payload: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    items = payload.get(field_name, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _position_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []
    return _position_rows_with_source_keys(rows)


def _position_rows_from_responses(responses: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for _, payload in responses for row in _position_rows_from_payload(payload)]


def _position_rows_with_source_keys(rows: list[Any]) -> list[dict[str, Any]]:
    return [_position_row_with_source_key(row) for row in rows if isinstance(row, dict)]


def _position_row_with_source_key(row: dict[str, Any]) -> dict[str, Any]:
    source_position_key = _source_position_key(row)
    if source_position_key is None or row.get("source_position_key") == source_position_key:
        return row
    return {**row, "source_position_key": source_position_key}


def _source_position_key(row: dict[str, Any]) -> str | None:
    explicit_source_key = row.get("source_position_key")
    if _non_empty_string(explicit_source_key):
        return explicit_source_key
    position_grain_id = row.get("position_grain_id")
    if _non_empty_string(position_grain_id):
        return position_grain_id
    position_id = row.get("position_id")
    if not _non_empty_string(position_id):
        return None
    grain_parts = [
        f"{field}={value}" for field in POSITION_SOURCE_GRAIN_FIELDS if _non_empty_string(value := row.get(field))
    ]
    if not grain_parts:
        return position_id
    return "|".join([f"position_id={position_id}", *grain_parts])


def _record_position_chunk_payload(
    *,
    accumulator: _PositionChunkAccumulator,
    payload: dict[str, Any],
) -> None:
    accumulator.rows.extend(_position_rows_from_payload(payload))
    accumulator.page_count += 1


def _component_index_points(component: Any) -> tuple[str, list[dict[str, Any]]] | None:
    if not isinstance(component, dict):
        return None
    index_id = _component_index_id(component)
    if index_id is None:
        return None
    return index_id, _component_point_records(component)


def _component_index_id(component: dict[str, Any]) -> str | None:
    index_id = component.get("index_id")
    if not isinstance(index_id, str):
        return None
    return index_id


def _component_point_records(component: dict[str, Any]) -> list[dict[str, Any]]:
    points_raw = component.get("points")
    if not isinstance(points_raw, list):
        return []
    return [point for point in points_raw if isinstance(point, dict)]


def _non_empty_string(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _record_key_by_fields(*, record: dict[str, Any], key_fields: tuple[str, ...]) -> tuple[str, ...] | None:
    key_values: list[str] = []
    for field in key_fields:
        value = record.get(field)
        if not isinstance(value, str):
            return None
        key_values.append(value)
    return tuple(key_values)


def _portfolio_identity_from_payload(
    *,
    payload: dict[str, Any],
    portfolio_open_date: str | None,
    portfolio_currency: str | None,
    reporting_currency: str | None,
) -> tuple[str | None, str | None, str | None]:
    return (
        _payload_string_identity_value(
            payload=payload,
            field_name="portfolio_open_date",
            current_value=portfolio_open_date,
        ),
        _payload_string_identity_value(
            payload=payload,
            field_name="portfolio_currency",
            current_value=portfolio_currency,
        ),
        _payload_string_identity_value(
            payload=payload,
            field_name="reporting_currency",
            current_value=reporting_currency,
        ),
    )


def _record_portfolio_chunk_payload(
    *,
    accumulator: _PortfolioChunkAccumulator,
    payload: dict[str, Any],
) -> None:
    (
        accumulator.portfolio_open_date,
        accumulator.portfolio_currency,
        accumulator.reporting_currency,
    ) = _portfolio_identity_from_payload(
        payload=payload,
        portfolio_open_date=accumulator.portfolio_open_date,
        portfolio_currency=accumulator.portfolio_currency,
        reporting_currency=accumulator.reporting_currency,
    )
    accumulator.observations.extend(_portfolio_observations_from_payload(payload))
    accumulator.page_count += 1


def _payload_string_identity_value(
    *,
    payload: dict[str, Any],
    field_name: str,
    current_value: str | None,
) -> str | None:
    if current_value is not None:
        return current_value
    payload_value = payload.get(field_name)
    if isinstance(payload_value, str):
        return payload_value
    return None


def _portfolio_observations_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    observations = payload.get("observations", [])
    if not isinstance(observations, list):
        return []
    return [observation for observation in observations if isinstance(observation, dict)]


def _string_payload_values(
    *,
    responses: list[tuple[int, dict[str, Any]]],
    field_name: str,
) -> list[str]:
    return [value for _, payload in responses if isinstance((value := payload.get(field_name)), str)]


def _dict_list_payload_items(
    *,
    responses: list[tuple[int, dict[str, Any]]],
    field_name: str,
) -> list[dict[str, Any]]:
    return [
        item
        for _, payload in responses
        for item in (payload.get(field_name, []) if isinstance(payload.get(field_name), list) else [])
        if isinstance(item, dict)
    ]


def _retrieval_page_count(payload: dict[str, Any]) -> int:
    metadata = payload.get("retrieval_metadata")
    if not isinstance(metadata, dict):
        return 0
    return int(metadata.get("page_count", 0) or 0)
