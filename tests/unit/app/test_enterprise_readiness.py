import json

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.enterprise_readiness import (
    _DEFAULT_ENTERPRISE_POLICY_VERSION,
    _ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
    _ENV_ENTERPRISE_ENFORCE_AUTHZ,
    _ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ,
    _ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG,
    _ENV_ENTERPRISE_FEATURE_FLAGS_JSON,
    _ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES,
    _ENV_ENTERPRISE_POLICY_VERSION,
    _ENV_ENTERPRISE_PRIMARY_KEY_ID,
    _ENV_ENTERPRISE_RUNTIME_PROFILE,
    _ENV_ENTERPRISE_SECRET_ROTATION_DAYS,
    _HTTP_STATUS_FORBIDDEN,
    _HTTP_STATUS_PAYLOAD_TOO_LARGE,
    _MISSING_POLICY_VERSION_ISSUE,
    _MISSING_PRIMARY_KEY_ID_ISSUE,
    _PATH_PERFORMANCE_INSPECTIONS,
    _PATH_PERFORMANCE_LINEAGE,
    _PAYLOAD_TOO_LARGE_DETAIL,
    _PRODUCTION_PRIVILEGED_READ_AUTHZ_DISABLED_ISSUE,
    _PRODUCTION_RUNTIME_CONFIG_ENFORCEMENT_DISABLED_ISSUE,
    _PRODUCTION_RUNTIME_THRESHOLD_DISABLED_ISSUE_PREFIX,
    _PRODUCTION_WRITE_AUTHZ_DISABLED_ISSUE,
    _RESPONSE_DETAIL_KEY,
    _RUNTIME_CONFIG_INVALID_PREFIX,
    _SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE,
    authorize_privileged_read_request,
    authorize_write_request,
    build_enterprise_audit_middleware,
    enterprise_policy_version,
    is_feature_enabled,
    redact_sensitive,
    validate_enterprise_runtime_config,
)
from tests.unit.app.enterprise_runtime_test_settings import settings_with_runtime_thresholds


def _request_with_body(
    *,
    method: str = "POST",
    path: str = "/analytics",
    headers: list[tuple[bytes, bytes]] | None = None,
    body_chunks: list[bytes],
) -> Request:
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(body_chunks) - 1}
        for index, chunk in enumerate(body_chunks)
    ] or [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
        },
        receive,
    )


def test_feature_flags_resolution(monkeypatch):
    monkeypatch.setenv(
        _ENV_ENTERPRISE_FEATURE_FLAGS_JSON,
        json.dumps({"analytics.risk": {"tenant-x": {"analyst": True, "*": False}}}),
    )
    assert is_feature_enabled("analytics.risk", "tenant-x", "analyst") is True
    assert is_feature_enabled("analytics.risk", "tenant-x", "viewer") is False


def test_feature_flags_fail_closed_for_malformed_nested_values(monkeypatch):
    monkeypatch.setenv(
        _ENV_ENTERPRISE_FEATURE_FLAGS_JSON,
        json.dumps(
            {
                "analytics.risk": True,
                "analytics.performance": {"tenant-x": "enabled"},
                "analytics.reporting": {"tenant-x": {"analyst": "yes"}, "*": "enabled"},
            }
        ),
    )

    assert is_feature_enabled("analytics.risk", "tenant-x", "analyst") is False
    assert is_feature_enabled("analytics.performance", "tenant-x", "analyst") is False
    assert is_feature_enabled("analytics.reporting", "tenant-x", "analyst") is False


def test_redaction_masks_sensitive_values():
    payload = {"token": "abc", "nested": [{"ssn": "123"}, {"safe": "ok"}]}
    redacted = redact_sensitive(payload)
    assert redacted["token"] == "***REDACTED***"
    assert redacted["nested"][0]["ssn"] == "***REDACTED***"
    assert redacted["nested"][1]["safe"] == "ok"


def test_redaction_handles_non_string_metadata_keys():
    payload = {1: {"token": "abc"}, "safe": "ok"}
    redacted = redact_sensitive(payload)
    assert redacted[1]["token"] == "***REDACTED***"
    assert redacted["safe"] == "ok"


def test_authorize_write_request_enforces_required_headers_when_enabled(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    allowed, reason = authorize_write_request("POST", "/analytics", {})
    assert allowed is False
    assert reason.startswith("missing_headers:")


def test_authorize_write_request_rejects_blank_required_headers(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    headers = {
        "X-Actor-Id": " ",
        "X-Tenant-Id": "t1",
        "X-Role": "\t",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
    }

    allowed, reason = authorize_write_request("POST", "/analytics", headers)

    assert allowed is False
    assert reason == "missing_headers:x-actor-id,x-role"


def test_authorize_write_request_enforces_capability_rules(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(
        _ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
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
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
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
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
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
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
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
    monkeypatch.setenv(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, "120")
    issues = validate_enterprise_runtime_config()
    assert _SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE in issues


def test_invalid_json_and_invalid_int_env_defaults(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_FEATURE_FLAGS_JSON, "{bad")
    monkeypatch.setenv(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, "not-a-number")
    assert is_feature_enabled("analytics.risk", "tenant-x", "analyst") is False
    issues = validate_enterprise_runtime_config()
    assert _SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE not in issues


def test_validate_runtime_config_flags_missing_policy_and_key(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " ")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)
    issues = validate_enterprise_runtime_config()
    assert _MISSING_POLICY_VERSION_ISSUE in issues
    assert _MISSING_PRIMARY_KEY_ID_ISSUE in issues
    assert enterprise_policy_version() == _DEFAULT_ENTERPRISE_POLICY_VERSION


def test_validate_runtime_config_fails_closed_for_production_profile(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, raising=False)
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, raising=False)
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, raising=False)
    monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)

    with pytest.raises(RuntimeError, match=_RUNTIME_CONFIG_INVALID_PREFIX) as exc_info:
        validate_enterprise_runtime_config(settings=settings_with_runtime_thresholds())

    message = str(exc_info.value)
    assert _PRODUCTION_WRITE_AUTHZ_DISABLED_ISSUE in message
    assert _PRODUCTION_PRIVILEGED_READ_AUTHZ_DISABLED_ISSUE in message
    assert _PRODUCTION_RUNTIME_CONFIG_ENFORCEMENT_DISABLED_ISSUE in message
    assert _MISSING_PRIMARY_KEY_ID_ISSUE in message


def test_validate_runtime_config_allows_explicit_local_relaxed_mode(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "local")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, "false")
    monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)

    assert validate_enterprise_runtime_config(settings=settings_with_runtime_thresholds()) == []


def test_validate_runtime_config_fails_closed_for_production_threshold_defaults(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, "kms-key-1")

    with pytest.raises(RuntimeError, match=_RUNTIME_CONFIG_INVALID_PREFIX) as exc_info:
        validate_enterprise_runtime_config(settings=Settings())

    message = str(exc_info.value)
    assert (
        f"{_PRODUCTION_RUNTIME_THRESHOLD_DISABLED_ISSUE_PREFIX}:"
        "RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS" in message
    )
    assert (
        f"{_PRODUCTION_RUNTIME_THRESHOLD_DISABLED_ISSUE_PREFIX}:"
        "RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO" in message
    )
    assert (
        f"{_PRODUCTION_RUNTIME_THRESHOLD_DISABLED_ISSUE_PREFIX}:"
        "RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT" in message
    )


def test_validate_runtime_config_accepts_production_authz_contract(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, "kms-key-1")

    assert validate_enterprise_runtime_config(settings=settings_with_runtime_thresholds()) == []


def test_production_operator_write_surfaces_require_runtime_manage_capability(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, "kms-key-1")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "operations.runtime.read",
    }

    for path in {"/integration/recovery-drills/run", "/integration/runtime-retention-cleanups/run"}:
        denied, denied_reason = authorize_write_request("POST", path, headers)
        assert denied is False
        assert denied_reason == "missing_capability:operations.runtime.manage"


def test_production_runtime_read_surface_requires_runtime_read_capability(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, "kms-key-1")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "operations.runtime.manage",
    }

    denied, denied_reason = authorize_privileged_read_request("GET", "/integration/runtime-status", headers)

    assert denied is False
    assert denied_reason == "missing_capability:operations.runtime.read"


def test_lineage_evidence_read_surfaces_require_runtime_read_capability(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "operations.runtime.manage",
    }

    for path in {
        f"{_PATH_PERFORMANCE_LINEAGE}/06d61089-cee1-455e-b31e-2df6f6a2da2e",
        f"{_PATH_PERFORMANCE_LINEAGE}/06d61089-cee1-455e-b31e-2df6f6a2da2e/artifacts/request.json",
    }:
        denied, denied_reason = authorize_privileged_read_request("GET", path, headers)
        assert denied is False
        assert denied_reason == "missing_capability:operations.runtime.read"

    headers["X-Capabilities"] = "operations.runtime.manage,operations.runtime.read"
    allowed, allowed_reason = authorize_privileged_read_request(
        "GET",
        f"{_PATH_PERFORMANCE_LINEAGE}/06d61089-cee1-455e-b31e-2df6f6a2da2e/artifacts/request.json",
        headers,
    )
    assert allowed is True
    assert allowed_reason is None


def test_twr_inspection_evidence_read_surfaces_require_runtime_read_capability(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "operations.runtime.manage",
    }
    inspection_id = "06d61089-cee1-455e-b31e-2df6f6a2da2e"

    for path in {
        f"{_PATH_PERFORMANCE_INSPECTIONS}/{inspection_id}",
        f"{_PATH_PERFORMANCE_INSPECTIONS}/{inspection_id}/artifacts/inspection_summary.json",
    }:
        denied, denied_reason = authorize_privileged_read_request("GET", path, headers)
        assert denied is False
        assert denied_reason == "missing_capability:operations.runtime.read"

    headers["X-Capabilities"] = "operations.runtime.manage,operations.runtime.read"
    allowed, allowed_reason = authorize_privileged_read_request(
        "GET",
        f"{_PATH_PERFORMANCE_INSPECTIONS}/{inspection_id}/artifacts/inspection_summary.json",
        headers,
    )
    assert allowed is True
    assert allowed_reason is None


def test_enterprise_policy_version_trims_configured_value(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " 2.0.0 ")
    assert enterprise_policy_version() == "2.0.0"


@pytest.mark.asyncio
async def test_middleware_blocks_oversized_payload(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES, "1")
    middleware = build_enterprise_audit_middleware()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analytics",
        "headers": [(b"content-length", b"2")],
    }
    request = Request(scope)
    response = await middleware(request, lambda req: None)  # pragma: no cover
    assert response.status_code == _HTTP_STATUS_PAYLOAD_TOO_LARGE
    assert json.loads(response.body) == {_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL}


@pytest.mark.asyncio
async def test_middleware_blocks_oversized_streamed_payload_without_content_length(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES, "3")
    middleware = build_enterprise_audit_middleware()
    request = _request_with_body(body_chunks=[b"ab", b"cd"])

    async def _call_next(body_request):
        await body_request.body()
        return JSONResponse({"ok": True}, status_code=200)  # pragma: no cover

    response = await middleware(request, _call_next)

    assert response.status_code == _HTTP_STATUS_PAYLOAD_TOO_LARGE
    assert json.loads(response.body) == {_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL}


@pytest.mark.asyncio
async def test_middleware_blocks_oversized_streamed_payload_with_invalid_content_length(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES, "3")
    middleware = build_enterprise_audit_middleware()
    request = _request_with_body(headers=[(b"content-length", b"not-a-number")], body_chunks=[b"abcd"])

    async def _call_next(body_request):
        await body_request.body()
        return JSONResponse({"ok": True}, status_code=200)  # pragma: no cover

    response = await middleware(request, _call_next)

    assert response.status_code == _HTTP_STATUS_PAYLOAD_TOO_LARGE
    assert json.loads(response.body) == {_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL}


@pytest.mark.asyncio
async def test_middleware_denies_missing_service_identity(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
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
    assert response.status_code == _HTTP_STATUS_FORBIDDEN


@pytest.mark.asyncio
async def test_middleware_normalizes_blank_denied_audit_identity(monkeypatch, mocker):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    middleware = build_enterprise_audit_middleware()
    emit = mocker.patch("app.enterprise_readiness.emit_audit_event")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analytics",
        "headers": [
            (b"x-actor-id", b"   "),
            (b"x-tenant-id", b"tenant-a"),
            (b"x-role", b"\t"),
            (b"x-correlation-id", b" c1 "),
            (b"x-service-identity", b"lotus-performance"),
        ],
    }
    request = Request(scope)

    response = await middleware(request, lambda req: None)  # pragma: no cover

    assert response.status_code == _HTTP_STATUS_FORBIDDEN
    assert emit.call_args.kwargs["actor_id"] == "unknown"
    assert emit.call_args.kwargs["tenant_id"] == "tenant-a"
    assert emit.call_args.kwargs["role"] == "unknown"
    assert emit.call_args.kwargs["correlation_id"] == "c1"
    assert emit.call_args.kwargs["metadata"]["reason"] == "missing_headers:x-actor-id,x-role"


@pytest.mark.asyncio
async def test_middleware_accepts_invalid_content_length_and_sets_policy_header(monkeypatch, mocker):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, "2.0.0")
    middleware = build_enterprise_audit_middleware()
    emit = mocker.patch("app.enterprise_readiness.emit_audit_event")

    async def _call_next(_request):
        return JSONResponse({"ok": True}, status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/analytics",
        "headers": [
            (b"content-length", b"abc"),
            (b"x-actor-id", b" a1 "),
            (b"x-tenant-id", b" t1 "),
            (b"x-role", b" operator "),
            (b"x-correlation-id", b"  "),
        ],
    }
    request = Request(scope)
    response = await middleware(request, _call_next)
    assert response.status_code == 200
    assert response.headers["X-Enterprise-Policy-Version"] == "2.0.0"
    assert emit.call_args.kwargs["actor_id"] == "a1"
    assert emit.call_args.kwargs["tenant_id"] == "t1"
    assert emit.call_args.kwargs["role"] == "operator"
    assert emit.call_args.kwargs["correlation_id"] == ""


@pytest.mark.asyncio
async def test_middleware_denies_privileged_read_without_identity_headers(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    middleware = build_enterprise_audit_middleware()
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"{_PATH_PERFORMANCE_LINEAGE}/06d61089-cee1-455e-b31e-2df6f6a2da2e/artifacts/request.json",
        "headers": [],
    }
    request = Request(scope)
    response = await middleware(request, lambda req: None)  # pragma: no cover
    assert response.status_code == _HTTP_STATUS_FORBIDDEN


@pytest.mark.asyncio
async def test_middleware_audits_allowed_privileged_read_with_governed_surface_metadata(monkeypatch, mocker):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "false")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
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
    assert emit.call_args.kwargs["actor_id"] == "a1"
    assert emit.call_args.kwargs["tenant_id"] == "t1"
    assert emit.call_args.kwargs["role"] == "operator"
    assert emit.call_args.kwargs["correlation_id"] == "c1"
    assert emit.call_args.kwargs["metadata"]["access_mode"] == "privileged_read"
    assert emit.call_args.kwargs["metadata"]["required_capability"] == "operations.runtime.read"
    assert emit.call_args.kwargs["metadata"]["governed_surface"] == "/integration/runtime-status"


@pytest.mark.asyncio
async def test_middleware_audits_allowed_governed_write_with_capability_metadata(monkeypatch, mocker):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "false")
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
            (b"x-actor-id", b" a1 "),
            (b"x-tenant-id", b" t1 "),
            (b"x-role", b" operator "),
            (b"x-correlation-id", b" c1 "),
            (b"x-service-identity", b"lotus-performance"),
            (b"x-capabilities", b"operations.runtime.manage"),
        ],
    }
    request = Request(scope)

    response = await middleware(request, _call_next)

    assert response.status_code == 200
    emit.assert_called_once()
    assert emit.call_args.kwargs["actor_id"] == "a1"
    assert emit.call_args.kwargs["tenant_id"] == "t1"
    assert emit.call_args.kwargs["role"] == "operator"
    assert emit.call_args.kwargs["correlation_id"] == "c1"
    assert emit.call_args.kwargs["metadata"]["access_mode"] == "write"
    assert emit.call_args.kwargs["metadata"]["required_capability"] == "operations.runtime.manage"
    assert emit.call_args.kwargs["metadata"]["governed_surface"] == "/integration/runtime-retention-cleanups/run"
