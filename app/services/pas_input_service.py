from datetime import date
from typing import Any

import httpx

from app.observability import propagation_headers
from app.services.http_resilience import post_with_retry, response_payload


class PasInputService:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.2,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    async def get_core_snapshot(
        self,
        portfolio_id: str,
        as_of_date: date,
        include_sections: list[str],
        consumer_system: str,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/portfolios/{portfolio_id}/core-snapshot"
        payload = {
            "as_of_date": str(as_of_date),
            "include_sections": include_sections,
            "consumer_system": consumer_system,
        }
        headers = propagation_headers()
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=headers,
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    def _response_payload(self, response: httpx.Response) -> dict[str, Any]:
        return response_payload(response)

    async def get_performance_input(
        self,
        portfolio_id: str,
        as_of_date: date,
        lookback_days: int,
        consumer_system: str,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/portfolios/{portfolio_id}/performance-input"
        payload = {
            "as_of_date": str(as_of_date),
            "lookback_days": lookback_days,
            "consumer_system": consumer_system,
        }
        headers = propagation_headers()
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=headers,
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    async def get_positions_analytics(
        self,
        portfolio_id: str,
        as_of_date: date,
        sections: list[str],
        performance_periods: list[str] | None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/portfolios/{portfolio_id}/positions-analytics"
        payload: dict[str, Any] = {"as_of_date": str(as_of_date), "sections": sections}
        if performance_periods:
            payload["performance_options"] = {"periods": performance_periods}
        headers = propagation_headers()
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=headers,
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    async def get_benchmark_assignment(
        self,
        portfolio_id: str,
        as_of_date: date,
        reporting_currency: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/portfolios/{portfolio_id}/benchmark-assignment"
        payload: dict[str, Any] = {"as_of_date": str(as_of_date)}
        if reporting_currency:
            payload["reporting_currency"] = reporting_currency
        headers = propagation_headers()
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=headers,
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    async def get_benchmark_return_series(
        self,
        benchmark_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/benchmarks/{benchmark_id}/return-series"
        payload = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        headers = propagation_headers()
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=headers,
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    async def get_risk_free_series(
        self,
        currency: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        *,
        frequency: str = "daily",
        series_mode: str = "return_series",
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/reference/risk-free-series"
        payload = {
            "currency": currency,
            "series_mode": series_mode,
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        headers = propagation_headers()
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=headers,
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )
