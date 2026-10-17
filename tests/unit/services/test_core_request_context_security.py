"""Synthetic security authority; no live credentials or sibling runtime dependency."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import ValidationError

from app.core.config import Settings
from app.observability import tenant_id_var
from app.services.core_request_context import CoreExecutionScopeDenied
from app.services.core_tenant_authority import MissingTenantAuthorityError, TenantAuthority
from app.services.http_resilience import close_upstream_http_client_pool, configure_upstream_http_client_pool
from app.services.portfolio_source_service import build_stateful_input_service
from app.workers.compute_executor_worker import _is_retryable_exception, _restored_job_tenant_authority


def settings(**overrides):
    return Settings(
        _env_file=None,
        **{
            "CORE_REQUEST_CONTEXT_ENABLED": True,
            "CORE_REQUEST_CONTEXT_SERVICE_IDENTITY": " performance-test ",
            "CORE_REQUEST_CONTEXT_KEY_ID": "key-test",
            "CORE_REQUEST_CONTEXT_SECRET": "synthetic-only-key",
            "CORE_REQUEST_CONTEXT_ACTOR_ID": "service-actor",
            "CORE_REQUEST_CONTEXT_ROLE": "source-reader",
            "CORE_REQUEST_CONTEXT_TENANTS": ["tenant-a", "tenant-b"],
            "CORE_REQUEST_CONTEXT_CAPABILITIES": [
                "source_data.portfolio_timeseries_input.read",
                "source_data.benchmark_assignment.read",
            ],
            **overrides,
        },
    )


def test_known_canonical_vector_and_private_normalized_maps(monkeypatch):
    monkeypatch.setattr("app.services.core_request_context.time.time", lambda: 1700000000)
    authority = settings().core_request_context_authority()
    propagation = {"X-Correlation-Id": " corr-vector ", "Authorization": "untrusted", "X-Actor-Id": "forged"}
    headers = authority.signed_headers(tenant=TenantAuthority("tenant-a"), propagation=propagation)
    assert headers["x-enterprise-auth-signature"] == "7a15bee8565b716a4561a07995bdd424f5a992338e7acee2ee8dd516bfea64fb"
    assert headers["x-actor-id"] == "service-actor"
    assert headers["x-service-identity"] == "performance-test"
    assert "authorization" not in headers
    assert propagation["X-Actor-Id"] == "forged"
    headers["x-tenant-id"] = "mutated"
    assert (
        authority.signed_headers(tenant=TenantAuthority("tenant-a"), propagation=propagation)["x-tenant-id"]
        == "tenant-a"
    )
    assert "synthetic-only-key" not in repr(authority)
    assert "synthetic-only-key" not in repr(settings())
    assert "secret" not in authority.model_dump()


@pytest.mark.parametrize(
    "field,value",
    [
        ("SERVICE_IDENTITY", ""),
        ("SERVICE_IDENTITY", "*"),
        ("ACTOR_ID", " "),
        ("ROLE", ""),
        ("KEY_ID", ""),
        ("SECRET", " "),
        ("TENANTS", []),
        ("CAPABILITIES", []),
        ("TENANTS", ["*"]),
        ("CAPABILITIES", ["source_data.*"]),
        ("CAPABILITIES", ["allowed,extra"]),
        ("TENANTS", ["tenant-a", " tenant-a "]),
        ("ACTOR_ID", "x\nforged"),
        ("ROLE", "x" * 129),
    ],
)
def test_enabled_incomplete_or_ambiguous_configuration_fails_closed(field, value):
    with pytest.raises(ValidationError):
        settings(**{f"CORE_REQUEST_CONTEXT_{field}": value})


def test_disabled_compatibility_and_scope_refusal():
    assert Settings(_env_file=None).core_request_context_authority() is None
    authority = settings().core_request_context_authority()
    with pytest.raises(CoreExecutionScopeDenied) as refusal:
        authority.signed_headers(tenant=TenantAuthority("tenant-other"), propagation={"X-Correlation-Id": "c"})
    assert refusal.value.retryable is False
    assert _is_retryable_exception(refusal.value) is False
    assert "tenant-other" not in str(refusal.value)


def test_api_and_worker_declare_identical_explicit_operator_configuration():
    composition = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    expected = composition["x-core-request-context"]
    assert set(expected) == {name for name in Settings.model_fields if name.startswith("CORE_REQUEST_CONTEXT_")}
    for service in ("performance-analytics", "performance-compute-executor"):
        environment = composition["services"][service]["environment"]
        assert {name: environment[name] for name in expected} == expected
    assert expected["CORE_REQUEST_CONTEXT_ENABLED"] == "${CORE_REQUEST_CONTEXT_ENABLED:-false}"
    assert expected["CORE_REQUEST_CONTEXT_SECRET"] == "${CORE_REQUEST_CONTEXT_SECRET:-}"


def _factory_core(config):
    return build_stateful_input_service(settings=config)._core_service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "correlation,expected_status", [("c" * 128, 200), ("c" * 129, 400), ("caf\u00e9", 400), ("<not-set>", 200)]
)
async def test_real_ingress_to_factory_refuses_invalid_core_correlation_before_transport(
    monkeypatch, correlation, expected_status
):
    from app.observability import correlation_id_var
    from main import app

    original_client = httpx.AsyncClient
    transported = []

    async def respond(request):
        transported.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    path = "/internal-test/core-context-correlation-probe"
    config = settings()

    @app.get(path)
    async def source_probe():
        status, _ = await _factory_core(config)._get_json(path="/fx-rates/", query_params={})
        return {"upstream_status": status}

    previous_tenant, previous_correlation = tenant_id_var.get(), correlation_id_var.get()
    try:
        async with original_client(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get(
                path, headers=[(b"X-Tenant-Id", b"tenant-a"), (b"X-Correlation-Id", correlation.encode("latin-1"))]
            )
        assert response.status_code == expected_status
        if expected_status == 200:
            assert response.json() == {"upstream_status": 200}
            assert len(transported) == 1
            assert transported[0].headers["x-correlation-id"] == correlation
            assert len(transported[0].headers["x-enterprise-auth-signature"]) == 64
        else:
            assert transported == []
            assert response.json()["error_code"] == "CORE_REQUEST_CONTEXT_MALFORMED"
            assert response.json()["retryable"] is False
            assert correlation not in response.json()["message"]
        assert tenant_id_var.get() == previous_tenant
        assert correlation_id_var.get() == previous_correlation
    finally:
        app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != path]


@pytest.mark.asyncio
async def test_shared_pool_concurrent_factory_reads_remain_tenant_isolated(monkeypatch):
    clients = []
    requests = []
    original_client = httpx.AsyncClient

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"observations": []})

    def client_factory(**kwargs):
        client = original_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("app.services.http_resilience.httpx.AsyncClient", client_factory)
    configure_upstream_http_client_pool(max_connections=8, max_keepalive_connections=4, keepalive_expiry_seconds=20)
    config = settings()

    async def source_read(tenant, page):
        token = tenant_id_var.set(tenant)
        try:
            service = _factory_core(config)
            return await service._post_json(
                path="/integration/portfolios/P/analytics/portfolio-timeseries", payload={"page": page}
            )
        finally:
            tenant_id_var.reset(token)

    previous = tenant_id_var.get()
    try:
        results = await asyncio.gather(
            *(source_read(tenant, page) for tenant in ("tenant-a", "tenant-b") for page in range(3))
        )
        assert all(status == 200 for status, _ in results)
        assert len(clients) == 1
        assert "x-tenant-id" not in clients[0].headers
        assert "x-enterprise-auth-signature" not in clients[0].headers
        assert sorted(request.headers["x-tenant-id"] for request in requests) == ["tenant-a"] * 3 + ["tenant-b"] * 3
        assert all(len(request.headers["x-enterprise-auth-signature"]) == 64 for request in requests)
        assert tenant_id_var.get() == previous
    finally:
        await close_upstream_http_client_pool()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_deterministic_core_refusal_remains_nonretryable(monkeypatch, status):
    calls = []
    original_client = httpx.AsyncClient

    async def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "native auth refusal"})

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    token = tenant_id_var.set("tenant-a")
    try:
        result = await _factory_core(settings())._post_json(path="/integration/benchmarks/B/definition", payload={})
        assert result == (status, {"detail": "native auth refusal"})
        assert len(calls) == 1
    finally:
        tenant_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["exception", "cancellation"])
async def test_delayed_worker_uses_fresh_service_context_and_restores_tenant(monkeypatch, exit_mode):
    clock = [1700000000]
    monkeypatch.setattr("app.services.core_request_context.time.time", lambda: clock[0])
    config = settings()
    token = tenant_id_var.set("tenant-a")
    try:
        original = _factory_core(config)._core_headers(operation="POST original")
        clock[0] += 301
        # The existing durable worker boundary owns the tenant; original user
        # context/signatures are neither required nor stored for source execution.
        job = SimpleNamespace(tenant_id="tenant-b", calculation_id="synthetic-job")
        expected_exception = asyncio.CancelledError if exit_mode == "cancellation" else RuntimeError
        with pytest.raises(expected_exception):
            with _restored_job_tenant_authority(job):
                fresh = _factory_core(config)._core_headers(operation="POST worker")
                assert fresh["x-tenant-id"] == "tenant-b"
                assert fresh["x-enterprise-auth-timestamp"] == "1700000301"
                assert fresh["x-actor-id"] == original["x-actor-id"] == "service-actor"
                assert fresh["x-enterprise-auth-signature"] != original["x-enterprise-auth-signature"]
                raise expected_exception()
        assert tenant_id_var.get() == "tenant-a"
    finally:
        tenant_id_var.reset(token)


def test_no_tenant_is_not_replaced_by_service_allowlist():
    token = tenant_id_var.set("")
    try:
        with pytest.raises(MissingTenantAuthorityError):
            _factory_core(settings())._core_headers(operation="POST test")
    finally:
        tenant_id_var.reset(token)


@pytest.mark.asyncio
async def test_bounded_retry_retains_context_and_next_logical_call_signs_fresh(monkeypatch):
    original_client = httpx.AsyncClient
    calls = []
    clock = [1700000000]
    monkeypatch.setattr("app.services.core_request_context.time.time", lambda: clock[0])

    async def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    token = tenant_id_var.set("tenant-a")
    try:
        core = _factory_core(settings())
        assert (await core._post_json(path="/integration/benchmarks/B/definition", payload={}))[0] == 200
        assert len(calls) == 2
        assert calls[0].headers["x-enterprise-auth-signature"] == calls[1].headers["x-enterprise-auth-signature"]
        clock[0] += 1
        assert (await core._get_json(path="/fx-rates/", query_params={}))[0] == 200
        assert calls[2].headers["x-enterprise-auth-timestamp"] == "1700000001"
        assert calls[2].headers["x-enterprise-auth-signature"] != calls[1].headers["x-enterprise-auth-signature"]
    finally:
        tenant_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_total_signed_deadline_returns_safe_failure_and_preserves_worker_context(monkeypatch, method):
    original_client = httpx.AsyncClient
    calls = []
    response_cancelled = asyncio.Event()
    monkeypatch.setattr("app.services.core_integration_service.CORE_SIGNED_REQUEST_DEADLINE_SECONDS", 0.02)

    async def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "0"}, json={})
        try:
            await asyncio.Event().wait()
        finally:
            response_cancelled.set()

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    token = tenant_id_var.set("tenant-a")
    try:
        with _restored_job_tenant_authority(SimpleNamespace(tenant_id="tenant-b", calculation_id="synthetic-job")):
            service = _factory_core(settings())
            if method == "GET":
                result = await service._get_json(path="/fx-rates/", query_params={})
            else:
                result = await service._post_json(path="/integration/benchmarks/B/definition", payload={})
        assert result == (503, {"detail": "upstream communication failure: CoreRequestContextDeadlineExceeded"})
        assert len(calls) == 2
        assert response_cancelled.is_set()
        assert tenant_id_var.get() == "tenant-a"
        assert all(call.headers["x-tenant-id"] == "tenant-b" for call in calls)
    finally:
        tenant_id_var.reset(token)


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_from_inflight_source_and_restores_context(monkeypatch):
    original_client = httpx.AsyncClient
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    previous = tenant_id_var.get()

    async def respond(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )

    async def worker_read():
        try:
            with _restored_job_tenant_authority(SimpleNamespace(tenant_id="tenant-b", calculation_id="synthetic-job")):
                await _factory_core(settings())._post_json(path="/integration/benchmarks/B/definition", payload={})
        finally:
            assert tenant_id_var.get() == previous

    task = asyncio.create_task(worker_read())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert tenant_id_var.get() == previous


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [307, 308])
async def test_shared_pool_never_forwards_core_context_to_redirect_origin(monkeypatch, status):
    original_client = httpx.AsyncClient
    requests = []

    async def respond(request):
        requests.append(request)
        assert request.url.host != "outside-core.invalid", "Core authority escaped to redirect origin"
        return httpx.Response(
            status, headers={"Location": "https://outside-core.invalid/collect"}, json={"detail": "redirect"}
        )

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    configure_upstream_http_client_pool(max_connections=8, max_keepalive_connections=4, keepalive_expiry_seconds=20)
    token = tenant_id_var.set("tenant-a")
    try:
        result = await _factory_core(settings())._post_json(path="/integration/benchmarks/B/definition", payload={})
        assert result == (status, {"detail": "redirect"})
        assert len(requests) == 1
        assert "x-enterprise-auth-signature" in requests[0].headers
    finally:
        tenant_id_var.reset(token)
        await close_upstream_http_client_pool()


@pytest.mark.asyncio
async def test_disabled_mode_preserves_unsigned_transport_and_has_no_signed_deadline(monkeypatch):
    original_client = httpx.AsyncClient
    calls = []
    monkeypatch.setattr("app.services.core_integration_service.CORE_SIGNED_REQUEST_DEADLINE_SECONDS", 0)

    async def respond(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        "app.services.http_resilience.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    token = tenant_id_var.set("tenant-a")
    try:
        assert (await _factory_core(Settings(_env_file=None))._post_json(path="/test", payload={}))[0] == 200
        assert calls[0].headers["X-Tenant-Id"] == "tenant-a"
        assert "x-enterprise-auth-signature" not in calls[0].headers
    finally:
        tenant_id_var.reset(token)
