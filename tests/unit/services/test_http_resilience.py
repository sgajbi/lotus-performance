import json as jsonlib
import logging

import httpx
import pytest

from app.services.http_resilience import get_with_retry, post_with_retry, response_payload


async def _capture_sleep(delay_seconds: float) -> None:
    _CapturedSleep.delays.append(delay_seconds)


class _CapturedSleep:
    delays: list[float] = []


class _FlakyAsyncClient:
    attempts = 0

    def __init__(self, timeout: float):
        _ = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        payload_json = json
        _ = url, payload_json, headers
        _FlakyAsyncClient.attempts += 1
        if _FlakyAsyncClient.attempts == 1:
            raise httpx.TimeoutException("timeout")
        return httpx.Response(
            200,
            content=jsonlib.dumps({"ok": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=httpx.Request("POST", "http://test"),
        )


@pytest.mark.asyncio
async def test_post_with_retry_retries_timeout(monkeypatch, caplog):
    _FlakyAsyncClient.attempts = 0
    caplog.set_level(logging.WARNING, logger="app.services.http_resilience")
    monkeypatch.setattr("httpx.AsyncClient", _FlakyAsyncClient)
    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=2,
        backoff_seconds=0.0,
    )
    assert status == 200
    assert payload == {"ok": True}
    assert _FlakyAsyncClient.attempts == 2
    assert caplog.records[0].extra_fields["retry_reason"] == "transport_exception"
    assert caplog.records[0].extra_fields["exception_type"] == "TimeoutException"


class _AlwaysTimeoutClient:
    def __init__(self, timeout: float):
        _ = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        _ = url, json, headers
        raise httpx.TimeoutException("timeout")


@pytest.mark.asyncio
async def test_post_with_retry_raises_after_max_retries(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _AlwaysTimeoutClient)
    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=0,
        backoff_seconds=0.0,
    )
    assert status == 503
    assert "upstream communication failure" in payload["detail"]


@pytest.mark.asyncio
async def test_post_with_retry_returns_exhausted_retries_for_invalid_retry_config():
    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=-1,
        backoff_seconds=0.0,
    )
    assert status == 503
    assert payload["detail"] == "upstream communication failure: exhausted retries"


def test_response_payload_wraps_non_json_and_non_dict_payloads():
    dict_response = httpx.Response(
        200,
        content=jsonlib.dumps({"ok": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        request=httpx.Request("POST", "http://test"),
    )
    assert response_payload(dict_response) == {"ok": True}

    text_response = httpx.Response(502, text="bad gateway", request=httpx.Request("POST", "http://test"))
    assert response_payload(text_response) == {"detail": "bad gateway"}

    list_response = httpx.Response(
        200,
        content=jsonlib.dumps(["a", "b"]).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        request=httpx.Request("POST", "http://test"),
    )
    assert response_payload(list_response) == {"detail": ["a", "b"]}


class _FlakyGetClient:
    attempts = 0

    def __init__(self, timeout: float):
        _ = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        _ = url, params, headers
        _FlakyGetClient.attempts += 1
        if _FlakyGetClient.attempts == 1:
            raise httpx.NetworkError("boom")
        return httpx.Response(
            200,
            content=jsonlib.dumps({"points": []}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=httpx.Request("GET", "http://test"),
        )


@pytest.mark.asyncio
async def test_get_with_retry_retries_network_errors(monkeypatch):
    _FlakyGetClient.attempts = 0
    monkeypatch.setattr("httpx.AsyncClient", _FlakyGetClient)

    status, payload = await get_with_retry(
        url="http://pas/fx-rates",
        timeout_seconds=1.0,
        query_params={"from_currency": "EUR", "to_currency": "USD"},
        headers={"X-Correlation-Id": "cid"},
        max_retries=2,
        backoff_seconds=0.0,
    )

    assert status == 200
    assert payload == {"points": []}
    assert _FlakyGetClient.attempts == 2


class _AlwaysTimeoutGetClient:
    def __init__(self, timeout: float):
        _ = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        _ = url, params, headers
        raise httpx.TimeoutException("timeout")


@pytest.mark.asyncio
async def test_get_with_retry_returns_unavailable_after_retry_budget(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _AlwaysTimeoutGetClient)

    status, payload = await get_with_retry(
        url="http://pas/fx-rates",
        timeout_seconds=1.0,
        query_params={"from_currency": "EUR", "to_currency": "USD"},
        headers={"X-Correlation-Id": "cid"},
        max_retries=0,
        backoff_seconds=0.0,
    )

    assert status == 503
    assert payload == {"detail": "upstream communication failure: TimeoutException"}


class _TransientStatusClient:
    responses: list[httpx.Response] = []
    attempts = 0

    def __init__(self, timeout: float):
        _ = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        _ = url, json, headers
        response = _TransientStatusClient.responses[_TransientStatusClient.attempts]
        _TransientStatusClient.attempts += 1
        return response


def _json_response(status_code: int, payload: dict[str, object], headers: dict[str, str] | None = None):
    return httpx.Response(
        status_code,
        content=jsonlib.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        request=httpx.Request("POST", "http://test"),
    )


@pytest.mark.asyncio
async def test_post_with_retry_retries_transient_status_and_honors_safe_retry_after(monkeypatch, caplog):
    _TransientStatusClient.attempts = 0
    _TransientStatusClient.responses = [
        _json_response(503, {"detail": "temporarily unavailable"}, headers={"Retry-After": "1"}),
        _json_response(200, {"ok": True}),
    ]
    _CapturedSleep.delays = []
    caplog.set_level(logging.WARNING, logger="app.services.http_resilience")
    monkeypatch.setattr("httpx.AsyncClient", _TransientStatusClient)
    monkeypatch.setattr("app.services.http_resilience.asyncio.sleep", _capture_sleep)

    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=2,
        backoff_seconds=0.25,
    )

    assert status == 200
    assert payload == {"ok": True}
    assert _TransientStatusClient.attempts == 2
    assert _CapturedSleep.delays == [1.0]
    assert caplog.records[0].extra_fields["retry_reason"] == "transient_http_status"
    assert caplog.records[0].extra_fields["status_code"] == 503


@pytest.mark.asyncio
async def test_post_with_retry_falls_back_when_retry_after_is_excessive(monkeypatch):
    _TransientStatusClient.attempts = 0
    _TransientStatusClient.responses = [
        _json_response(429, {"detail": "rate limited"}, headers={"Retry-After": "99"}),
        _json_response(200, {"ok": True}),
    ]
    _CapturedSleep.delays = []
    monkeypatch.setattr("httpx.AsyncClient", _TransientStatusClient)
    monkeypatch.setattr("app.services.http_resilience.asyncio.sleep", _capture_sleep)

    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=1,
        backoff_seconds=0.25,
    )

    assert status == 200
    assert payload == {"ok": True}
    assert _CapturedSleep.delays == [0.25]


@pytest.mark.asyncio
async def test_post_with_retry_returns_last_transient_status_after_retry_budget(monkeypatch):
    _TransientStatusClient.attempts = 0
    _TransientStatusClient.responses = [
        _json_response(502, {"detail": "bad gateway"}),
        _json_response(503, {"detail": "still unavailable"}),
    ]
    monkeypatch.setattr("httpx.AsyncClient", _TransientStatusClient)

    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=1,
        backoff_seconds=0.0,
    )

    assert status == 503
    assert payload == {"detail": "still unavailable"}
    assert _TransientStatusClient.attempts == 2


@pytest.mark.asyncio
async def test_post_with_retry_does_not_retry_non_retryable_status(monkeypatch):
    _TransientStatusClient.attempts = 0
    _TransientStatusClient.responses = [
        _json_response(422, {"detail": "invalid request"}),
        _json_response(200, {"ok": True}),
    ]
    monkeypatch.setattr("httpx.AsyncClient", _TransientStatusClient)

    status, payload = await post_with_retry(
        url="http://pas/integration",
        timeout_seconds=1.0,
        json_body={"x": 1},
        headers={"X-Correlation-Id": "cid"},
        max_retries=2,
        backoff_seconds=0.0,
    )

    assert status == 422
    assert payload == {"detail": "invalid request"}
    assert _TransientStatusClient.attempts == 1
