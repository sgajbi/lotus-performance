import json

import pytest

from app.enterprise_readiness import (
    _required_capability,
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
