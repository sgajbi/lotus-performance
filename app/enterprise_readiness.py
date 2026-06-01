import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app import enterprise_audit_redaction as _audit_redaction
from app import enterprise_capability_rules as _capability_rules
from app import enterprise_feature_flags as _feature_flags
from app import enterprise_request_context as _request_context
from app import enterprise_runtime_config as _runtime_config

_DEFAULT_ENTERPRISE_POLICY_VERSION = _runtime_config._DEFAULT_ENTERPRISE_POLICY_VERSION
_DEFAULT_MAX_WRITE_PAYLOAD_BYTES = _runtime_config._DEFAULT_MAX_WRITE_PAYLOAD_BYTES
_DIAGNOSTIC_LIST_SEPARATOR = _runtime_config._DIAGNOSTIC_LIST_SEPARATOR
_EMPTY_ENV_VALUE = _runtime_config._EMPTY_ENV_VALUE
_EMPTY_JSON_OBJECT = _runtime_config._EMPTY_JSON_OBJECT
_ENV_ENABLED_VALUES = _runtime_config._ENV_ENABLED_VALUES
_ENV_ENTERPRISE_CAPABILITY_RULES_JSON = _runtime_config._ENV_ENTERPRISE_CAPABILITY_RULES_JSON
_ENV_ENTERPRISE_ENFORCE_AUTHZ = _runtime_config._ENV_ENTERPRISE_ENFORCE_AUTHZ
_ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ = _runtime_config._ENV_ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ
_ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG = _runtime_config._ENV_ENTERPRISE_ENFORCE_RUNTIME_CONFIG
_ENV_ENTERPRISE_FEATURE_FLAGS_JSON = _runtime_config._ENV_ENTERPRISE_FEATURE_FLAGS_JSON
_ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES = _runtime_config._ENV_ENTERPRISE_MAX_WRITE_PAYLOAD_BYTES
_ENV_ENTERPRISE_POLICY_VERSION = _runtime_config._ENV_ENTERPRISE_POLICY_VERSION
_ENV_ENTERPRISE_PRIMARY_KEY_ID = _runtime_config._ENV_ENTERPRISE_PRIMARY_KEY_ID
_ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON = _runtime_config._ENV_ENTERPRISE_PRIVILEGED_READ_RULES_JSON
_ENV_ENTERPRISE_SECRET_ROTATION_DAYS = _runtime_config._ENV_ENTERPRISE_SECRET_ROTATION_DAYS
_ENV_SWITCH_DISABLED_DEFAULT = _runtime_config._ENV_SWITCH_DISABLED_DEFAULT
_MISSING_POLICY_VERSION_ISSUE = _runtime_config._MISSING_POLICY_VERSION_ISSUE
_MISSING_PRIMARY_KEY_ID_ISSUE = _runtime_config._MISSING_PRIMARY_KEY_ID_ISSUE
_RUNTIME_CONFIG_INVALID_PREFIX = _runtime_config._RUNTIME_CONFIG_INVALID_PREFIX
_SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE = _runtime_config._SECRET_ROTATION_DAYS_OUT_OF_RANGE_ISSUE
_configured_enterprise_policy_version = _runtime_config._configured_enterprise_policy_version
_empty_json_map = _runtime_config._empty_json_map
_enterprise_runtime_config_issues = _runtime_config._enterprise_runtime_config_issues
_env_enabled = _runtime_config._env_enabled
_env_int = _runtime_config._env_int
_env_value = _runtime_config._env_value
_load_json_map = _runtime_config._load_json_map
_max_write_payload_bytes = _runtime_config._max_write_payload_bytes
_normalized_enterprise_policy_version = _runtime_config._normalized_enterprise_policy_version
_parse_int_or_default = _runtime_config._parse_int_or_default
_primary_key_configured = _runtime_config._primary_key_configured
_privileged_read_authz_enabled = _runtime_config._privileged_read_authz_enabled
_runtime_config_enforcement_enabled = _runtime_config._runtime_config_enforcement_enabled
_runtime_config_invalid_message = _runtime_config._runtime_config_invalid_message
_write_authz_enabled = _runtime_config._write_authz_enabled
enterprise_policy_version = _runtime_config.enterprise_policy_version
validate_enterprise_runtime_config = _runtime_config.validate_enterprise_runtime_config
_dict_value = _feature_flags._dict_value
_feature_flag_enabled = _feature_flags._feature_flag_enabled
is_feature_enabled = _feature_flags.is_feature_enabled
load_feature_flags = _feature_flags.load_feature_flags
_CAPABILITY_OPERATIONS_RUNTIME_MANAGE = _capability_rules._CAPABILITY_OPERATIONS_RUNTIME_MANAGE
_CAPABILITY_OPERATIONS_RUNTIME_READ = _capability_rules._CAPABILITY_OPERATIONS_RUNTIME_READ
_CAPABILITY_RULE_METHOD_PATH_SEPARATOR = _capability_rules._CAPABILITY_RULE_METHOD_PATH_SEPARATOR
_DEFAULT_CAPABILITY_RULES = _capability_rules._DEFAULT_CAPABILITY_RULES
_DEFAULT_PRIVILEGED_READ_RULES = _capability_rules._DEFAULT_PRIVILEGED_READ_RULES
_HTTP_METHOD_DELETE = _capability_rules._HTTP_METHOD_DELETE
_HTTP_METHOD_GET = _capability_rules._HTTP_METHOD_GET
_HTTP_METHOD_PATCH = _capability_rules._HTTP_METHOD_PATCH
_HTTP_METHOD_POST = _capability_rules._HTTP_METHOD_POST
_HTTP_METHOD_PUT = _capability_rules._HTTP_METHOD_PUT
_PATH_RECOVERY_DRILL_RUN = _capability_rules._PATH_RECOVERY_DRILL_RUN
_PATH_RECOVERY_DRILLS = _capability_rules._PATH_RECOVERY_DRILLS
_PATH_RUNTIME_RECOVERIES = _capability_rules._PATH_RUNTIME_RECOVERIES
_PATH_RUNTIME_RETENTION_CLEANUP_RUN = _capability_rules._PATH_RUNTIME_RETENTION_CLEANUP_RUN
_PATH_RUNTIME_RETENTION_CLEANUPS = _capability_rules._PATH_RUNTIME_RETENTION_CLEANUPS
_PATH_RUNTIME_STATUS = _capability_rules._PATH_RUNTIME_STATUS
_PATH_RUNTIME_WORK_ITEMS = _capability_rules._PATH_RUNTIME_WORK_ITEMS
_RULE_RECOVERY_DRILL_RUN_WRITE = _capability_rules._RULE_RECOVERY_DRILL_RUN_WRITE
_RULE_RECOVERY_DRILLS_READ = _capability_rules._RULE_RECOVERY_DRILLS_READ
_RULE_RUNTIME_RECOVERIES_READ = _capability_rules._RULE_RUNTIME_RECOVERIES_READ
_RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE = _capability_rules._RULE_RUNTIME_RETENTION_CLEANUP_RUN_WRITE
_RULE_RUNTIME_RETENTION_CLEANUPS_READ = _capability_rules._RULE_RUNTIME_RETENTION_CLEANUPS_READ
_RULE_RUNTIME_STATUS_READ = _capability_rules._RULE_RUNTIME_STATUS_READ
_RULE_RUNTIME_WORK_ITEMS_READ = _capability_rules._RULE_RUNTIME_WORK_ITEMS_READ
_WRITE_METHODS = _capability_rules._WRITE_METHODS
_capability_rule_key = _capability_rules._capability_rule_key
_capability_rule_path_for_method = _capability_rules._capability_rule_path_for_method
_is_privileged_read_method = _capability_rules._is_privileged_read_method
_is_write_method = _capability_rules._is_write_method
_load_capability_rule_family = _capability_rules._load_capability_rule_family
_normalized_capability_rule_overrides = _capability_rules._normalized_capability_rule_overrides
_normalized_http_method = _capability_rules._normalized_http_method
_path_matches_rule = _capability_rules._path_matches_rule
_required_capability = _capability_rules._required_capability
_required_capability_from_rules = _capability_rules._required_capability_from_rules
_required_privileged_read_capability = _capability_rules._required_privileged_read_capability
load_capability_rules = _capability_rules.load_capability_rules
load_privileged_read_rules = _capability_rules.load_privileged_read_rules
_ACTOR_ID_HEADER = _request_context._ACTOR_ID_HEADER
_AUDIT_PAYLOAD_ACTOR_ID_KEY = _request_context._AUDIT_PAYLOAD_ACTOR_ID_KEY
_AUDIT_PAYLOAD_CORRELATION_ID_KEY = _request_context._AUDIT_PAYLOAD_CORRELATION_ID_KEY
_AUDIT_PAYLOAD_ROLE_KEY = _request_context._AUDIT_PAYLOAD_ROLE_KEY
_AUDIT_PAYLOAD_TENANT_ID_KEY = _request_context._AUDIT_PAYLOAD_TENANT_ID_KEY
_AUTHORIZATION_HEADER = _request_context._AUTHORIZATION_HEADER
_CAPABILITIES_HEADER = _request_context._CAPABILITIES_HEADER
_CORRELATION_ID_HEADER = _request_context._CORRELATION_ID_HEADER
_DEFAULT_TENANT_ID = _request_context._DEFAULT_TENANT_ID
_EMPTY_AUDIT_CORRELATION_ID = _request_context._EMPTY_AUDIT_CORRELATION_ID
_HEADER_CAPABILITY_SEPARATOR = _request_context._HEADER_CAPABILITY_SEPARATOR
_REQUIRED_HEADERS = _request_context._REQUIRED_HEADERS
_ROLE_HEADER = _request_context._ROLE_HEADER
_SERVICE_IDENTITY_HEADER = _request_context._SERVICE_IDENTITY_HEADER
_TENANT_ID_HEADER = _request_context._TENANT_ID_HEADER
_UNKNOWN_ACTOR_ID = _request_context._UNKNOWN_ACTOR_ID
_UNKNOWN_ROLE = _request_context._UNKNOWN_ROLE
_audit_identity_from_headers = _request_context._audit_identity_from_headers
_has_required_capability = _request_context._has_required_capability
_has_service_identity = _request_context._has_service_identity
_header_capabilities = _request_context._header_capabilities
_missing_required_headers = _request_context._missing_required_headers
_normalized_headers = _request_context._normalized_headers
_REDACTED_VALUE = _audit_redaction._REDACTED_VALUE
_REDACT_FIELDS = _audit_redaction._REDACT_FIELDS
_normalized_redaction_field = _audit_redaction._normalized_redaction_field
_redacted_mapping = _audit_redaction._redacted_mapping
_redacted_mapping_value = _audit_redaction._redacted_mapping_value
_redacted_sequence = _audit_redaction._redacted_sequence
_should_redact_field = _audit_redaction._should_redact_field
redact_sensitive = _audit_redaction.redact_sensitive

logger = logging.getLogger("enterprise_readiness")

_SERVICE_NAME = "lotus-performance"
_ENTERPRISE_AUDIT_EVENT_NAME = "enterprise_audit_event"
_ENTERPRISE_AUDIT_EXTRA_KEY = "audit"
_ENTERPRISE_POLICY_VERSION_HEADER = "X-Enterprise-Policy-Version"
_AUDIT_PAYLOAD_SERVICE_KEY = "service"
_AUDIT_PAYLOAD_ACTION_KEY = "action"
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
_MISSING_HEADERS_REASON = "missing_headers"
_MISSING_SERVICE_IDENTITY_REASON = "missing_service_identity"
_MISSING_CAPABILITY_REASON = "missing_capability"
_CONTENT_LENGTH_HEADER = "content-length"
_MISSING_CONTENT_LENGTH = "0"


def _governed_surface_for_capability(*, path: str, required_capability: str | None) -> str | None:
    return path if required_capability is not None else None


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
    return correlation_id or _EMPTY_AUDIT_CORRELATION_ID


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
