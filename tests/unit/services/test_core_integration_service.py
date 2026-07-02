from datetime import date

import httpx
import pytest

from app.services.core_integration_service import CoreIntegrationService, _index_catalog_filter_payload
from app.services.http_resilience import close_upstream_http_client_pool, configure_upstream_http_client_pool


class _FakeAsyncClient:
    responses: list[httpx.Response] = []
    calls: list[dict] = []
    instances: list["_FakeAsyncClient"] = []

    def __init__(self, timeout: float, limits=None):
        self.timeout = timeout
        self.limits = limits
        self.is_closed = False
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aclose(self):
        self.is_closed = True

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
    _FakeAsyncClient.instances = []
    monkeypatch.setattr("app.services.http_resilience.httpx.AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_core_service_reuses_managed_client_for_stateful_chunk_requests():
    service = CoreIntegrationService(base_url="http://core-control", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"observations": []})
    _FakeAsyncClient.queue_json(200, {"rows": []})
    configure_upstream_http_client_pool(
        max_connections=8,
        max_keepalive_connections=4,
        keepalive_expiry_seconds=20.0,
    )

    try:
        await service.get_portfolio_analytics_timeseries(
            portfolio_id="PORT-1",
            as_of_date=date(2026, 2, 24),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            reporting_currency="USD",
            consumer_system="lotus-performance",
            page_token=None,
        )
        await service.get_position_analytics_timeseries(
            portfolio_id="PORT-1",
            as_of_date=date(2026, 2, 24),
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 24),
            reporting_currency="USD",
            consumer_system="lotus-performance",
            page_token="page-2",
        )
    finally:
        await close_upstream_http_client_pool()

    assert len(_FakeAsyncClient.instances) == 1
    assert _FakeAsyncClient.instances[0].is_closed is True
    assert len(_FakeAsyncClient.calls) == 2


@pytest.mark.asyncio
async def test_get_portfolio_analytics_timeseries_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core-control", timeout_seconds=2.0)
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
        _FakeAsyncClient.calls[0]["url"]
        == "http://core-control/integration/portfolios/PORT-1/analytics/portfolio-timeseries"
    )
    assert _FakeAsyncClient.calls[0]["json"]["window"]["start_date"] == "2026-01-01"
    assert _FakeAsyncClient.calls[0]["json"]["window"]["end_date"] == "2026-02-24"
    assert _FakeAsyncClient.calls[0]["json"]["consumer_system"] == "lotus-performance"


@pytest.mark.asyncio
async def test_get_benchmark_assignment_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core-control", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"benchmark_id": "BMK_1"})

    status_code, payload = await service.get_benchmark_assignment(
        portfolio_id="PORT-5",
        as_of_date=date(2026, 2, 24),
        reporting_currency="USD",
    )

    assert status_code == 200
    assert payload["benchmark_id"] == "BMK_1"
    assert _FakeAsyncClient.calls[0]["url"] == "http://core-control/integration/portfolios/PORT-5/benchmark-assignment"
    assert _FakeAsyncClient.calls[0]["json"]["reporting_currency"] == "USD"


@pytest.mark.asyncio
async def test_get_portfolio_analytics_reference_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core-control", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"portfolio_open_date": "2024-01-01"})

    status_code, payload = await service.get_portfolio_analytics_reference(
        portfolio_id="PORT-REF",
        as_of_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["portfolio_open_date"] == "2024-01-01"
    assert _FakeAsyncClient.calls[0]["url"] == "http://core-control/integration/portfolios/PORT-REF/analytics/reference"
    assert _FakeAsyncClient.calls[0]["json"] == {"as_of_date": "2026-02-24"}


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
    service = CoreIntegrationService(base_url="http://core-control", timeout_seconds=2.0)
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
    assert (
        _FakeAsyncClient.calls[0]["url"]
        == "http://core-control/integration/portfolios/PORT-6/analytics/position-timeseries"
    )
    assert _FakeAsyncClient.calls[0]["json"]["dimensions"] == ["sector"]
    assert _FakeAsyncClient.calls[0]["json"]["include_cash_flows"] is False
    assert _FakeAsyncClient.calls[0]["json"]["filters"] == {"security_ids": ["SEC_1"]}
    assert _FakeAsyncClient.calls[0]["json"]["page"] == {"page_size": 123, "page_token": "next-page"}


@pytest.mark.asyncio
async def test_get_performance_component_economics_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core-control", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"product_name": "PerformanceComponentEconomics"})

    status_code, payload = await service.get_performance_component_economics(
        portfolio_id="PORT-6",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
        security_ids=["SEC_1"],
        transaction_types=["DIVIDEND"],
    )

    assert status_code == 200
    assert payload["product_name"] == "PerformanceComponentEconomics"
    assert (
        _FakeAsyncClient.calls[0]["url"]
        == "http://core-control/integration/portfolios/PORT-6/performance-component-economics"
    )
    assert _FakeAsyncClient.calls[0]["json"] == {
        "as_of_date": "2026-02-24",
        "window": {"start_date": "2026-01-01", "end_date": "2026-02-24"},
        "page": {"page_size": 1000, "page_token": None},
        "security_ids": ["SEC_1"],
        "transaction_types": ["DIVIDEND"],
    }


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
async def test_get_benchmark_composition_window_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"segments": []})

    status_code, payload = await service.get_benchmark_composition_window(
        benchmark_id="BMK_2",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["segments"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/benchmarks/BMK_2/composition-window"
    assert _FakeAsyncClient.calls[0]["json"] == {"window": {"start_date": "2026-01-01", "end_date": "2026-02-24"}}


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
async def test_get_benchmark_market_series_uses_default_series_fields_when_not_overridden():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"component_series": []})

    status_code, payload = await service.get_benchmark_market_series(
        benchmark_id="BMK_4",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["component_series"] == []
    assert _FakeAsyncClient.calls[0]["json"]["series_fields"] == ["index_return", "component_weight"]
    assert "target_currency" not in _FakeAsyncClient.calls[0]["json"]


@pytest.mark.asyncio
async def test_get_index_catalog_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"records": []})

    status_code, payload = await service.get_index_catalog(
        as_of_date=date(2026, 2, 24),
        index_ids=["IDX_GLOBAL_EQUITY_TR", "IDX_GLOBAL_BOND_TR"],
        index_currency="USD",
        index_type="BENCHMARK",
        index_status="ACTIVE",
    )

    assert status_code == 200
    assert payload["records"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/indices/catalog"
    assert _FakeAsyncClient.calls[0]["json"] == {
        "as_of_date": "2026-02-24",
        "index_ids": ["IDX_GLOBAL_EQUITY_TR", "IDX_GLOBAL_BOND_TR"],
        "index_currency": "USD",
        "index_type": "BENCHMARK",
        "index_status": "ACTIVE",
    }


def test_index_catalog_filter_payload_omits_absent_optional_filters():
    assert _index_catalog_filter_payload(
        index_ids=[],
        index_currency=None,
        index_type="BENCHMARK",
        index_status="",
    ) == {"index_type": "BENCHMARK"}


@pytest.mark.asyncio
async def test_get_fx_rates_uses_query_params_contract(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_get_with_retry(**kwargs):
        captured.update(kwargs)
        return 200, {"points": []}

    monkeypatch.setattr("app.services.core_integration_service.get_with_retry", _fake_get_with_retry)
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)

    status_code, payload = await service.get_fx_rates(
        from_currency="EUR",
        to_currency="USD",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assert status_code == 200
    assert payload["points"] == []
    assert captured["url"] == "http://core/fx-rates/"
    assert captured["query_params"] == {
        "from_currency": "EUR",
        "to_currency": "USD",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    }


@pytest.mark.asyncio
async def test_get_index_price_series_posts_contract_payload():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"points": []})

    status_code, payload = await service.get_index_price_series(
        index_id="IDX_1",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
        target_currency="USD",
    )

    assert status_code == 200
    assert payload["points"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://core/integration/indices/IDX_1/price-series"
    assert _FakeAsyncClient.calls[0]["json"]["target_currency"] == "USD"


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


@pytest.mark.asyncio
async def test_get_risk_free_series_supports_series_mode_override():
    service = CoreIntegrationService(base_url="http://core", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"points": []})

    await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
        series_mode="yield_series",
    )

    assert _FakeAsyncClient.calls[0]["json"]["series_mode"] == "yield_series"
