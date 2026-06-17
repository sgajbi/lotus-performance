from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.services.core_integration_service import CoreIntegrationService
from app.services.execution_registry import ExecutionRegistry, execution_registry


@dataclass(frozen=True)
class DateChunk:
    start_date: date
    end_date: date


@dataclass(frozen=True)
class RetrievalMetadata:
    chunk_count: int
    page_count: int


class StatefulInputService:
    def __init__(
        self,
        *,
        core_service: CoreIntegrationService,
        execution_store: ExecutionRegistry | None = None,
        portfolio_chunk_days: int = 90,
        reference_chunk_days: int = 365,
        max_concurrent_chunks: int = 4,
    ) -> None:
        self._core_service = core_service
        self._execution_store = execution_store or execution_registry
        self._portfolio_chunk_days = max(1, portfolio_chunk_days)
        self._reference_chunk_days = max(1, reference_chunk_days)
        self._max_concurrent_chunks = max(1, max_concurrent_chunks)
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
        response = await self._core_service.get_portfolio_analytics_reference(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )
        if calculation_id is not None:
            request_payload = {
                "portfolio_id": portfolio_id,
                "as_of_date": str(as_of_date),
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="portfolio_reference",
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
                            upstream_endpoint="portfolio_reference",
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
        response = await self._core_service.get_benchmark_definition(
            benchmark_id=benchmark_id,
            as_of_date=as_of_date,
        )
        if calculation_id is not None:
            request_payload = {
                "benchmark_id": benchmark_id,
                "as_of_date": str(as_of_date),
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="benchmark_definition",
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
                            upstream_endpoint="benchmark_definition",
                            source_identifier=benchmark_id,
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
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._core_service.get_benchmark_market_series(
                benchmark_id=benchmark_id,
                as_of_date=as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                frequency=frequency,
                target_currency=target_currency,
                series_fields=series_fields or ["index_return", "component_weight"],
            ),
        )
        self._record_benchmark_market_series_snapshots(
            calculation_id=calculation_id,
            benchmark_id=benchmark_id,
            as_of_date=as_of_date,
            frequency=frequency,
            target_currency=target_currency,
            series_fields=series_fields,
            chunks=chunks,
            responses=responses,
            existing_snapshot_ids=existing_snapshot_ids,
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

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
        benchmark_id: str,
        as_of_date: date,
        frequency: str,
        target_currency: str | None,
        series_fields: list[str] | None,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        resolved_series_fields = series_fields or ["index_return", "component_weight"]
        for chunk, response in zip(chunks, responses):
            request_payload = {
                "benchmark_id": benchmark_id,
                "start_date": str(chunk.start_date),
                "end_date": str(chunk.end_date),
                "frequency": frequency,
                "target_currency": target_currency,
                "series_fields": resolved_series_fields,
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="benchmark_market_series",
                source_identifier=benchmark_id,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="benchmark_market_series",
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

        merged_rates = self._merge_dedup_records(
            records=[
                {"series_date": rate.get("rate_date"), "fx_rate": rate.get("rate")}
                for _, payload in responses
                for rate in (payload.get("rates", []) if isinstance(payload, dict) else [])
                if isinstance(rate, dict)
            ],
            date_key="series_date",
        )
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
        if calculation_id is not None:
            sorted_index_ids = sorted(set(index_ids or []))
            request_payload = {
                "as_of_date": str(as_of_date),
                "index_ids": sorted_index_ids,
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="index_catalog",
                source_identifier="|".join(sorted_index_ids) if sorted_index_ids else "all_indices",
                request_payload=request_payload,
            )
            existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
            if snapshot_id not in existing_snapshot_ids:
                self._execution_store.record_upstream_snapshots(
                    calculation_id=calculation_id,
                    snapshots=[
                        self._build_snapshot(
                            calculation_id=calculation_id,
                            upstream_endpoint="index_catalog",
                            source_identifier="|".join(sorted_index_ids) if sorted_index_ids else "all_indices",
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
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._core_service.get_index_price_series(
                index_id=index_id,
                as_of_date=as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                frequency=frequency,
                target_currency=target_currency,
            ),
        )
        self._record_index_price_series_snapshots(
            calculation_id=calculation_id,
            index_id=index_id,
            as_of_date=as_of_date,
            frequency=frequency,
            target_currency=target_currency,
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

    def _record_index_price_series_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        index_id: str,
        as_of_date: date,
        frequency: str,
        target_currency: str | None,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        for chunk, response in zip(chunks, responses):
            request_payload = {
                "index_id": index_id,
                "start_date": str(chunk.start_date),
                "end_date": str(chunk.end_date),
                "frequency": frequency,
                "target_currency": target_currency,
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="index_price_series",
                source_identifier=index_id,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="index_price_series",
                    source_identifier=index_id,
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
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        chunks = self.plan_chunks(
            start_date=start_date,
            end_date=end_date,
            chunk_days=self._reference_chunk_days,
        )
        responses = await self._gather_chunked(
            chunks=chunks,
            fetcher=lambda chunk: self._core_service.get_risk_free_series(
                currency=currency,
                as_of_date=as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                frequency=frequency,
                series_mode=series_mode,
            ),
        )
        self._record_risk_free_series_snapshots(
            calculation_id=calculation_id,
            currency=currency,
            as_of_date=as_of_date,
            frequency=frequency,
            series_mode=series_mode,
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

    def _record_risk_free_series_snapshots(
        self,
        *,
        calculation_id: UUID | None,
        currency: str,
        as_of_date: date,
        frequency: str,
        series_mode: str,
        chunks: list[DateChunk],
        responses: list[tuple[int, dict[str, Any]]],
        existing_snapshot_ids: set[str],
    ) -> None:
        if calculation_id is None:
            return
        snapshot_batch: list[dict[str, Any]] = []
        for chunk, response in zip(chunks, responses):
            request_payload = {
                "currency": currency,
                "start_date": str(chunk.start_date),
                "end_date": str(chunk.end_date),
                "frequency": frequency,
                "series_mode": series_mode,
            }
            snapshot_id, request_fingerprint = self._build_snapshot_identity(
                calculation_id=calculation_id,
                upstream_endpoint="risk_free_series",
                source_identifier=currency,
                request_payload=request_payload,
            )
            if snapshot_id in existing_snapshot_ids:
                continue
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="risk_free_series",
                    source_identifier=currency,
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
        merged_observations: list[dict[str, Any]] = []
        portfolio_open_date: str | None = None
        portfolio_currency: str | None = None
        effective_reporting_currency: str | None = None
        snapshot_batch: list[dict[str, Any]] = []
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        page_count = 0

        while True:
            status_code, payload = await self._core_service.get_portfolio_analytics_timeseries(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                reporting_currency=reporting_currency,
                consumer_system=consumer_system,
                page_token=page_token,
            )
            request_payload = _portfolio_timeseries_request_payload(
                portfolio_id=portfolio_id,
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
            page_count += 1

            portfolio_open_date, portfolio_currency, effective_reporting_currency = _portfolio_identity_from_payload(
                payload=payload,
                portfolio_open_date=portfolio_open_date,
                portfolio_currency=portfolio_currency,
                reporting_currency=effective_reporting_currency,
            )
            merged_observations.extend(_portfolio_observations_from_payload(payload))

            page_token = self._next_page_token(payload)
            if not page_token:
                break

        self._record_upstream_snapshot_batch(
            calculation_id=calculation_id,
            snapshots=snapshot_batch,
        )

        return 200, {
            "portfolio_open_date": portfolio_open_date,
            "portfolio_currency": portfolio_currency,
            "reporting_currency": effective_reporting_currency,
            "observations": self._merge_dedup_records(records=merged_observations, date_key="valuation_date"),
            "retrieval_metadata": {
                "page_count": page_count,
            },
        }

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
        if calculation_id is None:
            return
        snapshot_id, request_fingerprint = self._build_snapshot_identity(
            calculation_id=calculation_id,
            upstream_endpoint="portfolio_timeseries",
            source_identifier=portfolio_id,
            request_payload=request_payload,
        )
        if snapshot_id not in existing_snapshot_ids:
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="portfolio_timeseries",
                    source_identifier=portfolio_id,
                    as_of_date=as_of_date,
                    request_payload=request_payload,
                    response=response,
                    snapshot_id=snapshot_id,
                    request_fingerprint=request_fingerprint,
                )
            )
            existing_snapshot_ids.add(snapshot_id)

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
        merged_rows: list[dict[str, Any]] = []
        snapshot_batch: list[dict[str, Any]] = []
        existing_snapshot_ids = self._existing_snapshot_ids(calculation_id)
        page_count = 0

        while True:
            status_code, payload = await self._core_service.get_position_analytics_timeseries(
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
            request_payload = _position_timeseries_request_payload(
                portfolio_id=portfolio_id,
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
            if status_code >= 400:
                if calculation_id is not None:
                    self._execution_store.record_upstream_snapshots(
                        calculation_id=calculation_id,
                        snapshots=snapshot_batch,
                    )
                return status_code, payload
            page_count += 1

            merged_rows.extend(_position_rows_from_payload(payload))

            page_token = self._next_page_token(payload)
            if not page_token:
                break

        if calculation_id is not None:
            self._execution_store.record_upstream_snapshots(
                calculation_id=calculation_id,
                snapshots=snapshot_batch,
            )

        return 200, {
            "rows": self._merge_dedup_records_by_fields(
                records=merged_rows,
                key_fields=("valuation_date", "position_id"),
            ),
            "retrieval_metadata": {
                "page_count": page_count,
            },
        }

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
        if calculation_id is None:
            return
        snapshot_id, request_fingerprint = self._build_snapshot_identity(
            calculation_id=calculation_id,
            upstream_endpoint="position_timeseries",
            source_identifier=portfolio_id,
            request_payload=request_payload,
        )
        if snapshot_id not in existing_snapshot_ids:
            snapshot_batch.append(
                self._build_snapshot(
                    calculation_id=calculation_id,
                    upstream_endpoint="position_timeseries",
                    source_identifier=portfolio_id,
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
                records=_dict_list_payload_items(responses=responses, field_name="rows"),
                key_fields=("valuation_date", "position_id"),
            ),
            "retrieval_metadata": {
                "chunk_count": chunk_count,
                "page_count": self._total_retrieval_page_count(responses),
            },
        }

    def _next_page_token(self, payload: dict[str, Any]) -> str | None:
        next_page_token = payload.get("next_page_token")
        if isinstance(next_page_token, str) and next_page_token:
            return next_page_token
        page_block = payload.get("page")
        if isinstance(page_block, dict):
            nested_token = page_block.get("next_page_token")
            if isinstance(nested_token, str) and nested_token:
                return nested_token
        return None

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

    def _merge_dedup_records_by_fields(
        self,
        *,
        records: list[dict[str, Any]],
        key_fields: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        deduped: dict[tuple[str, ...], dict[str, Any]] = {}
        for record in records:
            key_values: list[str] = []
            for field in key_fields:
                value = record.get(field)
                if not isinstance(value, str):
                    break
                key_values.append(value)
            if len(key_values) != len(key_fields):
                continue
            deduped[tuple(key_values)] = record
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


def _position_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _component_index_points(component: Any) -> tuple[str, list[dict[str, Any]]] | None:
    if not isinstance(component, dict):
        return None
    index_id = component.get("index_id")
    if not isinstance(index_id, str):
        return None
    points_raw = component.get("points")
    if not isinstance(points_raw, list):
        return index_id, []
    return index_id, [point for point in points_raw if isinstance(point, dict)]


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
