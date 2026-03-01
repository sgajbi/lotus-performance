from datetime import date
from typing import Any

from app.observability import propagation_headers
from app.services.http_resilience import post_with_retry


class CoreIntegrationService:
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

    async def get_portfolio_analytics_timeseries(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        reporting_currency: str | None,
        consumer_system: str,
        page_size: int = 5000,
        page_token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries"
        payload: dict[str, Any] = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": "daily",
            "consumer_system": consumer_system,
            "page": {"page_size": page_size, "page_token": page_token},
        }
        if reporting_currency:
            payload["reporting_currency"] = reporting_currency
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=propagation_headers(),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    async def get_benchmark_assignment(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        reporting_currency: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/portfolios/{portfolio_id}/benchmark-assignment"
        payload: dict[str, Any] = {"as_of_date": str(as_of_date)}
        if reporting_currency:
            payload["reporting_currency"] = reporting_currency
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=propagation_headers(),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
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
        url = f"{self._base_url}/integration/benchmarks/{benchmark_id}/return-series"
        payload = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=propagation_headers(),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
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
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/integration/reference/risk-free-series"
        payload = {
            "currency": currency,
            "series_mode": series_mode,
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        return await post_with_retry(
            url=url,
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=propagation_headers(),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )
