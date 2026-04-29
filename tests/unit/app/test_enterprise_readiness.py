import json

import pytest
from fastapi import Request

from app.enterprise_readiness import (
    authorize_privileged_read_request,
    authorize_write_request,
    build_enterprise_audit_middleware,
    is_feature_enabled,
    redact_sensitive,
    validate_enterprise_runtime_config,
)


def test_feature_flags_resolution(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_FEATURE_FLAGS_JSON",
        json.dumps({"analytics.risk": {"tenant-x": {"analyst": True, "*": False}}}),
    )
    assert is_feature_enabled("analytics.risk", "tenant-x", "analyst") is True
    assert is_feature_enabled("analytics.risk", "tenant-x", "viewer") is False


def test_redaction_masks_sensitive_values():
    payload = {"token": "abc", "nested": [{"ssn": "123"}, {"safe": "ok"}]}
    redacted = redact_sensitive(payload)
    assert redacted["token"] == "***REDACTED***"
    assert redacted["nested"][0]["ssn"] == "***REDACTED***"
    assert redacted["nested"][1]["safe"] == "ok"


def test_authorize_write_request_enforces_required_headers_when_enabled(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    allowed, reason = authorize_write_request("POST", "/analytics", {})
    assert allowed is False
    assert reason.startswith("missing_headers:")


def test_authorize_write_request_enforces_capability_rules(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.setenv(
        "ENTERPRISE_CAPABILITY_RULES_JSON",
        json.dumps({"POST /analytics": "analytics.write"}),
    )
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "analyst",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "analytics.read",
    }
    denied, denied_reason = authorize_write_request("POST", "/analytics/calc", headers)
    assert denied is False
    assert denied_reason == "missing_capability:analytics.write"

    headers["X-Capabilities"] = "analytics.read,analytics.write"
    allowed, allowed_reason = authorize_write_request("POST", "/analytics/calc", headers)
    assert allowed is True
    assert allowed_reason is None


def test_authorize_write_request_requires_runtime_manage_capability_for_retention_run(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "operations.runtime.read",
    }
    denied, denied_reason = authorize_write_request("POST", "/integration/runtime-retention-cleanups/run", headers)
    assert denied is False
    assert denied_reason == "missing_capability:operations.runtime.manage"

    headers["X-Capabilities"] = "operations.runtime.read,operations.runtime.manage"
    allowed, allowed_reason = authorize_write_request("POST", "/integration/runtime-retention-cleanups/run", headers)
    assert allowed is True
    assert allowed_reason is None


def test_authorize_write_request_requires_runtime_manage_capability_for_recovery_drill_run(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "operations.runtime.read",
    }
    denied, denied_reason = authorize_write_request("POST", "/integration/recovery-drills/run", headers)
    assert denied is False
    assert denied_reason == "missing_capability:operations.runtime.manage"

    headers["X-Capabilities"] = "operations.runtime.read,operations.runtime.manage"
    allowed, allowed_reason = authorize_write_request("POST", "/integration/recovery-drills/run", headers)
    assert allowed is True
    assert allowed_reason is None


def test_authorize_privileged_read_request_enforces_required_headers_and_capability(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    denied, denied_reason = authorize_privileged_read_request("GET", "/integration/runtime-status", {})
    assert denied is False
    assert denied_reason.startswith("missing_headers:")

    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "analyst",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "analytics.read",
    }
    denied, denied_reason = authorize_privileged_read_request("GET", "/integration/runtime-status", headers)
    assert denied is False
    assert denied_reason == "missing_capability:operations.runtime.read"

    headers["X-Capabilities"] = "analytics.read,operations.runtime.read"
    allowed, allowed_reason = authorize_privileged_read_request("GET", "/integration/runtime-status", headers)
    assert allowed is True
    assert allowed_reason is None


def test_validate_enterprise_runtime_config_reports_rotation_issue(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_SECRET_ROTATION_DAYS", "120")
    issues = validate_enterprise_runtime_config()
    assert "secret_rotation_days_out_of_range" in issues


def test_invalid_json_and_invalid_int_env_defaults(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_FEATURE_FLAGS_JSON", "{bad")
    monkeypatch.setenv("ENTERPRISE_SECRET_ROTATION_DAYS", "not-a-number")
    assert is_feature_enabled("analytics.risk", "tenant-x", "analyst") is False
    issues = validate_enterprise_runtime_config()
    assert "secret_rotation_days_out_of_range" not in issues


def test_validate_runtime_config_flags_missing_policy_and_key(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_POLICY_VERSION", " ")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.delenv("ENTERPRISE_PRIMARY_KEY_ID", raising=False)
    issues = validate_enterprise_runtime_config()
    assert "missing_policy_version" in issues
    assert "missing_primary_key_id" in issues


@pytest.mark.asyncio
async def test_middleware_blocks_oversized_payload(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "false")
    monkeypatch.setenv("ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES", "1")
    middleware = build_enterprise_audit_middleware()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analytics",
        "headers": [(b"content-length", b"2")],
    }
    request = Request(scope)
    response = await middleware(request, lambda req: None)  # pragma: no cover
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_middleware_denies_missing_service_identity(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    middleware = build_enterprise_audit_middleware()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analytics",
        "headers": [
            (b"x-actor-id", b"a1"),
            (b"x-tenant-id", b"t1"),
            (b"x-role", b"analyst"),
            (b"x-correlation-id", b"c1"),
            (b"x-capabilities", b"analytics.write"),
        ],
    }
    request = Request(scope)
    response = await middleware(request, lambda req: None)  # pragma: no cover
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_middleware_accepts_invalid_content_length_and_sets_policy_header(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "false")
    monkeypatch.setenv("ENTERPRISE_POLICY_VERSION", "2.0.0")
    middleware = build_enterprise_audit_middleware()

    async def _call_next(_request):
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True}, status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analytics",
        "headers": [(b"content-length", b"abc")],
    }
    request = Request(scope)
    response = await middleware(request, _call_next)
    assert response.status_code == 200
    assert response.headers["X-Enterprise-Policy-Version"] == "2.0.0"


@pytest.mark.asyncio
async def test_middleware_denies_privileged_read_without_identity_headers(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "false")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    middleware = build_enterprise_audit_middleware()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/integration/runtime-status",
        "headers": [],
    }
    request = Request(scope)
    response = await middleware(request, lambda req: None)  # pragma: no cover
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_middleware_audits_allowed_privileged_read_with_governed_surface_metadata(monkeypatch, mocker):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "false")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    middleware = build_enterprise_audit_middleware()
    emit = mocker.patch("app.enterprise_readiness.emit_audit_event")

    async def _call_next(_request):
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True}, status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/integration/runtime-status",
        "headers": [
            (b"x-actor-id", b"a1"),
            (b"x-tenant-id", b"t1"),
            (b"x-role", b"operator"),
            (b"x-correlation-id", b"c1"),
            (b"x-service-identity", b"lotus-performance"),
            (b"x-capabilities", b"operations.runtime.read"),
        ],
    }
    request = Request(scope)

    response = await middleware(request, _call_next)

    assert response.status_code == 200
    emit.assert_called_once()
    assert emit.call_args.kwargs["metadata"]["access_mode"] == "privileged_read"
    assert emit.call_args.kwargs["metadata"]["required_capability"] == "operations.runtime.read"
    assert emit.call_args.kwargs["metadata"]["governed_surface"] == "/integration/runtime-status"


@pytest.mark.asyncio
async def test_middleware_audits_allowed_governed_write_with_capability_metadata(monkeypatch, mocker):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "false")
    middleware = build_enterprise_audit_middleware()
    emit = mocker.patch("app.enterprise_readiness.emit_audit_event")

    async def _call_next(_request):
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True}, status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/integration/runtime-retention-cleanups/run",
        "headers": [
            (b"x-actor-id", b"a1"),
            (b"x-tenant-id", b"t1"),
            (b"x-role", b"operator"),
            (b"x-correlation-id", b"c1"),
            (b"x-service-identity", b"lotus-performance"),
            (b"x-capabilities", b"operations.runtime.manage"),
        ],
    }
    request = Request(scope)

    response = await middleware(request, _call_next)

    assert response.status_code == 200
    emit.assert_called_once()
    assert emit.call_args.kwargs["metadata"]["access_mode"] == "write"
    assert emit.call_args.kwargs["metadata"]["required_capability"] == "operations.runtime.manage"
    assert emit.call_args.kwargs["metadata"]["governed_surface"] == "/integration/runtime-retention-cleanups/run"
