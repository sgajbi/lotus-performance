import logging
from typing import Any, Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app import enterprise_audit_events as _audit_events
from app import enterprise_audit_redaction as _audit_redaction
from app import enterprise_authorization as _authorization
from app import enterprise_capability_rules as _capability_rules
from app import enterprise_feature_flags as _feature_flags
from app import enterprise_payload_limits as _payload_limits
from app import enterprise_request_context as _request_context
from app import enterprise_response_envelopes as _response_envelopes
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
_CONTENT_LENGTH_HEADER = _payload_limits._CONTENT_LENGTH_HEADER
_MISSING_CONTENT_LENGTH = _payload_limits._MISSING_CONTENT_LENGTH
_content_length = _payload_limits._content_length
_payload_too_large_response = _payload_limits._payload_too_large_response
_write_payload_too_large = _payload_limits._write_payload_too_large
_AUDIT_ACCESS_MODE_PRIVILEGED_READ = _audit_events._AUDIT_ACCESS_MODE_PRIVILEGED_READ
_AUDIT_ACCESS_MODE_WRITE = _audit_events._AUDIT_ACCESS_MODE_WRITE
_AUDIT_METADATA_ACCESS_MODE_KEY = _audit_events._AUDIT_METADATA_ACCESS_MODE_KEY
_AUDIT_METADATA_GOVERNED_SURFACE_KEY = _audit_events._AUDIT_METADATA_GOVERNED_SURFACE_KEY
_AUDIT_METADATA_REQUIRED_CAPABILITY_KEY = _audit_events._AUDIT_METADATA_REQUIRED_CAPABILITY_KEY
_AUDIT_METADATA_STATUS_CODE_KEY = _audit_events._AUDIT_METADATA_STATUS_CODE_KEY
_AUDIT_PAYLOAD_ACTION_KEY = _audit_events._AUDIT_PAYLOAD_ACTION_KEY
_AUDIT_PAYLOAD_METADATA_KEY = _audit_events._AUDIT_PAYLOAD_METADATA_KEY
_AUDIT_PAYLOAD_POLICY_VERSION_KEY = _audit_events._AUDIT_PAYLOAD_POLICY_VERSION_KEY
_AUDIT_PAYLOAD_SERVICE_KEY = _audit_events._AUDIT_PAYLOAD_SERVICE_KEY
_AUDIT_PAYLOAD_TIMESTAMP_UTC_KEY = _audit_events._AUDIT_PAYLOAD_TIMESTAMP_UTC_KEY
_ENTERPRISE_AUDIT_EVENT_NAME = _audit_events._ENTERPRISE_AUDIT_EVENT_NAME
_ENTERPRISE_AUDIT_EXTRA_KEY = _audit_events._ENTERPRISE_AUDIT_EXTRA_KEY
_ENTERPRISE_POLICY_VERSION_HEADER = _audit_events._ENTERPRISE_POLICY_VERSION_HEADER
_SERVICE_NAME = _audit_events._SERVICE_NAME
_apply_enterprise_policy_header = _audit_events._apply_enterprise_policy_header
_audit_correlation_id = _audit_events._audit_correlation_id
_audit_event_payload = _audit_events._audit_event_payload
_audit_metadata = _audit_events._audit_metadata
_audit_timestamp_utc = _audit_events._audit_timestamp_utc
_MISSING_CAPABILITY_REASON = _authorization._MISSING_CAPABILITY_REASON
_MISSING_HEADERS_REASON = _authorization._MISSING_HEADERS_REASON
_MISSING_SERVICE_IDENTITY_REASON = _authorization._MISSING_SERVICE_IDENTITY_REASON
_allowed_audit_metadata = _authorization._allowed_audit_metadata
_authorization_allowed = _authorization._authorization_allowed
_authorization_denial_metadata = _authorization._authorization_denial_metadata
_authorization_denied = _authorization._authorization_denied
_authorize_enterprise_request = _authorization._authorize_enterprise_request
_authorize_with_required_capability = _authorization._authorize_with_required_capability
_denied_request_action = _authorization._denied_request_action
_governed_surface_for_capability = _authorization._governed_surface_for_capability
_missing_capability_reason = _authorization._missing_capability_reason
_missing_headers_reason = _authorization._missing_headers_reason
_request_action = _authorization._request_action
authorize_privileged_read_request = _authorization.authorize_privileged_read_request
authorize_write_request = _authorization.authorize_write_request
_AUTHORIZATION_POLICY_DENIED_DETAIL = _response_envelopes._AUTHORIZATION_POLICY_DENIED_DETAIL
_HTTP_STATUS_FORBIDDEN = _response_envelopes._HTTP_STATUS_FORBIDDEN
_HTTP_STATUS_PAYLOAD_TOO_LARGE = _response_envelopes._HTTP_STATUS_PAYLOAD_TOO_LARGE
_PAYLOAD_TOO_LARGE_DETAIL = _response_envelopes._PAYLOAD_TOO_LARGE_DETAIL
_RESPONSE_DETAIL_KEY = _response_envelopes._RESPONSE_DETAIL_KEY
_RESPONSE_REASON_KEY = _response_envelopes._RESPONSE_REASON_KEY
_authorization_denied_response_envelope = _response_envelopes._authorization_denied_response_envelope

logger = logging.getLogger("enterprise_readiness")


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
    return _authorization_denied_response_envelope(reason)


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
