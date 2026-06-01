import json

import pytest

from app.enterprise_readiness import (
    _allowed_audit_metadata,
    _audit_identity_from_headers,
    _authorization_denied_response,
    _content_length,
    _header_capabilities,
    _load_capability_rule_family,
    _normalized_headers,
    _required_capability,
    _required_capability_from_rules,
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
