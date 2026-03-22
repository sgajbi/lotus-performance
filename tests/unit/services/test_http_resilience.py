import json as jsonlib

import httpx
import pytest

from app.services.http_resilience import get_with_retry, post_with_retry, response_payload


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
async def test_post_with_retry_retries_timeout(monkeypatch):
    _FlakyAsyncClient.attempts = 0
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
