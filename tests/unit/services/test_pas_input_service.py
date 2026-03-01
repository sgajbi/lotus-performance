from datetime import date

import httpx
import pytest

from app.services.pas_input_service import PasInputService


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

    @classmethod
    def queue_text(cls, status_code: int, text: str):
        cls.responses.append(
            httpx.Response(
                status_code=status_code,
                content=text.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                request=httpx.Request("POST", "http://test"),
            )
        )


@pytest.fixture(autouse=True)
def _patch_async_client(monkeypatch):
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr("app.services.http_resilience.httpx.AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_get_core_snapshot_posts_contract_payload():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"snapshot": {"overview": {}}})

    status_code, payload = await service.get_core_snapshot(
        portfolio_id="PORT-1",
        as_of_date=date(2026, 2, 24),
        include_sections=["OVERVIEW", "HOLDINGS"],
        consumer_system="lotus-performance",
    )

    assert status_code == 200
    assert payload["snapshot"] == {"overview": {}}
    assert _FakeAsyncClient.calls[0]["url"] == "http://pas/integration/portfolios/PORT-1/core-snapshot"
    assert _FakeAsyncClient.calls[0]["json"]["include_sections"] == ["OVERVIEW", "HOLDINGS"]
    assert _FakeAsyncClient.calls[0]["json"]["consumer_system"] == "lotus-performance"


@pytest.mark.asyncio
async def test_get_performance_input_posts_contract_payload():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"valuation_points": []})

    status_code, payload = await service.get_performance_input(
        portfolio_id="PORT-2",
        as_of_date=date(2026, 2, 24),
        lookback_days=365,
        consumer_system="lotus-performance",
    )

    assert status_code == 200
    assert "valuation_points" in payload
    assert _FakeAsyncClient.calls[0]["url"] == "http://pas/integration/portfolios/PORT-2/performance-input"
    assert _FakeAsyncClient.calls[0]["json"]["lookback_days"] == 365


@pytest.mark.asyncio
async def test_get_positions_analytics_with_and_without_performance_periods():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"portfolio_id": "PORT-3"})
    _FakeAsyncClient.queue_json(200, {"portfolio_id": "PORT-3"})

    status_one, _ = await service.get_positions_analytics(
        portfolio_id="PORT-3",
        as_of_date=date(2026, 2, 24),
        sections=["BASE"],
        performance_periods=["YTD", "MTD"],
    )
    status_two, _ = await service.get_positions_analytics(
        portfolio_id="PORT-3",
        as_of_date=date(2026, 2, 24),
        sections=["BASE"],
        performance_periods=None,
    )

    assert status_one == 200
    assert status_two == 200
    assert _FakeAsyncClient.calls[0]["url"] == "http://pas/portfolios/PORT-3/positions-analytics"
    assert _FakeAsyncClient.calls[0]["json"]["performance_options"]["periods"] == ["YTD", "MTD"]
    assert "performance_options" not in _FakeAsyncClient.calls[1]["json"]


@pytest.mark.parametrize(
    ("payload", "text", "expected"),
    [
        ({"ok": True}, "", {"ok": True}),
        (["non-dict"], "", {"detail": ["non-dict"]}),
        (ValueError("bad json"), "plain-text", {"detail": "plain-text"}),
    ],
)
def test_response_payload_parsing(payload, text, expected):
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)

    class _Resp:
        def __init__(self, value, raw_text: str):
            self._value = value
            self.text = raw_text

        def json(self):
            if isinstance(self._value, Exception):
                raise self._value
            return self._value

    parsed = service._response_payload(_Resp(payload, text))
    assert parsed == expected


@pytest.mark.asyncio
async def test_text_error_payload_is_mapped_to_detail():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_text(503, "upstream unavailable")
    status_code, payload = await service.get_core_snapshot(
        portfolio_id="PORT-4",
        as_of_date=date(2026, 2, 24),
        include_sections=["OVERVIEW"],
        consumer_system="lotus-performance",
    )
    assert status_code == 503
    assert payload["detail"] == "upstream unavailable"


@pytest.mark.asyncio
async def test_get_benchmark_assignment_posts_contract_payload():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"benchmark_id": "BMK_1"})

    status_code, payload = await service.get_benchmark_assignment(
        portfolio_id="PORT-5",
        as_of_date=date(2026, 2, 24),
        reporting_currency="USD",
    )

    assert status_code == 200
    assert payload["benchmark_id"] == "BMK_1"
    assert _FakeAsyncClient.calls[0]["url"] == "http://pas/integration/portfolios/PORT-5/benchmark-assignment"
    assert _FakeAsyncClient.calls[0]["json"]["as_of_date"] == "2026-02-24"
    assert _FakeAsyncClient.calls[0]["json"]["reporting_currency"] == "USD"


@pytest.mark.asyncio
async def test_get_benchmark_return_series_posts_contract_payload():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"points": []})

    status_code, payload = await service.get_benchmark_return_series(
        benchmark_id="BMK_2",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["points"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://pas/integration/benchmarks/BMK_2/return-series"
    assert _FakeAsyncClient.calls[0]["json"]["window"]["start_date"] == "2026-01-01"
    assert _FakeAsyncClient.calls[0]["json"]["window"]["end_date"] == "2026-02-24"
    assert _FakeAsyncClient.calls[0]["json"]["frequency"] == "daily"


@pytest.mark.asyncio
async def test_get_risk_free_series_posts_contract_payload():
    service = PasInputService(base_url="http://pas", timeout_seconds=2.0)
    _FakeAsyncClient.queue_json(200, {"points": []})

    status_code, payload = await service.get_risk_free_series(
        currency="USD",
        as_of_date=date(2026, 2, 24),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 24),
    )

    assert status_code == 200
    assert payload["points"] == []
    assert _FakeAsyncClient.calls[0]["url"] == "http://pas/integration/reference/risk-free-series"
    assert _FakeAsyncClient.calls[0]["json"]["currency"] == "USD"
    assert _FakeAsyncClient.calls[0]["json"]["series_mode"] == "return_series"
