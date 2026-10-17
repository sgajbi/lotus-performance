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
from uuid import UUID

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


@pytest.mark.parametrize(
    "presented",
    ["tenant-sg ", " tenant-sg", "\ttenant-sg"],
    ids=["trailing space", "leading space", "leading tab"],
)
def test_a_padded_tenant_is_canonicalised_like_core(recorded_core, presented: str) -> None:
    """Performance and Core admit the same canonical tenant identity."""

    response = asyncio.run(_request(presented))

    assert response.status_code == 200
    assert recorded_core.tenants == ["tenant-sg"]


@pytest.mark.parametrize("tenant", ["Tenant-SG_01", "x" * 128], ids=["canonical", "maximum-length"])
def test_the_canonical_presented_tenant_reaches_core(recorded_core, tenant) -> None:
    response = asyncio.run(_request(tenant))

    assert response.status_code == 200
    assert recorded_core.tenants == [tenant]


@pytest.mark.parametrize(
    "headers",
    [[(TENANT_HEADER, "x" * 129)], [(TENANT_HEADER, "tenant-a"), (TENANT_HEADER, "tenant-b")]],
    ids=["oversized", "duplicate"],
)
def test_malformed_authority_survives_installed_context_to_core_boundary(recorded_core, headers) -> None:
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.get(_PROBE_PATH, headers=headers)

    response = asyncio.run(request())
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "TENANT_AUTHORITY_MALFORMED"
    assert response.json()["retryable"] is False
    assert recorded_core.calls == []


@pytest.mark.parametrize(
    "headers, status, code",
    [
        ([], 401, "TENANT_AUTHORITY_REQUIRED"),
        ([(TENANT_HEADER, "   ")], 401, "TENANT_AUTHORITY_REQUIRED"),
        ([(TENANT_HEADER, "x" * 129)], 400, "TENANT_AUTHORITY_MALFORMED"),
        ([(TENANT_HEADER, "tenant-a"), (TENANT_HEADER, "tenant-b")], 400, "TENANT_AUTHORITY_MALFORMED"),
    ],
    ids=["missing", "blank", "oversized", "duplicate"],
)
@pytest.mark.parametrize("offload", [False, True], ids=["inline", "async"])
def test_stateful_twr_refuses_authority_before_source_or_registration(
    recorded_core, mocker, caplog, headers, status, code, offload
):
    from app.core.config import get_settings

    mocker.patch.object(get_settings(), "TWR_EXECUTOR_WINDOW_DAYS", 1 if offload else 365)
    execution = mocker.patch("app.services.submission_fencing_service.execution_registry.register_execution")
    job = mocker.patch("app.services.submission_fencing_service.compute_job_store.register_job")
    lookup = mocker.patch("app.services.stateful_execution_policy_service.execution_registry.get_execution_for_tenant")
    payload = {
        "portfolio_id": "TENANT_INGRESS_CONTROL",
        "input_mode": "stateful",
        "performance_start_date": "2025-01-01",
        "report_end_date": "2025-01-02",
        "metric_basis": "GROSS",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
        "stateful_input": {},
    }

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post("/performance/twr", json=payload, headers=headers)

    response = asyncio.run(request())
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error_code"] == code
    assert body["retryable"] is False
    assert "results_by_period" not in body
    assert "poll_path" not in body
    execution.assert_not_called()
    job.assert_not_called()
    lookup.assert_not_called()
    assert recorded_core.calls == []
    assert "x" * 129 not in response.text
    assert "x" * 129 not in caplog.text


@pytest.mark.parametrize(
    "stateful, headers",
    [
        (True, [(TENANT_HEADER, "  tenant-ingress  ")]),
        (False, [(TENANT_HEADER, "tenant-a"), (TENANT_HEADER, "tenant-b")]),
        (False, [(TENANT_HEADER, "x" * 129)]),
    ],
    ids=["padded-stateful", "stateless-duplicate-ignored", "stateless-oversized-ignored"],
)
def test_twr_keeps_valid_stateful_and_stateless_calculations(mocker, tmp_path, stateful, headers):
    from app.core.config import get_settings
    from app.services.durable_metadata_bootstrap import bootstrap_durable_metadata_stores
    from app.services.execution_registry import execution_registry

    settings = get_settings()
    mocker.patch.object(settings, "LINEAGE_METADATA_DATABASE_URL", f"sqlite:///{tmp_path / 'ingress.db'}")
    mocker.patch.object(settings, "LINEAGE_STORAGE_PATH", tmp_path / "lineage")
    bootstrap_durable_metadata_stores()
    calls = []

    async def source(**kwargs):
        calls.append(kwargs)
        return 200, {
            "portfolio_open_date": "2024-12-31",
            "observations": [
                {"valuation_date": "2025-01-01", "beginning_market_value": "1000", "ending_market_value": "1010"},
                {"valuation_date": "2025-01-02", "beginning_market_value": "1010", "ending_market_value": "1020.1"},
            ],
        }

    mocker.patch("app.services.core_integration_service.post_with_retry", source)
    payload = {
        "portfolio_id": "TENANT_INGRESS_POSITIVE",
        "performance_start_date": "2024-12-31",
        "report_end_date": "2025-01-02",
        "metric_basis": "GROSS",
        "analyses": [{"period": "YTD", "frequencies": ["daily"]}],
    }
    if stateful:
        payload.update(input_mode="stateful", stateful_input={})
    else:
        payload["valuation_points"] = [
            {"perf_date": "2025-01-01", "begin_mv": 1000, "end_mv": 1010},
            {"perf_date": "2025-01-02", "begin_mv": 1010, "end_mv": 1020.1},
        ]

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post("/performance/twr", json=payload, headers=headers)

    response = asyncio.run(request())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results_by_period"]["YTD"]["portfolio"]["summary"]["period_return"]["base"] == pytest.approx(2.01)
    execution = execution_registry.get_execution(UUID(body["calculation_id"]))
    assert execution.tenant_id == ("tenant-ingress" if stateful else "")
    if stateful:
        assert calls
        assert {call["headers"][TENANT_HEADER] for call in calls} == {"tenant-ingress"}
    else:
        assert calls == []


def test_malformed_request_does_not_poison_later_authority(recorded_core):
    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            malformed = await client.get(_PROBE_PATH, headers={TENANT_HEADER: "x" * 129})
            valid = await client.get(_PROBE_PATH, headers={TENANT_HEADER: "tenant-after-refusal"})
            missing = await client.get(_PROBE_PATH)
        return malformed, valid, missing

    responses = asyncio.run(requests())
    assert [response.status_code for response in responses] == [400, 200, 401]
    assert recorded_core.tenants == ["tenant-after-refusal"]
