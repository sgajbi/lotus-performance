from datetime import date
from typing import Any

from app.observability import propagation_headers
from app.services.http_resilience import get_with_retry, post_with_retry


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

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def _post_json(self, *, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return await post_with_retry(
            url=self._url(path),
            timeout_seconds=self._timeout,
            json_body=payload,
            headers=propagation_headers(),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

    async def _get_json(self, *, path: str, query_params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return await get_with_retry(
            url=self._url(path),
            timeout_seconds=self._timeout,
            query_params=query_params,
            headers=propagation_headers(),
            max_retries=self._max_retries,
            backoff_seconds=self._retry_backoff_seconds,
        )

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
        payload: dict[str, Any] = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": "daily",
            "consumer_system": consumer_system,
            "page": {"page_size": page_size, "page_token": page_token},
        }
        if reporting_currency:
            payload["reporting_currency"] = reporting_currency
        return await self._post_json(
            path=f"/integration/portfolios/{portfolio_id}/analytics/portfolio-timeseries",
            payload=payload,
        )

    async def get_position_analytics_timeseries(
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
        page_size: int = 5000,
        page_token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": "daily",
            "dimensions": dimensions or [],
            "include_cash_flows": include_cash_flows,
            "consumer_system": consumer_system,
            "filters": filters or {},
            "page": {"page_size": page_size, "page_token": page_token},
        }
        if reporting_currency:
            payload["reporting_currency"] = reporting_currency
        return await self._post_json(
            path=f"/integration/portfolios/{portfolio_id}/analytics/position-timeseries",
            payload=payload,
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
        page_size: int = 5000,
        page_token: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "page": {"page_size": page_size, "page_token": page_token},
        }
        if security_ids:
            payload["security_ids"] = security_ids
        if transaction_types:
            payload["transaction_types"] = transaction_types
        return await self._post_json(
            path=f"/integration/portfolios/{portfolio_id}/performance-component-economics",
            payload=payload,
        )

    async def get_benchmark_assignment(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
        reporting_currency: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {"as_of_date": str(as_of_date)}
        if reporting_currency:
            payload["reporting_currency"] = reporting_currency
        return await self._post_json(
            path=f"/integration/portfolios/{portfolio_id}/benchmark-assignment",
            payload=payload,
        )

    async def get_portfolio_analytics_reference(
        self,
        *,
        portfolio_id: str,
        as_of_date: date,
    ) -> tuple[int, dict[str, Any]]:
        payload = {"as_of_date": str(as_of_date)}
        return await self._post_json(
            path=f"/integration/portfolios/{portfolio_id}/analytics/reference",
            payload=payload,
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
        payload = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        return await self._post_json(
            path=f"/integration/benchmarks/{benchmark_id}/return-series",
            payload=payload,
        )

    async def get_benchmark_definition(
        self,
        *,
        benchmark_id: str,
        as_of_date: date,
    ) -> tuple[int, dict[str, Any]]:
        payload = {"as_of_date": str(as_of_date)}
        return await self._post_json(
            path=f"/integration/benchmarks/{benchmark_id}/definition",
            payload=payload,
        )

    async def get_benchmark_composition_window(
        self,
        *,
        benchmark_id: str,
        start_date: date,
        end_date: date,
    ) -> tuple[int, dict[str, Any]]:
        payload = {
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
        }
        return await self._post_json(
            path=f"/integration/benchmarks/{benchmark_id}/composition-window",
            payload=payload,
        )

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
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
            "series_fields": series_fields or ["index_return", "component_weight"],
        }
        if target_currency:
            payload["target_currency"] = target_currency
        return await self._post_json(
            path=f"/integration/benchmarks/{benchmark_id}/market-series",
            payload=payload,
        )

    async def get_fx_rates(
        self,
        *,
        from_currency: str,
        to_currency: str,
        start_date: date,
        end_date: date,
    ) -> tuple[int, dict[str, Any]]:
        query_params = {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "start_date": str(start_date),
            "end_date": str(end_date),
        }
        return await self._get_json(
            path="/fx-rates/",
            query_params=query_params,
        )

    async def get_index_catalog(
        self,
        *,
        as_of_date: date,
        index_ids: list[str] | None = None,
        index_currency: str | None = None,
        index_type: str | None = None,
        index_status: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {"as_of_date": str(as_of_date)}
        payload.update(
            _index_catalog_filter_payload(
                index_ids=index_ids,
                index_currency=index_currency,
                index_type=index_type,
                index_status=index_status,
            )
        )
        return await self._post_json(
            path="/integration/indices/catalog",
            payload=payload,
        )

    async def get_index_price_series(
        self,
        *,
        index_id: str,
        as_of_date: date,
        start_date: date,
        end_date: date,
        frequency: str = "daily",
        target_currency: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        if target_currency:
            payload["target_currency"] = target_currency
        return await self._post_json(
            path=f"/integration/indices/{index_id}/price-series",
            payload=payload,
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
        payload = {
            "currency": currency,
            "series_mode": series_mode,
            "as_of_date": str(as_of_date),
            "window": {"start_date": str(start_date), "end_date": str(end_date)},
            "frequency": frequency,
        }
        return await self._post_json(
            path="/integration/reference/risk-free-series",
            payload=payload,
        )


def _index_catalog_filter_payload(
    *,
    index_ids: list[str] | None,
    index_currency: str | None,
    index_type: str | None,
    index_status: str | None,
) -> dict[str, Any]:
    filter_values: tuple[tuple[str, Any], ...] = (
        ("index_ids", index_ids),
        ("index_currency", index_currency),
        ("index_type", index_type),
        ("index_status", index_status),
    )
    return {field_name: value for field_name, value in filter_values if value}
