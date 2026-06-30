import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)
_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_RETRY_AFTER_HEADER = "Retry-After"
_MAX_RETRY_AFTER_SECONDS = 5.0


def response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": response.text}
    if isinstance(payload, dict):
        return payload
    return {"detail": payload}


async def post_with_retry(
    *,
    url: str,
    timeout_seconds: float,
    json_body: dict[str, Any],
    headers: dict[str, str],
    max_retries: int = 2,
    backoff_seconds: float = 0.2,
) -> tuple[int, dict[str, Any]]:
    return await _request_with_retry(
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        request=lambda client: client.post(url, json=json_body, headers=headers),
    )


async def get_with_retry(
    *,
    url: str,
    timeout_seconds: float,
    query_params: dict[str, Any],
    headers: dict[str, str],
    max_retries: int = 2,
    backoff_seconds: float = 0.2,
) -> tuple[int, dict[str, Any]]:
    return await _request_with_retry(
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        request=lambda client: client.get(url, params=query_params, headers=headers),
    )


async def _request_with_retry(
    *,
    timeout_seconds: float,
    max_retries: int,
    backoff_seconds: float,
    request: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]],
) -> tuple[int, dict[str, Any]]:
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await request(client)
            if _should_retry_response(response=response, attempt=attempt, max_retries=max_retries):
                delay_seconds = _response_retry_delay_seconds(
                    response=response,
                    backoff_seconds=backoff_seconds,
                    attempt=attempt,
                )
                _log_retry(
                    reason="transient_http_status",
                    attempt=attempt,
                    max_retries=max_retries,
                    delay_seconds=delay_seconds,
                    status_code=response.status_code,
                    exception_type=None,
                )
                await asyncio.sleep(delay_seconds)
                continue
            return response.status_code, response_payload(response)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt >= max_retries:
                return 503, {"detail": f"upstream communication failure: {exc.__class__.__name__}"}
            delay_seconds = _exponential_backoff_seconds(backoff_seconds=backoff_seconds, attempt=attempt)
            _log_retry(
                reason="transport_exception",
                attempt=attempt,
                max_retries=max_retries,
                delay_seconds=delay_seconds,
                status_code=None,
                exception_type=exc.__class__.__name__,
            )
            await asyncio.sleep(delay_seconds)

    return 503, {"detail": "upstream communication failure: exhausted retries"}


def _should_retry_response(*, response: httpx.Response, attempt: int, max_retries: int) -> bool:
    return response.status_code in _RETRYABLE_STATUS_CODES and attempt < max_retries


def _response_retry_delay_seconds(*, response: httpx.Response, backoff_seconds: float, attempt: int) -> float:
    fallback_seconds = _exponential_backoff_seconds(backoff_seconds=backoff_seconds, attempt=attempt)
    retry_after_seconds = _safe_retry_after_seconds(response.headers.get(_RETRY_AFTER_HEADER))
    return retry_after_seconds if retry_after_seconds is not None else fallback_seconds


def _exponential_backoff_seconds(*, backoff_seconds: float, attempt: int) -> float:
    return backoff_seconds * (2**attempt)


def _safe_retry_after_seconds(raw_header: str | None) -> float | None:
    if raw_header is None:
        return None
    parsed_seconds = _retry_after_delta_seconds(raw_header.strip())
    if parsed_seconds is None or parsed_seconds < 0 or parsed_seconds > _MAX_RETRY_AFTER_SECONDS:
        return None
    return parsed_seconds


def _retry_after_delta_seconds(raw_header: str) -> float | None:
    if not raw_header:
        return None
    try:
        parsed_seconds = Decimal(raw_header)
    except InvalidOperation:
        return _retry_after_http_date_seconds(raw_header)
    parsed_delay = float(parsed_seconds)
    return parsed_delay


def _retry_after_http_date_seconds(raw_header: str) -> float | None:
    try:
        retry_at = parsedate_to_datetime(raw_header)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return (retry_at - datetime.now(UTC)).total_seconds()


def _log_retry(
    *,
    reason: str,
    attempt: int,
    max_retries: int,
    delay_seconds: float,
    status_code: int | None,
    exception_type: str | None,
) -> None:
    _LOGGER.warning(
        "retrying upstream request",
        extra={
            "extra_fields": {
                "retry_reason": reason,
                "attempt": attempt + 1,
                "max_retries": max_retries,
                "delay_seconds": delay_seconds,
                "status_code": status_code,
                "exception_type": exception_type,
            }
        },
    )
