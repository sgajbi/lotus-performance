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
async def test_get_position_analytics_timeseries_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"rows": []})

    status_code, payload = await service.get_position_analytics_timeseries(
        portfolio_id="PORT-6",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
        reporting_currency="USD",
        consumer_system="lotus-performance",
        dimensions=["sector"],
        include_cash_flows=False,
        filters={"security_ids": ["SEC_1"]},
        page_size=123,
        page_token="next-page",
    )

    assert status_code == 200
    assert payload["rows"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/portfolios/PORT-6/analytics/position-timeseries"
    assert _FakeAsyncClient.calls[0]["json"]["dimensions"] == ["sector"]
    assert _FakeAsyncClient.calls[0]["json"]["include_cash_flows"] is False
    assert _FakeAsyncClient.calls[0]["json"]["filters"] == {"security_ids": ["SEC_1"]}
    assert _FakeAsyncClient.calls[0]["json"]["page"] == {"page_size": 123, "page_token": "next-page"}


@pytest.mark.asyncio
async def test_get_benchmark_definition_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"benchmark_id": "BMK_2"})

    status_code, payload = await service.get_benchmark_definition(
        benchmark_id="BMK_2",
        as_of_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["benchmark_id"] == "BMK_2"
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/benchmarks/BMK_2/definition"
    assert _FakeAsyncClient.calls[0]["json"] == {"as_of_date": "2026-02-24"}


@pytest.mark.asyncio
async def test_get_benchmark_market_series_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"component_series": []})

    status_code, payload = await service.get_benchmark_market_series(
        benchmark_id="BMK_3",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
        target_currency="USD",
        series_fields=["index_return", "component_weight", "fx_return"],
    )

    assert status_code == 200
    assert payload["component_series"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/benchmarks/BMK_3/market-series"
    assert _FakeAsyncClient.calls[0]["json"]["target_currency"] == "USD"
    assert _FakeAsyncClient.calls[0]["json"]["series_fields"] == ["index_return", "component_weight", "fx_return"]


@pytest.mark.asyncio
async def test_get_index_catalog_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"records": []})

    status_code, payload = await service.get_index_catalog(
        as_of_date=date(2026, 2, 24),
        index_currency="USD",
        index_type="BENCHMARK",
        index_status="ACTIVE",
    )

    assert status_code == 200
    assert payload["records"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/indices/catalog"
    assert _FakeAsyncClient.calls[0]["json"] == {
        "as_of_date": "2026-02-24",
        "index_currency": "USD",
        "index_type": "BENCHMARK",
        "index_status": "ACTIVE",
    }


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
