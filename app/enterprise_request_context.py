from typing import Any, Mapping

_AUDIT_PAYLOAD_ACTOR_ID_KEY = "actor_id"
_AUDIT_PAYLOAD_TENANT_ID_KEY = "tenant_id"
_AUDIT_PAYLOAD_ROLE_KEY = "role"
_AUDIT_PAYLOAD_CORRELATION_ID_KEY = "correlation_id"
_EMPTY_AUDIT_CORRELATION_ID = ""
_CAPABILITIES_HEADER = "x-capabilities"
_SERVICE_IDENTITY_HEADER = "x-service-identity"
_AUTHORIZATION_HEADER = "authorization"
_HEADER_CAPABILITY_SEPARATOR = ","
_ACTOR_ID_HEADER = "x-actor-id"
_TENANT_ID_HEADER = "x-tenant-id"
_ROLE_HEADER = "x-role"
_CORRELATION_ID_HEADER = "x-correlation-id"
_UNKNOWN_ACTOR_ID = "unknown"
_DEFAULT_TENANT_ID = "default"
_UNKNOWN_ROLE = "unknown"
_REQUIRED_HEADERS = {_ACTOR_ID_HEADER, _TENANT_ID_HEADER, _ROLE_HEADER, _CORRELATION_ID_HEADER}


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
        _AUDIT_PAYLOAD_CORRELATION_ID_KEY: normalized.get(
            _CORRELATION_ID_HEADER,
            _EMPTY_AUDIT_CORRELATION_ID,
        ),
    }
