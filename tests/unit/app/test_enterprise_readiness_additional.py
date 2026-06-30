import json
from datetime import datetime

import pytest
from fastapi import Response

from app import (
    enterprise_audit_emission,
    enterprise_audit_events,
    enterprise_audit_middleware,
    enterprise_audit_redaction,
    enterprise_authorization,
    enterprise_capability_rules,
    enterprise_feature_flags,
    enterprise_payload_limits,
    enterprise_request_context,
    enterprise_response_envelopes,
    enterprise_runtime_config,
)
from app.enterprise_readiness import (
    _ACTOR_ID_HEADER,
    _AUDIT_ACCESS_MODE_PRIVILEGED_READ,
    _AUDIT_ACCESS_MODE_WRITE,
    _AUDIT_METADATA_ACCESS_MODE_KEY,
    _AUDIT_METADATA_GOVERNED_SURFACE_KEY,
    _AUDIT_METADATA_REQUIRED_CAPABILITY_KEY,
    _AUDIT_METADATA_STATUS_CODE_KEY,
    _AUDIT_PAYLOAD_ACTION_KEY,
    _AUDIT_PAYLOAD_ACTOR_ID_KEY,
    _AUDIT_PAYLOAD_CORRELATION_ID_KEY,
    _AUDIT_PAYLOAD_METADATA_KEY,
    _AUDIT_PAYLOAD_POLICY_VERSION_KEY,
    _AUDIT_PAYLOAD_ROLE_KEY,
    _AUDIT_PAYLOAD_SERVICE_KEY,
    _AUDIT_PAYLOAD_TENANT_ID_KEY,
    _AUDIT_PAYLOAD_TIMESTAMP_UTC_KEY,
    _AUTHORIZATION_HEADER,
    _AUTHORIZATION_POLICY_DENIED_DETAIL,
    _CAPABILITIES_HEADER,
    _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
    _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _CONTENT_LENGTH_HEADER,
    _CORRELATION_ID_HEADER,
    _DEFAULT_MAX_WRITE_PAYLOAD_BYTES,
    _DEFAULT_TENANT_ID,
    _DIAGNOSTIC_LIST_SEPARATOR,
    _EMPTY_AUDIT_CORRELATION_ID,
    _EMPTY_ENV_VALUE,
    _EMPTY_JSON_OBJECT,
    _ENTERPRISE_AUDIT_EVENT_NAME,
    _ENTERPRISE_AUDIT_EXTRA_KEY,
    _ENTERPRISE_POLICY_VERSION_HEADER,
    _ENV_ENABLED_VALUES,
    _ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
    _ENV_ENTERPRISE_ENFORCE_AUTHZ,
    _ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ,
    _ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG,
    _ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES,
    _ENV_ENTERPRISE_POLICY_VERSION,
    _ENV_ENTERPRISE_PRIMARY_KEY_ID,
    _ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON,
    _ENV_ENTERPRISE_RUNTIME_PROFILE,
    _ENV_ENTERPRISE_SECRET_ROTATION_DAYS,
    _ENV_SWITCH_DISABLED_DEFAULT,
    _HEADER_CAPABILITY_SEPARATOR,
    _HTTP_METHOD_DELETE,
    _HTTP_METHOD_GET,
    _HTTP_METHOD_PATCH,
    _HTTP_METHOD_POST,
    _HTTP_METHOD_PUT,
    _HTTP_STATUS_FORBIDDEN,
    _HTTP_STATUS_PAYLOAD_TOO_LARGE,
    _MISSING_CAPABILITY_REASON,
    _MISSING_HEADERS_REASON,
    _MISSING_POLICY_VERSION_ISSUE,
    _MISSING_PRIMARY_KEY_ID_ISSUE,
    _PATH_RUNTIME_RETENTION_CLEANUP_RUN,
    _PATH_RUNTIME_STATUS,
    _PAYLOAD_TOO_LARGE_DETAIL,
    _PRODUCTION_LIKE_RUNTIME_PROFILES,
    _PRODUCTION_PRIVILEGED_READ_AUTHZ_DISABLED_ISSUE,
    _PRODUCTION_RUNTIME_CONFIG_ENFORCEMENT_DISABLED_ISSUE,
    _PRODUCTION_WRITE_AUTHZ_DISABLED_ISSUE,
    _REDACTED_VALUE,
    _RESPONSE_DETAIL_KEY,
    _RESPONSE_REASON_KEY,
    _ROLE_HEADER,
    _RULE_RECOVERY_DRILL_RUN_WRITE,
    _RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE,
    _RULE_RUNTIME_STATUS_READ,
    _RUNTIME_CONFIG_INVALID_PREFIX,
    _SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE,
    _SERVICE_IDENTITY_HEADER,
    _TENANT_ID_HEADER,
    _UNKNOWN_ACTOR_ID,
    _UNKNOWN_ROLE,
    PayloadTooLargeError,
    _allowed_audit_metadata,
    _apply_enterprise_policy_header,
    _audit_correlation_id,
    _audit_event_payload,
    _audit_identity_from_headers,
    _audit_metadata,
    _audit_timestamp_utc,
    _authorization_allowed,
    _authorization_denial_metadata,
    _authorization_denied,
    _authorization_denied_response,
    _authorize_enterprise_request,
    _build_enterprise_audit_middleware,
    _capability_rule_key,
    _capability_rule_path_for_method,
    _content_length,
    _denied_request_action,
    _emit_allowed_audit_event,
    _empty_json_map,
    _enterprise_runtime_config_issues,
    _env_enabled,
    _env_value,
    _feature_flag_enabled,
    _governed_surface_for_capability,
    _has_required_capability,
    _has_service_identity,
    _header_capabilities,
    _is_privileged_read_method,
    _is_write_method,
    _load_capability_rule_family,
    _load_json_map,
    _max_write_payload_bytes,
    _missing_capability_reason,
    _missing_headers_reason,
    _missing_required_headers,
    _normalized_enterprise_policy_version,
    _normalized_headers,
    _normalized_http_method,
    _normalized_redaction_field,
    _parse_int_or_default,
    _payload_too_large_response,
    _primary_key_configured,
    _privileged_read_authz_enabled,
    _production_like_runtime_profile_enabled,
    _production_primary_key_config_valid,
    _redacted_mapping,
    _redacted_mapping_value,
    _redacted_sequence,
    _request_action,
    _required_capability,
    _required_capability_from_rules,
    _runtime_config_enforcement_enabled,
    _runtime_config_invalid_message,
    _runtime_config_issues_should_raise,
    _runtime_profile,
    _should_redact_field,
    _write_authz_enabled,
    _write_payload_limited_receive,
    _write_payload_limited_request,
    _write_payload_too_large,
    authorize_privileged_read_request,
    authorize_write_request,
    emit_audit_event,
    load_capability_rules,
    load_privileged_read_rules,
    redact_sensitive,
    validate_enterprise_runtime_config,
)


def test_validate_enterprise_runtime_config_raises_when_enforcement_enabled(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " ")
    monkeypatch.setenv(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, "120")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, "true")

    with pytest.raises(RuntimeError, match=_RUNTIME_CONFIG_INVALID_PREFIX):
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


def test_governed_http_method_tokens_drive_enterprise_method_predicates():
    assert _is_privileged_read_method(_HTTP_METHOD_GET)
    for method in {_HTTP_METHOD_POST, _HTTP_METHOD_PUT, _HTTP_METHOD_PATCH, _HTTP_METHOD_DELETE}:
        assert _is_write_method(method)


def test_normalized_http_method_canonicalizes_case():
    assert _normalized_http_method("patch") == _HTTP_METHOD_PATCH


def test_env_enabled_uses_governed_enabled_tokens_and_disabled_default(monkeypatch):
    env_name = "ENTERPRISE_TEST_SWITCH"
    for configured in _ENV_ENABLED_VALUES:
        monkeypatch.setenv(env_name, configured)
        assert _env_enabled(env_name, _ENV_SWITCH_DISABLED_DEFAULT) is True

    monkeypatch.delenv(env_name, raising=False)
    assert _env_enabled(env_name, _ENV_SWITCH_DISABLED_DEFAULT) is False


def test_env_value_uses_configured_value_or_default(monkeypatch):
    env_name = "ENTERPRISE_TEST_VALUE"
    monkeypatch.setenv(env_name, "configured")
    assert _env_value(env_name, "fallback") == "configured"

    monkeypatch.delenv(env_name, raising=False)
    assert _env_value(env_name, "fallback") == "fallback"


def test_enterprise_readiness_reexports_runtime_config_boundary():
    assert _env_value is enterprise_runtime_config._env_value
    assert _runtime_profile is enterprise_runtime_config._runtime_profile
    assert (
        _production_like_runtime_profile_enabled is enterprise_runtime_config._production_like_runtime_profile_enabled
    )
    assert validate_enterprise_runtime_config is enterprise_runtime_config.validate_enterprise_runtime_config


def test_enterprise_readiness_reexports_feature_flag_boundary():
    assert _feature_flag_enabled is enterprise_feature_flags._feature_flag_enabled


def test_enterprise_readiness_reexports_capability_rule_boundary():
    assert _required_capability is enterprise_capability_rules._required_capability
    assert load_capability_rules is enterprise_capability_rules.load_capability_rules


def test_enterprise_readiness_reexports_request_context_boundary():
    assert _normalized_headers is enterprise_request_context._normalized_headers
    assert _audit_identity_from_headers is enterprise_request_context._audit_identity_from_headers


def test_enterprise_readiness_reexports_audit_redaction_boundary():
    assert redact_sensitive is enterprise_audit_redaction.redact_sensitive
    assert _redacted_mapping is enterprise_audit_redaction._redacted_mapping


def test_enterprise_readiness_reexports_payload_limits_boundary():
    assert _write_payload_too_large is enterprise_payload_limits._write_payload_too_large
    assert _write_payload_limited_request is enterprise_payload_limits._write_payload_limited_request
    assert _write_payload_limited_receive is enterprise_payload_limits._write_payload_limited_receive
    assert _payload_too_large_response is enterprise_payload_limits._payload_too_large_response
    assert PayloadTooLargeError is enterprise_payload_limits.PayloadTooLargeError


def test_enterprise_readiness_reexports_audit_events_boundary():
    assert _audit_event_payload is enterprise_audit_events._audit_event_payload
    assert _apply_enterprise_policy_header is enterprise_audit_events._apply_enterprise_policy_header


def test_enterprise_readiness_reexports_authorization_boundary():
    assert authorize_write_request is enterprise_authorization.authorize_write_request
    assert _allowed_audit_metadata is enterprise_authorization._allowed_audit_metadata


def test_enterprise_readiness_reexports_response_envelope_boundary():
    assert _RESPONSE_DETAIL_KEY is enterprise_response_envelopes._RESPONSE_DETAIL_KEY
    assert _RESPONSE_REASON_KEY is enterprise_response_envelopes._RESPONSE_REASON_KEY


def test_enterprise_readiness_delegates_audit_emission_boundary(mocker):
    emit = mocker.patch.object(enterprise_audit_emission, "emit_audit_event")

    emit_audit_event(
        action="POST /analytics",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id="corr-1",
        metadata={"safe": "ok"},
    )

    emit.assert_called_once()
    assert emit.call_args.kwargs["logger"].name == "enterprise_readiness"
    assert emit.call_args.kwargs["action"] == "POST /analytics"


def test_enterprise_readiness_reexports_audit_middleware_boundary():
    assert _build_enterprise_audit_middleware is enterprise_audit_middleware.build_enterprise_audit_middleware


def test_load_json_map_fails_closed_for_missing_invalid_or_non_object_json(monkeypatch):
    env_name = "ENTERPRISE_TEST_JSON"
    monkeypatch.delenv(env_name, raising=False)
    assert _load_json_map(env_name) == json.loads(_EMPTY_JSON_OBJECT)

    monkeypatch.setenv(env_name, "{bad")
    assert _load_json_map(env_name) == {}

    monkeypatch.setenv(env_name, "[]")
    assert _load_json_map(env_name) == {}

    monkeypatch.setenv(env_name, '{"policy": true}')
    assert _load_json_map(env_name) == {"policy": True}


def test_empty_json_map_returns_fresh_empty_mapping():
    empty_map = _empty_json_map()
    empty_map["policy"] = True

    assert _empty_json_map() == {}


@pytest.mark.parametrize(
    ("configured", "default", "expected"),
    [
        ("42", 0, 42),
        ("invalid", 7, 7),
        (None, 9, 9),
    ],
)
def test_parse_int_or_default_uses_valid_integer_or_fallback(configured, default, expected):
    assert _parse_int_or_default(configured, default) == expected


def test_runtime_config_invalid_message_uses_governed_prefix():
    issues = [_MISSING_POLICY_VERSION_ISSUE, _MISSING_PRIMARY_KEY_ID_ISSUE]
    assert _runtime_config_invalid_message(issues) == (
        f"{_RUNTIME_CONFIG_INVALID_PREFIX}:{_DIAGNOSTIC_LIST_SEPARATOR.join(issues)}"
    )


def test_normalized_enterprise_policy_version_trims_configured_value(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " 2.0.0 ")

    assert _normalized_enterprise_policy_version() == "2.0.0"


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
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, configured)

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
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, configured)

    assert _write_authz_enabled() is expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("true", True),
        ("on", True),
        ("false", False),
        ("", False),
    ],
)
def test_runtime_config_enforcement_enabled_uses_governed_env_switch(monkeypatch, configured, expected):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, configured)

    assert _runtime_config_enforcement_enabled() is expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("production", True),
        ("PROD", True),
        (" staging ", True),
        ("local", False),
        ("development", False),
    ],
)
def test_production_like_runtime_profile_normalizes_profile(monkeypatch, configured, expected):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, configured)

    assert _production_like_runtime_profile_enabled() is expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("primary-key-1", True),
        (" primary-key-1 ", True),
        (" ", False),
        (_EMPTY_ENV_VALUE, False),
        (None, False),
    ],
)
def test_primary_key_configured_requires_non_blank_value(monkeypatch, configured, expected):
    if configured is None:
        monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)
    else:
        monkeypatch.setenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, configured)

    assert _primary_key_configured() is expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("512", 512),
        ("invalid", _DEFAULT_MAX_WRITE_PAYLOAD_BYTES),
        ("", _DEFAULT_MAX_WRITE_PAYLOAD_BYTES),
    ],
)
def test_max_write_payload_bytes_uses_configured_int_or_default(monkeypatch, configured, expected):
    monkeypatch.setenv(_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES, configured)

    assert _max_write_payload_bytes() == expected


def test_required_capability_returns_none_when_no_matching_rule(monkeypatch):
    monkeypatch.setenv(
        _ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
        json.dumps({"POST /analytics": "analytics.write"}),
    )
    assert _required_capability("POST", "/different/path") is None


def test_required_capability_matches_exact_or_child_paths_only():
    assert _required_capability("POST", _PATH_RUNTIME_RETENTION_CLEANUP_RUN) == _CAPABILITY_OPERATIONS_RUNTIME_MANAGE
    assert (
        _required_capability("POST", f"{_PATH_RUNTIME_RETENTION_CLEANUP_RUN}/details")
        == _CAPABILITY_OPERATIONS_RUNTIME_MANAGE
    )
    assert _required_capability("POST", "/integration/runtime-retention-cleanups/run-extra") is None


def test_capability_rule_path_for_method_extracts_matching_rule_path():
    assert _capability_rule_path_for_method(rule_key=_RULE_RUNTIME_STATUS_READ, method="get") == _PATH_RUNTIME_STATUS


def test_capability_rule_path_uses_governed_method_path_separator():
    rule_key = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_STATUS)

    assert _capability_rule_path_for_method(rule_key=rule_key, method=_HTTP_METHOD_GET) == _PATH_RUNTIME_STATUS


def test_capability_rule_key_normalizes_method_and_joins_path():
    assert _capability_rule_key(method="get", path=_PATH_RUNTIME_STATUS) == _RULE_RUNTIME_STATUS_READ


def test_capability_rule_path_for_method_ignores_other_methods():
    assert _capability_rule_path_for_method(rule_key=_RULE_RUNTIME_STATUS_READ, method="POST") is None


def test_required_capability_from_rules_is_shared_for_authz_rule_families():
    rules = {_RULE_RUNTIME_STATUS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ}
    assert (
        _required_capability_from_rules(method="get", path="/integration/runtime-status/details", rules=rules)
        == _CAPABILITY_OPERATIONS_RUNTIME_READ
    )
    assert _required_capability_from_rules(method="POST", path="/integration/runtime-status", rules=rules) is None


def test_normalized_headers_and_capabilities_trim_values():
    normalized = _normalized_headers(
        {
            "X-Capabilities": f" analytics.read{_HEADER_CAPABILITY_SEPARATOR} operations.runtime.read ",
            1: " value ",
        }
    )
    assert normalized == {
        "1": "value",
        _CAPABILITIES_HEADER: "analytics.read, operations.runtime.read",
    }
    assert _header_capabilities(normalized) == {"analytics.read", "operations.runtime.read"}


def test_has_required_capability_accepts_absent_requirement_and_exact_token():
    normalized = _normalized_headers({"X-Capabilities": " analytics.read, operations.runtime.read "})

    assert _has_required_capability(normalized, None)
    assert _has_required_capability(normalized, _CAPABILITY_OPERATIONS_RUNTIME_READ)
    assert not _has_required_capability(normalized, _CAPABILITY_OPERATIONS_RUNTIME_MANAGE)


def test_governed_surface_for_capability_tracks_only_capability_bound_paths():
    assert (
        _governed_surface_for_capability(
            path=_PATH_RUNTIME_STATUS,
            required_capability=_CAPABILITY_OPERATIONS_RUNTIME_READ,
        )
        == _PATH_RUNTIME_STATUS
    )
    assert _governed_surface_for_capability(path=_PATH_RUNTIME_STATUS, required_capability=None) is None


def test_missing_required_headers_reports_sorted_blank_or_missing_fields():
    normalized = _normalized_headers(
        {
            "X-Actor-Id": " ",
            "X-Tenant-Id": "tenant-a",
            "X-Correlation-Id": "corr-1",
        }
    )

    assert _missing_required_headers(normalized) == [_ACTOR_ID_HEADER, _ROLE_HEADER]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({_SERVICE_IDENTITY_HEADER: "lotus-performance"}, True),
        ({_AUTHORIZATION_HEADER: "Bearer token"}, True),
        ({_SERVICE_IDENTITY_HEADER: " ", _AUTHORIZATION_HEADER: ""}, False),
        ({}, False),
    ],
)
def test_has_service_identity_accepts_service_identity_or_authorization(headers, expected):
    assert _has_service_identity(_normalized_headers(headers)) is expected


def test_audit_event_payload_redacts_metadata_and_includes_policy_version(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " 2.1.0 ")

    payload = _audit_event_payload(
        action="POST /analytics",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id=None,
        metadata={"token": "secret", "safe": "ok"},
    )

    assert payload[_AUDIT_PAYLOAD_SERVICE_KEY] == "lotus-performance"
    assert payload[_AUDIT_PAYLOAD_ACTION_KEY] == "POST /analytics"
    assert payload[_AUDIT_PAYLOAD_ACTOR_ID_KEY] == "actor-1"
    assert payload[_AUDIT_PAYLOAD_TENANT_ID_KEY] == "tenant-1"
    assert payload[_AUDIT_PAYLOAD_ROLE_KEY] == "operator"
    assert payload[_AUDIT_PAYLOAD_CORRELATION_ID_KEY] == _EMPTY_AUDIT_CORRELATION_ID
    assert payload[_AUDIT_PAYLOAD_POLICY_VERSION_KEY] == "2.1.0"
    assert payload[_AUDIT_PAYLOAD_METADATA_KEY] == {"token": _REDACTED_VALUE, "safe": "ok"}
    assert datetime.fromisoformat(payload[_AUDIT_PAYLOAD_TIMESTAMP_UTC_KEY]).tzinfo is not None


@pytest.mark.parametrize(
    ("correlation_id", "expected"),
    [
        ("corr-1", "corr-1"),
        (None, _EMPTY_AUDIT_CORRELATION_ID),
        ("", _EMPTY_AUDIT_CORRELATION_ID),
    ],
)
def test_audit_correlation_id_normalizes_missing_value(correlation_id, expected):
    assert _audit_correlation_id(correlation_id) == expected


def test_audit_metadata_redacts_sensitive_nested_values():
    assert _audit_metadata(
        {
            "safe": "ok",
            "nested": {"authorization": "Bearer secret"},
            "items": [{"token": "secret"}],
        }
    ) == {
        "safe": "ok",
        "nested": {"authorization": _REDACTED_VALUE},
        "items": [{"token": _REDACTED_VALUE}],
    }


def test_redaction_field_predicates_normalize_keys():
    assert _normalized_redaction_field("Token") == "token"
    assert _should_redact_field("Authorization")
    assert not _should_redact_field("safe")


def test_redacted_mapping_value_masks_sensitive_fields_and_recurses_safe_values():
    assert _redacted_mapping_value(field="token", value="secret") == _REDACTED_VALUE
    assert _redacted_mapping_value(field="safe", value={"authorization": "Bearer secret"}) == {
        "authorization": _REDACTED_VALUE
    }


def test_redacted_mapping_preserves_keys_and_recurses_values():
    assert _redacted_mapping({1: {"token": "secret"}, "safe": "ok"}) == {
        1: {"token": _REDACTED_VALUE},
        "safe": "ok",
    }


def test_redacted_sequence_recurses_sensitive_items():
    assert _redacted_sequence([{"token": "secret"}, "safe"]) == [
        {"token": _REDACTED_VALUE},
        "safe",
    ]


def test_audit_timestamp_utc_uses_timezone_aware_iso_timestamp():
    timestamp = datetime.fromisoformat(_audit_timestamp_utc())

    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() is not None


def test_emit_audit_event_uses_governed_logger_event_name(mocker):
    logger_info = mocker.patch("app.enterprise_readiness.logger.info")

    emit_audit_event(
        action="POST /analytics",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id="corr-1",
        metadata={"safe": "ok"},
    )

    logger_info.assert_called_once()
    assert logger_info.call_args.args == (_ENTERPRISE_AUDIT_EVENT_NAME,)
    assert (
        logger_info.call_args.kwargs["extra"][_ENTERPRISE_AUDIT_EXTRA_KEY][_AUDIT_PAYLOAD_ACTION_KEY]
        == "POST /analytics"
    )


def test_payload_too_large_response_uses_governed_response_envelope():
    response = _payload_too_large_response()

    assert response.status_code == _HTTP_STATUS_PAYLOAD_TOO_LARGE
    assert json.loads(response.body) == {_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL}


def test_apply_enterprise_policy_header_sets_normalized_policy_version(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " 2.2.0 ")
    response = Response()

    returned = _apply_enterprise_policy_header(response)

    assert returned is response
    assert response.headers[_ENTERPRISE_POLICY_VERSION_HEADER] == "2.2.0"


def test_audit_identity_from_headers_normalizes_case_and_defaults():
    identity = _audit_identity_from_headers(
        {
            _ACTOR_ID_HEADER: " actor-1 ",
            _TENANT_ID_HEADER: " ",
            _ROLE_HEADER: " operator ",
            _CORRELATION_ID_HEADER: " corr-1 ",
        }
    )

    assert identity == {
        _AUDIT_PAYLOAD_ACTOR_ID_KEY: "actor-1",
        _AUDIT_PAYLOAD_TENANT_ID_KEY: _DEFAULT_TENANT_ID,
        _AUDIT_PAYLOAD_ROLE_KEY: "operator",
        _AUDIT_PAYLOAD_CORRELATION_ID_KEY: "corr-1",
    }


def test_audit_identity_from_headers_uses_governed_missing_value_fallbacks():
    assert _audit_identity_from_headers({}) == {
        _AUDIT_PAYLOAD_ACTOR_ID_KEY: _UNKNOWN_ACTOR_ID,
        _AUDIT_PAYLOAD_TENANT_ID_KEY: _DEFAULT_TENANT_ID,
        _AUDIT_PAYLOAD_ROLE_KEY: _UNKNOWN_ROLE,
        _AUDIT_PAYLOAD_CORRELATION_ID_KEY: _EMPTY_AUDIT_CORRELATION_ID,
    }


def test_allowed_audit_metadata_classifies_write_surfaces():
    assert _allowed_audit_metadata(method="POST", path="/analytics", status_code=202) == {
        _AUDIT_METADATA_STATUS_CODE_KEY: 202,
        _AUDIT_METADATA_ACCESS_MODE_KEY: _AUDIT_ACCESS_MODE_WRITE,
        _AUDIT_METADATA_REQUIRED_CAPABILITY_KEY: None,
        _AUDIT_METADATA_GOVERNED_SURFACE_KEY: None,
    }
    assert _allowed_audit_metadata(
        method="POST",
        path="/integration/recovery-drills/run",
        status_code=200,
    ) == {
        _AUDIT_METADATA_STATUS_CODE_KEY: 200,
        _AUDIT_METADATA_ACCESS_MODE_KEY: _AUDIT_ACCESS_MODE_WRITE,
        _AUDIT_METADATA_REQUIRED_CAPABILITY_KEY: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
        _AUDIT_METADATA_GOVERNED_SURFACE_KEY: "/integration/recovery-drills/run",
    }


def test_allowed_audit_metadata_requires_privileged_read_enforcement(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "false")
    assert _allowed_audit_metadata(method="GET", path="/integration/runtime-status", status_code=200) is None

    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    assert _allowed_audit_metadata(method="GET", path="/integration/runtime-status", status_code=200) == {
        _AUDIT_METADATA_STATUS_CODE_KEY: 200,
        _AUDIT_METADATA_ACCESS_MODE_KEY: _AUDIT_ACCESS_MODE_PRIVILEGED_READ,
        _AUDIT_METADATA_REQUIRED_CAPABILITY_KEY: _CAPABILITY_OPERATIONS_RUNTIME_READ,
        _AUDIT_METADATA_GOVERNED_SURFACE_KEY: "/integration/runtime-status",
    }


def test_allowed_audit_metadata_ignores_unmatched_privileged_read_path(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    assert _allowed_audit_metadata(method="GET", path="/integration/capabilities", status_code=200) is None


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

    assert response.status_code == _HTTP_STATUS_FORBIDDEN
    assert json.loads(response.body) == {
        _RESPONSE_DETAIL_KEY: _AUTHORIZATION_POLICY_DENIED_DETAIL,
        _RESPONSE_REASON_KEY: "missing_capability:operations.runtime.manage",
    }
    emit.assert_called_once_with(
        action="DENY POST /integration/recovery-drills/run",
        actor_id="actor-1",
        tenant_id="tenant-1",
        role="operator",
        correlation_id="corr-1",
        metadata={_RESPONSE_REASON_KEY: "missing_capability:operations.runtime.manage"},
    )


def test_authorization_denial_metadata_uses_governed_reason_key():
    assert _authorization_denial_metadata("missing_service_identity") == {
        _RESPONSE_REASON_KEY: "missing_service_identity",
    }
    assert _authorization_denial_metadata(None) == {_RESPONSE_REASON_KEY: None}


def test_authorization_reason_helpers_use_governed_reason_tokens():
    assert _missing_headers_reason([_ACTOR_ID_HEADER, _ROLE_HEADER]) == (
        f"{_MISSING_HEADERS_REASON}:{_DIAGNOSTIC_LIST_SEPARATOR.join([_ACTOR_ID_HEADER, _ROLE_HEADER])}"
    )
    assert _missing_capability_reason(_CAPABILITY_OPERATIONS_RUNTIME_MANAGE) == (
        f"{_MISSING_CAPABILITY_REASON}:{_CAPABILITY_OPERATIONS_RUNTIME_MANAGE}"
    )


def test_authorization_result_helpers_return_governed_tuple_shape():
    assert _authorization_allowed() == (True, None)
    assert _authorization_denied("missing_service_identity") == (False, "missing_service_identity")


def test_request_action_helpers_format_governed_audit_actions():
    assert _request_action(method="POST", path="/integration/recovery-drills/run") == (
        "POST /integration/recovery-drills/run"
    )
    assert _denied_request_action(method="POST", path="/integration/recovery-drills/run") == (
        "DENY POST /integration/recovery-drills/run"
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
        ({_CONTENT_LENGTH_HEADER: "42"}, 42),
        ({_CONTENT_LENGTH_HEADER: "invalid"}, 0),
        ({_CONTENT_LENGTH_HEADER: None}, 0),
    ],
)
def test_content_length_parses_invalid_values_as_zero(headers, expected):
    assert _content_length(headers) == expected


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        ("POST", {_CONTENT_LENGTH_HEADER: "11"}, True),
        ("PATCH", {_CONTENT_LENGTH_HEADER: "10"}, False),
        ("GET", {_CONTENT_LENGTH_HEADER: "11"}, False),
        ("POST", {_CONTENT_LENGTH_HEADER: "invalid"}, False),
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
    monkeypatch.setenv(_ENV_ENTERPRISE_POLICY_VERSION, " ")
    monkeypatch.setenv(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, "91")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)

    assert _enterprise_runtime_config_issues() == [
        _MISSING_POLICY_VERSION_ISSUE,
        _SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE,
        _MISSING_PRIMARY_KEY_ID_ISSUE,
    ]


def test_enterprise_runtime_config_issues_reports_production_authz_posture(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "staging")
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, raising=False)
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, raising=False)
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, raising=False)
    monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)

    assert _enterprise_runtime_config_issues() == [
        _PRODUCTION_WRITE_AUTHZ_DISABLED_ISSUE,
        _PRODUCTION_PRIVILEGED_READ_AUTHZ_DISABLED_ISSUE,
        _PRODUCTION_RUNTIME_CONFIG_ENFORCEMENT_DISABLED_ISSUE,
        _MISSING_PRIMARY_KEY_ID_ISSUE,
    ]


def test_runtime_config_issues_raise_for_production_profile_even_without_runtime_config_flag(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    monkeypatch.delenv(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, raising=False)

    assert _runtime_config_issues_should_raise(["production_write_authz_disabled"])


def test_enterprise_runtime_config_issues_uses_default_for_invalid_rotation_days(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, "invalid")

    assert _SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE not in _enterprise_runtime_config_issues()


def test_enterprise_runtime_security_predicates_enforce_rotation_and_key_boundaries(monkeypatch):
    assert enterprise_runtime_config._secret_rotation_days_valid(1)
    assert enterprise_runtime_config._secret_rotation_days_valid(90)
    assert not enterprise_runtime_config._secret_rotation_days_valid(0)
    assert not enterprise_runtime_config._secret_rotation_days_valid(91)

    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.delenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, raising=False)
    assert not enterprise_runtime_config._write_authz_primary_key_config_valid()

    monkeypatch.setenv(_ENV_ENTERPRISE_RUNTIME_PROFILE, "production")
    assert not _production_primary_key_config_valid()
    assert _PRODUCTION_LIKE_RUNTIME_PROFILES == enterprise_runtime_config._PRODUCTION_LIKE_RUNTIME_PROFILES


def test_authorize_enterprise_request_preserves_write_denial_precedence(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")

    allowed, reason = _authorize_enterprise_request(method="POST", path="/analytics", headers={})

    assert allowed is False
    assert reason and reason.startswith("missing_headers:")


def test_authorize_enterprise_request_applies_privileged_read_after_write_allows(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_AUTHZ, "true")
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
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
    }
    allowed, reason = authorize_write_request("POST", "/reports/run", headers)
    assert allowed is True
    assert reason is None


def test_load_privileged_read_rules_merges_defaults_and_env(monkeypatch):
    monkeypatch.setenv(
        _ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON,
        json.dumps({" GET /integration/custom-status ": " operations.custom.read "}),
    )
    rules = load_privileged_read_rules()
    assert rules["GET /integration/runtime-status"] == _CAPABILITY_OPERATIONS_RUNTIME_READ
    assert rules["GET /integration/custom-status"] == "operations.custom.read"


def test_load_capability_rule_family_preserves_defaults_and_valid_overrides(monkeypatch):
    monkeypatch.setenv(
        "ENTERPRISE_TEST_RULES_JSON",
        json.dumps({" POST /analytics ": " analytics.write ", "GET /ignored": False}),
    )

    rules = _load_capability_rule_family(
        env_name="ENTERPRISE_TEST_RULES_JSON",
        defaults={_RULE_RECOVERY_DRILL_RUN_WRITE: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE},
    )

    assert rules == {
        "POST /analytics": "analytics.write",
        _RULE_RECOVERY_DRILL_RUN_WRITE: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
    }


def test_capability_rule_loader_ignores_blank_and_non_string_overrides(monkeypatch):
    monkeypatch.setenv(
        _ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
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

    assert rules[_RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE] == _CAPABILITY_OPERATIONS_RUNTIME_MANAGE
    assert " " not in rules
    assert rules["POST /analytics"] == "analytics.write"


def test_normalized_capability_rule_override_accepts_only_non_blank_strings():
    normalize = enterprise_capability_rules._normalized_capability_rule_override

    assert normalize(key=" POST /analytics ", value=" analytics.write ") == ("POST /analytics", "analytics.write")
    assert normalize(key=" ", value="analytics.write") is None
    assert normalize(key="POST /analytics", value=False) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" analytics.write ", "analytics.write"),
        (" ", None),
        ("", None),
        (False, None),
        (123, None),
    ],
)
def test_non_blank_rule_string_normalizes_only_required_strings(value, expected):
    normalize = enterprise_capability_rules._non_blank_rule_string

    assert normalize(value) == expected


def test_privileged_read_rule_loader_ignores_blank_default_override(monkeypatch):
    monkeypatch.setenv(
        _ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON,
        json.dumps({"GET /integration/runtime-status": " ", "GET /integration/custom-status": False}),
    )

    rules = load_privileged_read_rules()

    assert rules[_RULE_RUNTIME_STATUS_READ] == _CAPABILITY_OPERATIONS_RUNTIME_READ
    assert "GET /integration/custom-status" not in rules


def test_authorize_privileged_read_request_allows_unmatched_paths(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    allowed, reason = authorize_privileged_read_request("GET", "/integration/capabilities", {})
    assert allowed is True
    assert reason is None


def test_privileged_read_authorization_does_not_match_adjacent_prefix(monkeypatch):
    monkeypatch.setenv(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, "true")
    allowed, reason = authorize_privileged_read_request("GET", "/integration/runtime-status-extra", {})
    assert allowed is True
    assert reason is None
