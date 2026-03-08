from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from app.services.core_integration_service import CoreIntegrationService


@dataclass(frozen=True)
class DateChunk:
    start_date: date
    end_date: date


class StatefulInputService:
    def __init__(
        self,
        *,
        core_service: CoreIntegrationService,
        portfolio_chunk_days: int = 90,
        reference_chunk_days: int = 365,
        max_concurrent_chunks: int = 4,
    ) -> None:
        self._core_service = core_service
        self._portfolio_chunk_days = max(1, portfolio_chunk_days)
        self._reference_chunk_days = max(1, reference_chunk_days)
        self._max_concurrent_chunks = max(1, max_concurrent_chunks)

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
            ),
        )
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        open_dates = [
            payload["portfolio_open_date"]
            for _, payload in responses
            if isinstance(payload, dict) and isinstance(payload.get("portfolio_open_date"), str)
        ]
        observations = self._merge_dedup_records(
            records=[
                obs
                for _, payload in responses
                for obs in (payload.get("observations", []) if isinstance(payload, dict) else [])
                if isinstance(obs, dict)
            ],
            date_key="valuation_date",
        )
        return 200, {
            "portfolio_open_date": min(open_dates) if open_dates else None,
            "observations": observations,
        }

    async def get_benchmark_assignment(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        reporting_currency: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return await self._core_service.get_benchmark_assignment(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            reporting_currency=reporting_currency,
        )

    async def get_benchmark_return_series(
        self,
        *,
        benchmark_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
    ) -> tuple[int, dict[str, Any]]:
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
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        points = self._merge_dedup_records(
            records=[
                point
                for _, payload in responses
                for point in (payload.get("points", []) if isinstance(payload, dict) else [])
                if isinstance(point, dict)
            ],
            date_key="series_date",
        )
        return 200, {"points": points}

    async def get_risk_free_series(
        self,
        *,
        currency: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
        series_mode: str = "return_series",
    ) -> tuple[int, dict[str, Any]]:
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
        failure = self._first_failure(responses)
        if failure is not None:
            return failure

        points = self._merge_dedup_records(
            records=[
                point
                for _, payload in responses
                for point in (payload.get("points", []) if isinstance(payload, dict) else [])
                if isinstance(point, dict)
            ],
            date_key="series_date",
        )
        return 200, {"points": points}

    async def _fetch_portfolio_chunk(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        chunk: DateChunk,
        reporting_currency: str | None,
        consumer_system: str,
    ) -> tuple[int, dict[str, Any]]:
        page_token: str | None = None
        merged_observations: list[dict[str, Any]] = []
        portfolio_open_date: str | None = None

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
            if status_code >= 400:
                return status_code, payload

            if portfolio_open_date is None and isinstance(payload.get("portfolio_open_date"), str):
                portfolio_open_date = payload["portfolio_open_date"]

            observations = payload.get("observations", [])
            if isinstance(observations, list):
                merged_observations.extend(obs for obs in observations if isinstance(obs, dict))

            page_token = self._next_page_token(payload)
            if not page_token:
                break

        return 200, {
            "portfolio_open_date": portfolio_open_date,
            "observations": self._merge_dedup_records(records=merged_observations, date_key="valuation_date"),
        }

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
