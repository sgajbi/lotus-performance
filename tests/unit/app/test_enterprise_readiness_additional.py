import json
from datetime import datetime

import pytest
from fastapi import Response

from app.enterprise_readiness import (
    _allowed_audit_metadata,
    _apply_enterprise_policy_header,
    _audit_event_payload,
    _audit_identity_from_headers,
    _authorization_denied_response,
    _authorize_enterprise_request,
    _content_length,
    _emit_allowed_audit_event,
    _enterprise_runtime_config_issues,
    _feature_flag_enabled,
    _has_required_capability,
    _has_service_identity,
    _header_capabilities,
    _is_privileged_read_method,
    _is_write_method,
    _load_capability_rule_family,
    _missing_required_headers,
    _normalized_headers,
    _privileged_read_authz_enabled,
    _required_capability,
    _required_capability_from_rules,
    _write_authz_enabled,
    _write_payload_too_large,
    authorize_privileged_read_request,
    authorize_write_request,
    load_capability_rules,
    load_privileged_read_rules,
    validate_enterprise_runtime_config,
)


def test_validate_enterprise_runtime_config_raises_when_enforcement_enabled(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_POLICY_VERSION", " ")
    monkeypatch.setenv("ENTERPRISE_SECRET_ROTATION_DAYS", "120")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_RUNTIME_CONFIG", "true")

    with pytest.raises(RuntimeError, match="enterprise_runtime_config_invalid"):
        validate_enterprise_runtime_config()


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("POST", True),
        ("patch", True),
        ("GET", False),
        ("OPTIONS", False),
    ],
)
def test_is_write_method_normalizes_method_case(method, expected):
    assert _is_write_method(method) is expected


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("GET", True),
        ("get", True),
        ("POST", False),
        ("HEAD", False),
    ],
)
def test_is_privileged_read_method_normalizes_method_case(method, expected):
    assert _is_privileged_read_method(method) is expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("true", True),
        ("1", True),
        ("false", False),
        ("", False),
    ],
)
def test_privileged_read_authz_enabled_uses_governed_env_switch(monkeypatch, configured, expected):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", configured)

    assert _privileged_read_authz_enabled() is expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("true", True),
        ("yes", True),
        ("false", False),
        ("", False),
    ],
)
def test_write_authz_enabled_uses_governed_env_switch(monkeypatch, configured, expected):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", configured)

    assert _write_authz_enabled() is expected


def test_required_capability_returns_none_when_no_matching_rule(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_CAPABILITY_RULES_JSON",
        json.dumps({"POST /analytics": "analytics.write"}),
    )
    assert _required_capability("POST", "/different/path") is None


def test_required_capability_matches_exact_or_child_paths_only():
    assert _required_capability("POST", "/integration/runtime-retention-cleanups/run") == "operations.runtime.manage"
    assert (
        _required_capability("POST", "/integration/runtime-retention-cleanups/run/details")
        == "operations.runtime.manage"
    )
    assert _required_capability("POST", "/integration/runtime-retention-cleanups/run-extra") is None


def test_required_capability_from_rules_is_shared_for_authz_rule_families():
    rules = {"GET /integration/runtime-status": "operations.runtime.read"}
    assert (
        _required_capability_from_rules(method="get", path="/integration/runtime-status/details", rules=rules)
        == "operations.runtime.read"
    )
    assert _required_capability_from_rules(method="POST", path="/integration/runtime-status", rules=rules) is None


def test_normalized_headers_and_capabilities_trim_values():
    normalized = _normalized_headers({"X-Capabilities": " analytics.read, operations.runtime.read ", 1: " value "})
    assert normalized == {
        "1": "value",
        "x-capabilities": "analytics.read, operations.runtime.read",
    }
    assert _header_capabilities(normalized) == {"analytics.read", "operations.runtime.read"}


def test_has_required_capability_accepts_absent_requirement_and_exact_token():
    normalized = _normalized_headers({"X-Capabilities": " analytics.read, operations.runtime.read "})

    assert _has_required_capability(normalized, None)
    assert _has_required_capability(normalized, "operations.runtime.read")
    assert not _has_required_capability(normalized, "operations.runtime.manage")


def test_missing_required_headers_reports_sorted_blank_or_missing_fields():
    normalized = _normalized_headers(
        {
            "X-Actor-Id": " ",
            "X-Tenant-Id": "tenant-a",
            "X-Correlation-Id": "corr-1",
        }
    )

    assert _missing_required_headers(normalized) == ["x-actor-id", "x-role"]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X-Service-Identity": "lotus-performance"}, True),
        ({"Authorization": "Bearer token"}, True),
        ({"X-Service-Identity": " ", "Authorization": ""}, False),
        ({}, False),
    ],
)
def test_has_service_identity_accepts_service_identity_or_authorization(headers, expected):
    assert _has_service_identity(_normalized_headers(headers)) is expected


def test_audit_event_payload_redacts_metadata_and_includes_policy_version(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_POLICY_VERSION", " 2.1.0 ")

    payload = _audit_event_payload(
        action="POST /analytics",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id=None,
        metadata={"token": "secret", "safe": "ok"},
    )

    assert payload["service"] == "lotus-performance"
    assert payload["action"] == "POST /analytics"
    assert payload["actor_id"] == "actor-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["role"] == "operator"
    assert payload["correlation_id"] == ""
    assert payload["policy_version"] == "2.1.0"
    assert payload["metadata"] == {"token": "***REDACTED***", "safe": "ok"}
    assert datetime.fromisoformat(payload["timestamp_utc"]).tzinfo is not None


def test_apply_enterprise_policy_header_sets_normalized_policy_version(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_POLICY_VERSION", " 2.2.0 ")
    response = Response()

    returned = _apply_enterprise_policy_header(response)

    assert returned is response
    assert response.headers["X-Enterprise-Policy-Version"] == "2.2.0"


def test_audit_identity_from_headers_normalizes_case_and_defaults():
    identity = _audit_identity_from_headers(
        {
            "X-Actor-Id": " actor-1 ",
            "X-Tenant-Id": " ",
            "X-Role": " operator ",
            "X-Correlation-Id": " corr-1 ",
        }
    )

    assert identity == {
        "actor_id": "actor-1",
        "tenant_id": "default",
        "role": "operator",
        "correlation_id": "corr-1",
    }


def test_allowed_audit_metadata_classifies_write_surfaces():
    assert _allowed_audit_metadata(method="POST", path="/analytics", status_code=202) == {
        "status_code": 202,
        "access_mode": "write",
        "required_capability": None,
        "governed_surface": None,
    }
    assert _allowed_audit_metadata(
        method="POST",
        path="/integration/recovery-drills/run",
        status_code=200,
    ) == {
        "status_code": 200,
        "access_mode": "write",
        "required_capability": "operations.runtime.manage",
        "governed_surface": "/integration/recovery-drills/run",
    }


def test_allowed_audit_metadata_requires_privileged_read_enforcement(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "false")
    assert _allowed_audit_metadata(method="GET", path="/integration/runtime-status", status_code=200) is None

    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    assert _allowed_audit_metadata(method="GET", path="/integration/runtime-status", status_code=200) == {
        "status_code": 200,
        "access_mode": "privileged_read",
        "required_capability": "operations.runtime.read",
        "governed_surface": "/integration/runtime-status",
    }


def test_authorization_denied_response_emits_audit_and_structured_reason(mocker):
    emit = mocker.patch("app.enterprise_readiness.emit_audit_event")

    response = _authorization_denied_response(
        method="POST",
        path="/integration/recovery-drills/run",
        reason="missing_capability:operations.runtime.manage",
        audit_identity={
            "actor_id": "actor-1",
            "tenant_id": "tenant-1",
            "role": "operator",
            "correlation_id": "corr-1",
        },
    )

    assert response.status_code == 403
    assert json.loads(response.body) == {
        "detail": "authorization_policy_denied",
        "reason": "missing_capability:operations.runtime.manage",
    }
    emit.assert_called_once_with(
        action="DENY POST /integration/recovery-drills/run",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id="corr-1",
        metadata={"reason": "missing_capability:operations.runtime.manage"},
    )


def test_emit_allowed_audit_event_uses_method_path_action_and_identity(mocker):
    emit = mocker.patch("app.enterprise_readiness.emit_audit_event")

    _emit_allowed_audit_event(
        method="GET",
        path="/integration/runtime-status",
        audit_identity={
            "actor_id": "actor-1",
            "tenant_id": "tenant-1",
            "role": "operator",
            "correlation_id": "corr-1",
        },
        metadata={"status_code": 200, "access_mode": "privileged_read"},
    )

    emit.assert_called_once_with(
        action="GET /integration/runtime-status",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id="corr-1",
        metadata={"status_code": 200, "access_mode": "privileged_read"},
    )


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 0),
        ({"content-length": "42"}, 42),
        ({"content-length": "invalid"}, 0),
        ({"content-length": None}, 0),
    ],
)
def test_content_length_parses_invalid_values_as_zero(headers, expected):
    assert _content_length(headers) == expected


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        ("POST", {"content-length": "11"}, True),
        ("PATCH", {"content-length": "10"}, False),
        ("GET", {"content-length": "11"}, False),
        ("POST", {"content-length": "invalid"}, False),
    ],
)
def test_write_payload_too_large_applies_only_to_write_methods(method, headers, expected):
    assert _write_payload_too_large(method=method, headers=headers, max_write_payload_bytes=10) is expected


def test_feature_flag_enabled_applies_role_tenant_and_global_fallbacks():
    flags = {
        "analytics.risk": {
            "tenant-a": {"advisor": True, "*": False},
            "tenant-b": {"*": True},
            "*": {"*": False},
        }
    }

    assert _feature_flag_enabled(flags=flags, feature_key="analytics.risk", tenant_id="tenant-a", role="advisor")
    assert not _feature_flag_enabled(flags=flags, feature_key="analytics.risk", tenant_id="tenant-a", role="viewer")
    assert _feature_flag_enabled(flags=flags, feature_key="analytics.risk", tenant_id="tenant-b", role="viewer")
    assert not _feature_flag_enabled(flags=flags, feature_key="analytics.risk", tenant_id="tenant-c", role="viewer")


def test_feature_flag_enabled_fails_closed_for_malformed_blocks():
    flags = {
        "analytics.risk": True,
        "analytics.performance": {"tenant-a": "enabled"},
        "analytics.reporting": {"tenant-a": {"advisor": "yes"}, "*": "enabled"},
    }

    assert not _feature_flag_enabled(flags=flags, feature_key="analytics.risk", tenant_id="tenant-a", role="advisor")
    assert not _feature_flag_enabled(
        flags=flags,
        feature_key="analytics.performance",
        tenant_id="tenant-a",
        role="advisor",
    )
    assert not _feature_flag_enabled(
        flags=flags,
        feature_key="analytics.reporting",
        tenant_id="tenant-a",
        role="advisor",
    )


def test_enterprise_runtime_config_issues_reports_policy_rotation_and_key(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_POLICY_VERSION", " ")
    monkeypatch.setenv("ENTERPRISE_SECRET_ROTATION_DAYS", "91")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.delenv("ENTERPRISE_PRIMARY_KEY_ID", raising=False)

    assert _enterprise_runtime_config_issues() == [
        "missing_policy_version",
        "secret_rotation_days_out_of_range",
        "missing_primary_key_id",
    ]


def test_enterprise_runtime_config_issues_uses_default_for_invalid_rotation_days(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_SECRET_ROTATION_DAYS", "invalid")

    assert "secret_rotation_days_out_of_range" not in _enterprise_runtime_config_issues()


def test_authorize_enterprise_request_preserves_write_denial_precedence(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")

    allowed, reason = _authorize_enterprise_request(method="POST", path="/analytics", headers={})

    assert allowed is False
    assert reason and reason.startswith("missing_headers:")


def test_authorize_enterprise_request_applies_privileged_read_after_write_allows(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_AUTHZ", "true")
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    headers = {
        "X-Actor-Id": "a1",
        "X-Tenant-Id": "t1",
        "X-Role": "operator",
        "X-Correlation-Id": "c1",
        "X-Service-Identity": "lotus-performance",
        "X-Capabilities": "analytics.read",
    }

    allowed, reason = _authorize_enterprise_request(
        method="GET",
        path="/integration/runtime-status",
        headers=headers,
    )

    assert allowed is False
    assert reason == "missing_capability:operations.runtime.read"


def test_authorize_write_request_allows_when_no_capability_rule_matches(monkeypatch):
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
    }
    allowed, reason = authorize_write_request("POST", "/reports/run", headers)
    assert allowed is True
    assert reason is None


def test_load_privileged_read_rules_merges_defaults_and_env(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_PRIVILEGED_READ_RULES_JSON",
        json.dumps({" GET /integration/custom-status ": " operations.custom.read "}),
    )
    rules = load_privileged_read_rules()
    assert rules["GET /integration/runtime-status"] == "operations.runtime.read"
    assert rules["GET /integration/custom-status"] == "operations.custom.read"


def test_load_capability_rule_family_preserves_defaults_and_valid_overrides(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_TEST_RULES_JSON",
        json.dumps({" POST /analytics ": " analytics.write ", "GET /ignored": False}),
    )

    rules = _load_capability_rule_family(
        env_name="ENTERPRISE_TEST_RULES_JSON",
        defaults={"POST /integration/recovery-drills/run": "operations.runtime.manage"},
    )

    assert rules == {
        "POST /analytics": "analytics.write",
        "POST /integration/recovery-drills/run": "operations.runtime.manage",
    }


def test_capability_rule_loader_ignores_blank_and_non_string_overrides(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_CAPABILITY_RULES_JSON",
        json.dumps(
            {
                "POST /integration/runtime-retention-cleanups/run": " ",
                " ": "operations.invalid",
                "POST /analytics": 123,
                " POST /analytics ": " analytics.write ",
            }
        ),
    )

    rules = load_capability_rules()

    assert rules["POST /integration/runtime-retention-cleanups/run"] == "operations.runtime.manage"
    assert " " not in rules
    assert rules["POST /analytics"] == "analytics.write"


def test_privileged_read_rule_loader_ignores_blank_default_override(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_PRIVILEGED_READ_RULES_JSON",
        json.dumps({"GET /integration/runtime-status": " ", "GET /integration/custom-status": False}),
    )

    rules = load_privileged_read_rules()

    assert rules["GET /integration/runtime-status"] == "operations.runtime.read"
    assert "GET /integration/custom-status" not in rules


def test_authorize_privileged_read_request_allows_unmatched_paths(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    allowed, reason = authorize_privileged_read_request("GET", "/integration/capabilities", {})
    assert allowed is True
    assert reason is None


def test_privileged_read_authorization_does_not_match_adjacent_prefix(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ", "true")
    allowed, reason = authorize_privileged_read_request("GET", "/integration/runtime-status-extra", {})
    assert allowed is True
    assert reason is None
