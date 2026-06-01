from typing import Any

from app.enterprise_audit_events import (
    _AUDIT_ACCESS_MODE_PRIVILEGED_READ,
    _AUDIT_ACCESS_MODE_WRITE,
    _AUDIT_METADATA_ACCESS_MODE_KEY,
    _AUDIT_METADATA_GOVERNED_SURFACE_KEY,
    _AUDIT_METADATA_REQUIRED_CAPABILITY_KEY,
    _AUDIT_METADATA_STATUS_CODE_KEY,
)
from app.enterprise_capability_rules import (
    _is_privileged_read_method,
    _is_write_method,
    _required_capability,
    _required_privileged_read_capability,
)
from app.enterprise_request_context import (
    _has_required_capability,
    _has_service_identity,
    _missing_required_headers,
    _normalized_headers,
)
from app.enterprise_response_envelopes import _RESPONSE_REASON_KEY
from app.enterprise_runtime_config import (
    _DIAGNOSTIC_LIST_SEPARATOR,
    _privileged_read_authz_enabled,
    _write_authz_enabled,
)

_MISSING_HEADERS_REASON = "missing_headers"
_MISSING_SERVICE_IDENTITY_REASON = "missing_service_identity"
_MISSING_CAPABILITY_REASON = "missing_capability"


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


def _authorization_denial_metadata(reason: str | None) -> dict[str, str | None]:
    return {_RESPONSE_REASON_KEY: reason}


def _request_action(*, method: str, path: str) -> str:
    return f"{method} {path}"


def _denied_request_action(*, method: str, path: str) -> str:
    return f"DENY {_request_action(method=method, path=path)}"


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
