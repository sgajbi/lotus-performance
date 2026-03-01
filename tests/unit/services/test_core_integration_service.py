from datetime import date

import httpx
import pytest

from app.services.core_integration_service import CoreIntegrationService


class _FakeAsyncClient:
    responses: list[httpx.Response] = []
    calls: list[dict] = []

    def __init__(self, timeout: float):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json or {}, "headers": headers or {}})
        if not self.responses:
            raise AssertionError("No queued response available.")
        response = self.responses.pop(0)
        if response.request is None:
            response.request = httpx.Request("POST", url)  # type: ignore[misc]
        return response

    @classmethod
    def queue_json(cls, status_code: int, payload):
        cls.responses.append(
            httpx.Response(
                status_code=status_code,
                json=payload,
                request=httpx.Request("POST", "http://test"),
            )
        )


@pytest.fixture(autouse=True)
def _patch_async_client(monkeypatch):
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr("app.services.http_resilience.httpx.AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_get_portfolio_analytics_timeseries_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"observations": []})

    status_code, payload = await service.get_portfolio_analytics_timeseries(
        portfolio_id="PORT-1",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
        reporting_currency="USD",
        consumer_system="lotus-performance",
    )

    assert status_code == 200
    assert payload["observations"] == []
    assert (
        _FakeAsyncClient.calls[0]["url"] == "http://core/integration/portfolios/PORT-1/analytics/portfolio-timeseries"
    )
    assert _FakeAsyncClient.calls[0]["json"]["window"]["start_date"] == "2026-01-01"
    assert _FakeAsyncClient.calls[0]["json"]["window"]["end_date"] == "2026-02-24"
    assert _FakeAsyncClient.calls[0]["json"]["consumer_system"] == "lotus-performance"


@pytest.mark.asyncio
async def test_get_benchmark_assignment_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"benchmark_id": "BMK_1"})

    status_code, payload = await service.get_benchmark_assignment(
        portfolio_id="PORT-5",
        as_of_date=date(2026, 2, 24),
        reporting_currency="USD",
    )

    assert status_code == 200
    assert payload["benchmark_id"] == "BMK_1"
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/portfolios/PORT-5/benchmark-assignment"
    assert _FakeAsyncClient.calls[0]["json"]["reporting_currency"] == "USD"


@pytest.mark.asyncio
async def test_get_benchmark_return_series_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"points": []})

    status_code, payload = await service.get_benchmark_return_series(
        benchmark_id="BMK_2",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["points"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/benchmarks/BMK_2/return-series"


@pytest.mark.asyncio
async def test_get_risk_free_series_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"points": []})

    status_code, payload = await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["points"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/reference/risk-free-series"
