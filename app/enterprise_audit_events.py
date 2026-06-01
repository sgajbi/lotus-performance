from datetime import datetime, timezone
from typing import Any

from fastapi import Response

from app.enterprise_audit_redaction import redact_sensitive
from app.enterprise_request_context import (
    _AUDIT_PAYLOAD_ACTOR_ID_KEY,
    _AUDIT_PAYLOAD_CORRELATION_ID_KEY,
    _AUDIT_PAYLOAD_ROLE_KEY,
    _AUDIT_PAYLOAD_TENANT_ID_KEY,
    _EMPTY_AUDIT_CORRELATION_ID,
)
from app.enterprise_runtime_config import enterprise_policy_version

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
