import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger("enterprise_readiness")

_SERVICE_NAME = "lotus-performance"
_ENTERPRISE_AUDIT_EVENT_NAME = "enterprise_audit_event"
_ENTERPRISE_AUDIT_EXTRA_KEY = "audit"
_ENTERPRISE_POLICY_VERSION_HEADER = "X-Enterprise-Policy-Version"
_DEFAULT_ENTERPRISE_POLICY_VERSION = "1.0.0"
_AUDIT_PAYLOAD_SERVICE_KEY = "service"
_AUDIT_PAYLOAD_ACTION_KEY = "action"
_AUDIT_PAYLOAD_ACTOR_ID_KEY = "actor_id"
_AUDIT_PAYLOAD_TENANT_ID_KEY = "tenant_id"
_AUDIT_PAYLOAD_ROLE_KEY = "role"
_AUDIT_PAYLOAD_CORRELATION_ID_KEY = "correlation_id"
_AUDIT_PAYLOAD_TIMESTAMP_UTC_KEY = "timestamp_utc"
_AUDIT_PAYLOAD_POLICY_VERSION_KEY = "policy_version"
_AUDIT_PAYLOAD_METADATA_KEY = "metadata"
_AUDIT_METADATA_STATUS_CODE_KEY = "status_code"
_AUDIT_METADATA_ACCESS_MODE_KEY = "access_mode"
_AUDIT_METADATA_REQUIRED_CAPABILITY_KEY = "required_capability"
_AUDIT_METADATA_GOVERNED_SURFACE_KEY = "governed_surface"
_AUDIT_ACCESS_MODE_WRITE = "write"
_AUDIT_ACCESS_MODE_PRIVILEGED_READ = "privileged_read"
_RESPONSE_DETAIL_KEY = "detail"
_RESPONSE_REASON_KEY = "reason"
_AUTHORIZATION_POLICY_DENIED_DETAIL = "authorization_policy_denied"
_PAYLOAD_TOO_LARGE_DETAIL = "payload_too_large"
_HTTP_STATUS_FORBIDDEN = 403
_HTTP_STATUS_PAYLOAD_TOO_LARGE = 413
_REDACTED_VALUE = "***REDACTED***"
_MISSING_HEADERS_REASON = "missing_headers"
_MISSING_SERVICE_IDENTITY_REASON = "missing_service_identity"
_MISSING_CAPABILITY_REASON = "missing_capability"
_MISSING_POLICY_VERSION_ISSUE = "missing_policy_version"
_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE = "secret_rotation_days_out_of_range"
_MISSING_PRIMARY_KEY_ID_ISSUE = "missing_primary_key_id"
_RUNTIME_CONFIG_INVALID_PREFIX = "enterprise_runtime_config_invalid"
_DIAGNOSTIC_LIST_SEPARATOR = ","
_CAPABILITIES_HEADER = "x-capabilities"
_SERVICE_IDENTITY_HEADER = "x-service-identity"
_AUTHORIZATION_HEADER = "authorization"
_CONTENT_LENGTH_HEADER = "content-length"
_MISSING_CONTENT_LENGTH = "0"
_HEADER_CAPABILITY_SEPARATOR = ","
_ACTOR_ID_HEADER = "x-actor-id"
_TENANT_ID_HEADER = "x-tenant-id"
_ROLE_HEADER = "x-role"
_CORRELATION_ID_HEADER = "x-correlation-id"
_UNKNOWN_ACTOR_ID = "unknown"
_DEFAULT_TENANT_ID = "default"
_UNKNOWN_ROLE = "unknown"
_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ = "ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ"
_ENV_ENTERPRISE_ENFORCE_AUTHZ = "ENTERPRISE_ENFORCE_AUTHZ"
_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG = "ENTERPRISE_ENFORCE_RUNTIME_CONFIG"
_ENV_ENTERPRISE_PRIMARY_KEY_ID = "ENTERPRISE_PRIMARY_KEY_ID"
_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES = "ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES"
_ENV_ENTERPRISE_POLICY_VERSION = "ENTERPRISE_POLICY_VERSION"
_ENV_ENTERPRISE_SECRET_ROTATION_DAYS = "ENTERPRISE_SECRET_ROTATION_DAYS"
_ENV_ENTERPRISE_FEATURE_FLAGS_JSON = "ENTERPRISE_FEATURE_FLAGS_JSON"
_ENV_ENTERPRISE_CAPABILITY_RULES_JSON = "ENTERPRISE_CAPABILITY_RULES_JSON"
_ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON = "ENTERPRISE_PRIVILEGED_READ_RULES_JSON"
_ENV_SWITCH_DISABLED_DEFAULT = "false"
_ENV_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
_EMPTY_JSON_OBJECT = "{}"
_DEFAULT_MAX_WRITE_PAYLOAD_BYTES = 1_048_576
_DEFAULT_SECRET_ROTATION_DAYS = 90
_CAPABILITY_OPERATIONS_RUNTIME_MANAGE = "operations.runtime.manage"
_CAPABILITY_OPERATIONS_RUNTIME_READ = "operations.runtime.read"
_HTTP_METHOD_DELETE = "DELETE"
_HTTP_METHOD_GET = "GET"
_HTTP_METHOD_PATCH = "PATCH"
_HTTP_METHOD_POST = "POST"
_HTTP_METHOD_PUT = "PUT"
_CAPABILITY_RULE_METHOD_PATH_SEPARATOR = " "
_PATH_RUNTIME_RETENTION_CLEANUP_RUN = "/integration/runtime-retention-cleanups/run"
_PATH_RECOVERY_DRILL_RUN = "/integration/recovery-drills/run"
_PATH_RUNTIME_STATUS = "/integration/runtime-status"
_PATH_RUNTIME_WORK_ITEMS = "/integration/runtime-work-items"
_PATH_RUNTIME_RECOVERIES = "/integration/runtime-recoveries"
_PATH_RECOVERY_DRILLS = "/integration/recovery-drills"
_PATH_RUNTIME_RETENTION_CLEANUPS = "/integration/runtime-retention-cleanups"
_WRITE_METHODS = {_HTTP_METHOD_POST, _HTTP_METHOD_PUT, _HTTP_METHOD_PATCH, _HTTP_METHOD_DELETE}
_REQUIRED_HEADERS = {_ACTOR_ID_HEADER, _TENANT_ID_HEADER, _ROLE_HEADER, _CORRELATION_ID_HEADER}


def _normalized_http_method(method: str) -> str:
    return method.upper()


def _capability_rule_key(*, method: str, path: str) -> str:
    return f"{_normalized_http_method(method)}{_CAPABILITY_RULE_METHOD_PATH_SEPARATOR}{path}"


_RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE = _capability_rule_key(
    method=_HTTP_METHOD_POST,
    path=_PATH_RUNTIME_RETENTION_CLEANUP_RUN,
)
_RULE_RECOVERY_DRILL_RUN_WRITE = _capability_rule_key(method=_HTTP_METHOD_POST, path=_PATH_RECOVERY_DRILL_RUN)
_RULE_RUNTIME_STATUS_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_STATUS)
_RULE_RUNTIME_WORK_ITEMS_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_WORK_ITEMS)
_RULE_RUNTIME_RECOVERIES_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RUNTIME_RECOVERIES)
_RULE_RECOVERY_DRILLS_READ = _capability_rule_key(method=_HTTP_METHOD_GET, path=_PATH_RECOVERY_DRILLS)
_RULE_RUNTIME_RETENTION_CLEANUPS_READ = _capability_rule_key(
    method=_HTTP_METHOD_GET,
    path=_PATH_RUNTIME_RETENTION_CLEANUPS,
)
_DEFAULT_CAPABILITY_RULES = {
    _RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
    _RULE_RECOVERY_DRILL_RUN_WRITE: _CAPABILITY_OPERATIONS_RUNTIME_MANAGE,
}
_DEFAULT_PRIVILEGED_READ_RULES = {
    _RULE_RUNTIME_STATUS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RUNTIME_WORK_ITEMS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RUNTIME_RECOVERIES_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RECOVERY_DRILLS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
    _RULE_RUNTIME_RETENTION_CLEANUPS_READ: _CAPABILITY_OPERATIONS_RUNTIME_READ,
}
_REDACT_FIELDS = {
    "password",
    "secret",
    "token",
    "authorization",
    "ssn",
    "account_number",
    "client_email",
}


def _is_write_method(method: str) -> bool:
    return _normalized_http_method(method) in _WRITE_METHODS


def _is_privileged_read_method(method: str) -> bool:
    return _normalized_http_method(method) == _HTTP_METHOD_GET


def _env_enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in _ENV_ENABLED_VALUES


def _privileged_read_authz_enabled() -> bool:
    return _env_enabled(_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ, _ENV_SWITCH_DISABLED_DEFAULT)


def _write_authz_enabled() -> bool:
    return _env_enabled(_ENV_ENTERPRISE_ENFORCE_AUTHZ, _ENV_SWITCH_DISABLED_DEFAULT)


def _runtime_config_enforcement_enabled() -> bool:
    return _env_enabled(_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG, _ENV_SWITCH_DISABLED_DEFAULT)


def _primary_key_configured() -> bool:
    return bool(os.getenv(_ENV_ENTERPRISE_PRIMARY_KEY_ID, "").strip())


def _max_write_payload_bytes() -> int:
    return _env_int(_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES, _DEFAULT_MAX_WRITE_PAYLOAD_BYTES)


def _load_json_map(name: str) -> dict[str, Any]:
    raw = os.getenv(name, _EMPTY_JSON_OBJECT)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _env_int(name: str, default: int) -> int:
    return _parse_int_or_default(os.getenv(name, str(default)), default)


def _parse_int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _configured_enterprise_policy_version() -> str:
    return os.getenv(_ENV_ENTERPRISE_POLICY_VERSION, _DEFAULT_ENTERPRISE_POLICY_VERSION)


def enterprise_policy_version() -> str:
    return _configured_enterprise_policy_version().strip() or _DEFAULT_ENTERPRISE_POLICY_VERSION


def _enterprise_runtime_config_issues() -> list[str]:
    issues: list[str] = []
    if not _configured_enterprise_policy_version().strip():
        issues.append(_MISSING_POLICY_VERSION_ISSUE)

    rotation_days = _env_int(_ENV_ENTERPRISE_SECRET_ROTATION_DAYS, _DEFAULT_SECRET_ROTATION_DAYS)
    if rotation_days <= 0 or rotation_days > _DEFAULT_SECRET_ROTATION_DAYS:
        issues.append(_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE)

    if _write_authz_enabled() and not _primary_key_configured():
        issues.append(_MISSING_PRIMARY_KEY_ID_ISSUE)

    return issues


def _runtime_config_invalid_message(issues: list[str]) -> str:
    return f"{_RUNTIME_CONFIG_INVALID_PREFIX}:{_DIAGNOSTIC_LIST_SEPARATOR.join(issues)}"


def validate_enterprise_runtime_config() -> list[str]:
    issues = _enterprise_runtime_config_issues()
    if issues and _runtime_config_enforcement_enabled():
        raise RuntimeError(_runtime_config_invalid_message(issues))
    return issues


def load_feature_flags() -> dict[str, dict[str, dict[str, bool]]]:
    return _load_json_map(_ENV_ENTERPRISE_FEATURE_FLAGS_JSON)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _feature_flag_enabled(
    *,
    flags: dict[str, Any],
    feature_key: str,
    tenant_id: str,
    role: str,
) -> bool:
    feature = _dict_value(flags.get(feature_key))
    tenant = _dict_value(feature.get(tenant_id))
    value = tenant.get(role)
    if isinstance(value, bool):
        return value
    fallback = tenant.get("*")
    if isinstance(fallback, bool):
        return fallback
    global_default = _dict_value(feature.get("*")).get("*")
    return bool(global_default) if isinstance(global_default, bool) else False


def _normalized_capability_rule_overrides(configured: dict[str, Any]) -> dict[str, str]:
    rules: dict[str, str] = {}
    for key, value in configured.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        rule_key = key.strip()
        capability = value.strip()
        if rule_key and capability:
            rules[rule_key] = capability
    return rules


def _path_matches_rule(path: str, rule_path: str) -> bool:
    normalized_rule_path = rule_path.rstrip("/") or "/"
    return path == normalized_rule_path or path.startswith(f"{normalized_rule_path}/")


def _capability_rule_path_for_method(*, rule_key: str, method: str) -> str | None:
    prefix = f"{_normalized_http_method(method)}{_CAPABILITY_RULE_METHOD_PATH_SEPARATOR}"
    if not rule_key.upper().startswith(prefix):
        return None
    return rule_key[len(prefix) :]


def _load_capability_rule_family(*, env_name: str, defaults: dict[str, str]) -> dict[str, str]:
    rules = dict(defaults)
    configured = _load_json_map(env_name)
    rules.update(_normalized_capability_rule_overrides(configured))
    return rules


def load_capability_rules() -> dict[str, str]:
    return _load_capability_rule_family(
        env_name=_ENV_ENTERPRISE_CAPABILITY_RULES_JSON,
        defaults=_DEFAULT_CAPABILITY_RULES,
    )


def load_privileged_read_rules() -> dict[str, str]:
    return _load_capability_rule_family(
        env_name=_ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON,
        defaults=_DEFAULT_PRIVILEGED_READ_RULES,
    )


def is_feature_enabled(feature_key: str, tenant_id: str, role: str) -> bool:
    return _feature_flag_enabled(
        flags=load_feature_flags(),
        feature_key=feature_key,
        tenant_id=tenant_id,
        role=role,
    )


def _required_capability_from_rules(*, method: str, path: str, rules: dict[str, str]) -> str | None:
    for key, capability in rules.items():
        rule_path = _capability_rule_path_for_method(rule_key=key, method=method)
        if rule_path is not None and _path_matches_rule(path, rule_path):
            return capability
    return None


def _required_capability(method: str, path: str) -> str | None:
    return _required_capability_from_rules(method=method, path=path, rules=load_capability_rules())


def _required_privileged_read_capability(method: str, path: str) -> str | None:
    return _required_capability_from_rules(method=method, path=path, rules=load_privileged_read_rules())


def _normalized_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def _header_capabilities(normalized_headers: Mapping[str, str]) -> set[str]:
    return {
        part.strip()
        for part in normalized_headers.get(_CAPABILITIES_HEADER, "").split(_HEADER_CAPABILITY_SEPARATOR)
        if part.strip()
    }


def _has_required_capability(normalized_headers: Mapping[str, str], required_capability: str | None) -> bool:
    return required_capability is None or required_capability in _header_capabilities(normalized_headers)


def _governed_surface_for_capability(*, path: str, required_capability: str | None) -> str | None:
    return path if required_capability is not None else None


def _missing_required_headers(normalized_headers: Mapping[str, str]) -> list[str]:
    return sorted(header for header in _REQUIRED_HEADERS if not normalized_headers.get(header))


def _has_service_identity(normalized_headers: Mapping[str, str]) -> bool:
    return bool(normalized_headers.get(_SERVICE_IDENTITY_HEADER) or normalized_headers.get(_AUTHORIZATION_HEADER))


def _audit_identity_from_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    normalized = _normalized_headers(headers)
    return {
        _AUDIT_PAYLOAD_ACTOR_ID_KEY: normalized.get(_ACTOR_ID_HEADER) or _UNKNOWN_ACTOR_ID,
        _AUDIT_PAYLOAD_TENANT_ID_KEY: normalized.get(_TENANT_ID_HEADER) or _DEFAULT_TENANT_ID,
        _AUDIT_PAYLOAD_ROLE_KEY: normalized.get(_ROLE_HEADER) or _UNKNOWN_ROLE,
        _AUDIT_PAYLOAD_CORRELATION_ID_KEY: normalized.get(_CORRELATION_ID_HEADER, ""),
    }


def _allowed_audit_metadata(*, method: str, path: str, status_code: int) -> dict[str, Any] | None:
    write_capability = _required_capability(method, path)
    privileged_read_capability = _required_privileged_read_capability(method, path)
    is_privileged_read = _is_privileged_read_method(method)
    required_capability = privileged_read_capability if is_privileged_read else write_capability
    if not _is_write_method(method) and not (
        is_privileged_read and _privileged_read_authz_enabled() and privileged_read_capability is not None
    ):
        return None
    return {
        _AUDIT_METADATA_STATUS_CODE_KEY: status_code,
        _AUDIT_METADATA_ACCESS_MODE_KEY: (
            _AUDIT_ACCESS_MODE_PRIVILEGED_READ if is_privileged_read else _AUDIT_ACCESS_MODE_WRITE
        ),
        _AUDIT_METADATA_REQUIRED_CAPABILITY_KEY: required_capability,
        _AUDIT_METADATA_GOVERNED_SURFACE_KEY: _governed_surface_for_capability(
            path=path,
            required_capability=required_capability,
        ),
    }


def _authorization_denied_response(
    *,
    method: str,
    path: str,
    reason: str | None,
    audit_identity: dict[str, str],
) -> JSONResponse:
    emit_audit_event(
        action=_denied_request_action(method=method, path=path),
        **audit_identity,
        metadata=_authorization_denial_metadata(reason),
    )
    return JSONResponse(
        status_code=_HTTP_STATUS_FORBIDDEN,
        content={
            _RESPONSE_DETAIL_KEY: _AUTHORIZATION_POLICY_DENIED_DETAIL,
            _RESPONSE_REASON_KEY: reason,
        },
    )


def _authorization_denial_metadata(reason: str | None) -> dict[str, str | None]:
    return {_RESPONSE_REASON_KEY: reason}


def _request_action(*, method: str, path: str) -> str:
    return f"{method} {path}"


def _denied_request_action(*, method: str, path: str) -> str:
    return f"DENY {_request_action(method=method, path=path)}"


def _emit_allowed_audit_event(
    *,
    method: str,
    path: str,
    audit_identity: dict[str, str],
    metadata: dict[str, Any],
) -> None:
    emit_audit_event(
        action=_request_action(method=method, path=path),
        **audit_identity,
        metadata=metadata,
    )


def _content_length(headers: Mapping[str, Any]) -> int:
    return _parse_int_or_default(headers.get(_CONTENT_LENGTH_HEADER, _MISSING_CONTENT_LENGTH), 0)


def _write_payload_too_large(
    *,
    method: str,
    headers: Mapping[str, Any],
    max_write_payload_bytes: int,
) -> bool:
    return _is_write_method(method) and _content_length(headers) > max_write_payload_bytes


def _payload_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=_HTTP_STATUS_PAYLOAD_TOO_LARGE,
        content={_RESPONSE_DETAIL_KEY: _PAYLOAD_TOO_LARGE_DETAIL},
    )


def _missing_headers_reason(missing_headers: list[str]) -> str:
    return f"{_MISSING_HEADERS_REASON}:{_DIAGNOSTIC_LIST_SEPARATOR.join(missing_headers)}"


def _missing_capability_reason(required_capability: str | None) -> str:
    return f"{_MISSING_CAPABILITY_REASON}:{required_capability}"


def _authorization_allowed() -> tuple[bool, None]:
    return True, None


def _authorization_denied(reason: str) -> tuple[bool, str]:
    return False, reason


def _authorize_with_required_capability(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    required_capability: str | None,
) -> tuple[bool, str | None]:
    normalized = _normalized_headers(headers)
    missing = _missing_required_headers(normalized)
    if missing:
        return _authorization_denied(_missing_headers_reason(missing))

    if not _has_service_identity(normalized):
        return _authorization_denied(_MISSING_SERVICE_IDENTITY_REASON)

    if not _has_required_capability(normalized, required_capability):
        return _authorization_denied(_missing_capability_reason(required_capability))

    return _authorization_allowed()


def authorize_write_request(method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    if not _is_write_method(method) or not _write_authz_enabled():
        return _authorization_allowed()

    return _authorize_with_required_capability(
        method=method,
        path=path,
        headers=headers,
        required_capability=_required_capability(method, path),
    )


def authorize_privileged_read_request(method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    if not _is_privileged_read_method(method) or not _privileged_read_authz_enabled():
        return _authorization_allowed()

    required_capability = _required_privileged_read_capability(method, path)
    if required_capability is None:
        return _authorization_allowed()

    return _authorize_with_required_capability(
        method=method,
        path=path,
        headers=headers,
        required_capability=required_capability,
    )


def _authorize_enterprise_request(*, method: str, path: str, headers: dict[str, str]) -> tuple[bool, str | None]:
    authorized, reason = authorize_write_request(method, path, headers)
    if not authorized:
        return authorized, reason
    return authorize_privileged_read_request(method, path, headers)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _REDACT_FIELDS:
                output[key] = _REDACTED_VALUE
            else:
                output[key] = redact_sensitive(item)
        return output
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _audit_event_payload(
    *,
    action: str,
    actor_id: str,
    tenant_id: str,
    role: str,
    correlation_id: str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        _AUDIT_PAYLOAD_SERVICE_KEY: _SERVICE_NAME,
        _AUDIT_PAYLOAD_ACTION_KEY: action,
        _AUDIT_PAYLOAD_ACTOR_ID_KEY: actor_id,
        _AUDIT_PAYLOAD_TENANT_ID_KEY: tenant_id,
        _AUDIT_PAYLOAD_ROLE_KEY: role,
        _AUDIT_PAYLOAD_CORRELATION_ID_KEY: _audit_correlation_id(correlation_id),
        _AUDIT_PAYLOAD_TIMESTAMP_UTC_KEY: _audit_timestamp_utc(),
        _AUDIT_PAYLOAD_POLICY_VERSION_KEY: enterprise_policy_version(),
        _AUDIT_PAYLOAD_METADATA_KEY: _audit_metadata(metadata),
    }


def _audit_metadata(metadata: dict[str, Any]) -> Any:
    return redact_sensitive(metadata)


def _audit_correlation_id(correlation_id: str | None) -> str:
    return correlation_id or ""


def _audit_timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_enterprise_policy_header(response: Response) -> Response:
    response.headers[_ENTERPRISE_POLICY_VERSION_HEADER] = enterprise_policy_version()
    return response


def emit_audit_event(
    *,
    action: str,
    actor_id: str,
    tenant_id: str,
    role: str,
    correlation_id: str | None,
    metadata: dict[str, Any],
) -> None:
    logger.info(
        _ENTERPRISE_AUDIT_EVENT_NAME,
        extra={
            _ENTERPRISE_AUDIT_EXTRA_KEY: _audit_event_payload(
                action=action,
                actor_id=actor_id,
                tenant_id=tenant_id,
                role=role,
                correlation_id=correlation_id,
                metadata=metadata,
            )
        },
    )


def build_enterprise_audit_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    # Enforce enterprise audit and authorization policy on governed surfaces.
    async def middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if _write_payload_too_large(
            method=request.method,
            headers=request.headers,
            max_write_payload_bytes=_max_write_payload_bytes(),
        ):
            return _payload_too_large_response()

        audit_identity = _audit_identity_from_headers(request.headers)
        authorized, reason = _authorize_enterprise_request(
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
        )
        if not authorized:
            return _authorization_denied_response(
                method=request.method,
                path=request.url.path,
                reason=reason,
                audit_identity=audit_identity,
            )

        response = await call_next(request)
        _apply_enterprise_policy_header(response)
        allowed_audit_metadata = _allowed_audit_metadata(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        if allowed_audit_metadata is not None:
            _emit_allowed_audit_event(
                method=request.method,
                path=request.url.path,
                audit_identity=audit_identity,
                metadata=allowed_audit_metadata,
            )
        return response

    return middleware
