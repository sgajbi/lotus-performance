from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response


class HttpSecuritySettings(Protocol):
    HTTP_ALLOWED_HOSTS: str
    CORS_ALLOWED_ORIGINS: str
    HTTP_SECURITY_HSTS_ENABLED: bool
    HTTP_SECURITY_HSTS_MAX_AGE_SECONDS: int


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def configure_http_security(app: FastAPI, *, settings: HttpSecuritySettings) -> None:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=csv_setting_values(settings.HTTP_ALLOWED_HOSTS),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=csv_setting_values(settings.CORS_ALLOWED_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id", "X-Request-Id", "X-Trace-Id"],
    )
    app.middleware("http")(build_security_headers_middleware(settings=settings))


def csv_setting_values(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def build_security_headers_middleware(
    *,
    settings: HttpSecuritySettings,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        apply_security_headers(response, settings=settings)
        return response

    return middleware


def apply_security_headers(response: Response, *, settings: HttpSecuritySettings) -> None:
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if settings.HTTP_SECURITY_HSTS_ENABLED:
        response.headers.setdefault(
            "Strict-Transport-Security",
            f"max-age={settings.HTTP_SECURITY_HSTS_MAX_AGE_SECONDS}; includeSubDomains",
        )
