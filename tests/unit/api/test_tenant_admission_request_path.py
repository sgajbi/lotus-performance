"""The tenant admission path, driven as a real HTTP request.

The previous slice's tests proved the pieces and not the path: they built a
stand-in request object, set and reset the ContextVar by hand, called the
private `_core_headers` helper, and read `observability.py` as text to check
the middleware resets what it sets. Each of those is a proxy. Together they
could all pass while the request path was broken, because none of them ran it.

These tests run it. A probe route is mounted on the real application object
from `main`, so the request passes through the real middleware stack, the real
production factory, the real `CoreIntegrationService` and the real exception
handlers registered in `main.py`. Only the outbound Core call is replaced, by
a recorder that captures the headers the service actually built.

What this does NOT prove, stated plainly rather than left to be assumed: it
does not exercise any particular business endpoint's validation or payload
handling, and it does not run Core. It proves that an admitted tenant reaches
the outbound call, that an unadmitted one is refused before any call is made
and arrives as a 401, and that two tenants in flight together each reach Core
under their own.

It also does not prove the middleware's `tenant_id_var.reset` is necessary.
Deleting that line leaves every test in this file green, because Starlette's
`BaseHTTPMiddleware` runs the handler in its own task and asyncio copies the
context per task, so a request's tenant is already invisible to the next one.
That was checked, not assumed, and it corrects an earlier claim of mine that
the reset was preventing a cross-request leak. The reset stays as hygiene and
would matter under a pure-ASGI middleware setting the variable in the caller's
context; it is not what isolates these requests.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.services.core_tenant_authority import TENANT_HEADER
from main import app

_PROBE_PATH = "/internal-test/tenant-admission-probe"


class _RecordingCore:
    """Captures the headers the real service builds, without leaving the process."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.calls.append(kwargs)
        return 200, {"probe": "ok"}

    @property
    def tenants(self) -> list[str | None]:
        return [call["headers"].get(TENANT_HEADER) for call in self.calls]


@pytest.fixture
def recorded_core(monkeypatch) -> _RecordingCore:
    """Replace only the outbound transport, leaving header construction real."""

    recorder = _RecordingCore()
    monkeypatch.setattr("app.services.core_integration_service.post_with_retry", recorder, raising=True)
    return recorder


@pytest.fixture(scope="module", autouse=True)
def _probe_route():
    """Mount a probe that performs a genuine Core read through the production factory.

    Using the real `app` matters: it carries the observability middleware that
    populates the tenant context and the exception handlers that decide what a
    refusal looks like to a caller. Neither is re-implemented here.
    """

    from datetime import date

    from app.core.config import get_settings
    from app.services.portfolio_source_service import build_stateful_input_service

    @app.get(_PROBE_PATH)
    async def _tenant_admission_probe() -> dict[str, str]:
        core_service = build_stateful_input_service(settings=get_settings())._core_service
        await core_service.get_portfolio_analytics_reference(
            portfolio_id="PF_PROBE",
            as_of_date=date(2026, 3, 25),
        )
        return {"status": "reached core"}

    yield

    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != _PROBE_PATH]


async def _request(tenant: str | None) -> httpx.Response:
    headers = {} if tenant is None else {TENANT_HEADER: tenant}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(_PROBE_PATH, headers=headers)


def test_an_admitted_tenant_reaches_core_on_the_header_core_reads(recorded_core) -> None:
    """The presented tenant survives middleware, factory and service construction."""

    response = asyncio.run(_request("tenant-sg"))

    assert response.status_code == 200
    assert recorded_core.tenants == ["tenant-sg"]


def test_a_request_without_a_tenant_is_refused_before_any_core_call(recorded_core) -> None:
    """Refusal must precede I/O, and must arrive as an authority outcome.

    `recorded_core.calls == []` is the load-bearing assertion. A 401 alone would
    also be produced by refusing after the request had gone out, and by then the
    read has already been attempted under no established authority.

    401 rather than 500 is the second half: before this slice nothing mapped the
    refusal, so it reached the caller as an internal error, which is both the
    wrong story and retryable-looking.
    """

    response = asyncio.run(_request(None))

    assert response.status_code == 401
    assert recorded_core.calls == [], "no Core call may be made without an admitted tenant"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_tenant_header_is_absent_not_a_value(recorded_core, blank: str) -> None:
    """A header that is present but empty must not become an authority."""

    response = asyncio.run(_request(blank))

    assert response.status_code == 401
    assert recorded_core.calls == []


def test_concurrent_requests_do_not_read_under_each_others_tenant(recorded_core) -> None:
    """Two tenants in flight together must each reach Core under their own.

    This pins the property that matters to a caller. It does NOT prove the
    middleware's `tenant_id_var.reset` is what delivers it, and an earlier
    version of this docstring wrongly said it did. Deleting that reset line and
    re-running leaves every test here green.

    The reason, established by probing rather than assumed: Starlette's
    `BaseHTTPMiddleware` runs the handler in its own task, and asyncio copies
    the context into each task. A tenant set during a request is therefore
    already invisible to sibling requests and to whatever runs next, with or
    without the reset. The reset is correct hygiene -- and would become
    load-bearing under a pure-ASGI middleware that set the variable in the
    caller's own context -- but it is not the mechanism keeping these two
    requests apart, and claiming otherwise would misdescribe the safeguard.
    """

    async def both() -> list[httpx.Response]:
        return list(await asyncio.gather(_request("tenant-a"), _request("tenant-b")))

    responses = asyncio.run(both())

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(recorded_core.tenants) == ["tenant-a", "tenant-b"]


def test_an_unadmitted_request_after_an_admitted_one_is_still_refused(recorded_core) -> None:
    """Authority does not survive the request that carried it.

    This is the ordering where a leak would do the most damage: the second
    caller presents nothing and would silently inherit the first caller's scope.
    As with the concurrent case, the isolation comes from per-task context
    copying rather than from the explicit reset -- what this test guarantees is
    the outcome, not the mechanism.
    """

    first = asyncio.run(_request("tenant-a"))
    second = asyncio.run(_request(None))

    assert (first.status_code, second.status_code) == (200, 401)
    assert recorded_core.tenants == ["tenant-a"]
