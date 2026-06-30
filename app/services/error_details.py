from __future__ import annotations

from typing import Any

from fastapi import status

from app.api.http_status import HTTP_422_UNPROCESSABLE
from app.observability import correlation_id_var, request_id_var

_SOURCE_UNAVAILABLE_CODE = "SOURCE_UNAVAILABLE"
_RESOURCE_NOT_FOUND_CODE = "RESOURCE_NOT_FOUND"
_INSUFFICIENT_DATA_CODE = "INSUFFICIENT_DATA"
_INVALID_REQUEST_CODE = "INVALID_REQUEST"
_UPSTREAM_CONTRACT_VIOLATION_CODE = "CONTRACT_VIOLATION_UPSTREAM"
_CONFLICT_CODE = "CONFLICT"
_VALIDATION_ERROR_CODE = "VALIDATION_ERROR"
_INTERNAL_ERROR_CODE = "INTERNAL_SERVER_ERROR"
_UNAUTHORIZED_CODE = "UNAUTHORIZED"
_FORBIDDEN_CODE = "FORBIDDEN"
_RATE_LIMITED_CODE = "RATE_LIMITED"
_LOTUS_PERFORMANCE_SOURCE = "lotus-performance"
_PUBLIC_INTERNAL_ERROR_MESSAGE = "The service encountered an internal error. Use the correlation_id for support."

_ERROR_CODE_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: _INVALID_REQUEST_CODE,
    status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_CODE,
    status.HTTP_403_FORBIDDEN: _FORBIDDEN_CODE,
    status.HTTP_404_NOT_FOUND: _RESOURCE_NOT_FOUND_CODE,
    status.HTTP_409_CONFLICT: _CONFLICT_CODE,
    HTTP_422_UNPROCESSABLE: _INVALID_REQUEST_CODE,
    status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMITED_CODE,
    status.HTTP_500_INTERNAL_SERVER_ERROR: _INTERNAL_ERROR_CODE,
    status.HTTP_502_BAD_GATEWAY: _SOURCE_UNAVAILABLE_CODE,
    status.HTTP_503_SERVICE_UNAVAILABLE: _SOURCE_UNAVAILABLE_CODE,
    status.HTTP_504_GATEWAY_TIMEOUT: _SOURCE_UNAVAILABLE_CODE,
}

_RETRYABLE_STATUSES = frozenset(
    {
        status.HTTP_408_REQUEST_TIMEOUT,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        status.HTTP_502_BAD_GATEWAY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        status.HTTP_504_GATEWAY_TIMEOUT,
    }
)


def coded_error_detail(
    *,
    code: str,
    message: str,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    remediation_hint: str | None = None,
) -> dict[str, str | bool | int]:
    detail: dict[str, str | bool | int] = {"code": code, "message": message}
    if retryable is not None:
        detail["retryable"] = retryable
    if retry_after_seconds is not None:
        detail["retry_after_seconds"] = retry_after_seconds
    if remediation_hint:
        detail["remediation_hint"] = remediation_hint
    return detail


def source_unavailable_detail(message: str) -> dict[str, str | bool | int]:
    return coded_error_detail(code=_SOURCE_UNAVAILABLE_CODE, message=message, retryable=True)


def resource_not_found_detail(message: str) -> dict[str, str | bool | int]:
    return coded_error_detail(code=_RESOURCE_NOT_FOUND_CODE, message=message)


def insufficient_data_detail(message: str) -> dict[str, str | bool | int]:
    return coded_error_detail(code=_INSUFFICIENT_DATA_CODE, message=message)


def invalid_request_detail(message: str) -> dict[str, str | bool | int]:
    return coded_error_detail(code=_INVALID_REQUEST_CODE, message=message)


def upstream_contract_violation_detail(message: str) -> dict[str, str | bool | int]:
    return coded_error_detail(code=_UPSTREAM_CONTRACT_VIOLATION_CODE, message=message)


def error_code_for_status(status_code: int) -> str:
    return _ERROR_CODE_BY_STATUS.get(status_code, _INTERNAL_ERROR_CODE)


def safe_error_envelope(
    *,
    status_code: int,
    detail: Any,
    error_code: str | None = None,
    message: str | None = None,
    retryable: bool | None = None,
    retry_after_seconds: int | None = None,
    remediation_hint: str | None = None,
) -> dict[str, Any]:
    """Builds the public API error envelope while preserving the legacy detail key."""
    resolved_code = _resolved_error_code(detail=detail, status_code=status_code, error_code=error_code)
    resolved_message = _safe_public_message(
        detail=detail,
        status_code=status_code,
        message=message,
    )
    envelope = {
        "detail": _legacy_detail(detail=detail, status_code=status_code, message=resolved_message),
        "error_code": resolved_code,
        "message": resolved_message,
        "correlation_id": _nonblank_context_value(correlation_id_var.get()),
        "request_id": _nonblank_context_value(request_id_var.get()),
        "source": _LOTUS_PERFORMANCE_SOURCE,
        "retryable": _resolved_retryable(detail=detail, status_code=status_code, retryable=retryable),
        "retry_after_seconds": retry_after_seconds or _optional_int_detail(detail, "retry_after_seconds"),
        "remediation_hint": remediation_hint or _optional_str_detail(detail, "remediation_hint"),
    }
    return {key: value for key, value in envelope.items() if value is not None}


def validation_error_envelope(errors: list[dict[str, Any]]) -> dict[str, Any]:
    envelope = safe_error_envelope(
        status_code=HTTP_422_UNPROCESSABLE,
        detail="Request validation failed.",
        error_code=_VALIDATION_ERROR_CODE,
        message="Request validation failed.",
        retryable=False,
    )
    envelope["validation_errors"] = errors
    return envelope


def _safe_public_message(*, detail: Any, status_code: int, message: str | None) -> str:
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return message or _optional_str_detail(detail, "message") or _PUBLIC_INTERNAL_ERROR_MESSAGE
    return message or _detail_message(detail) or _default_client_error_message(status_code)


def _legacy_detail(*, detail: Any, status_code: int, message: str) -> Any:
    if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        return message
    return detail if detail is not None else message


def _resolved_error_code(*, detail: Any, status_code: int, error_code: str | None) -> str:
    return (
        error_code
        or _optional_str_detail(detail, "error_code")
        or _optional_str_detail(detail, "code")
        or error_code_for_status(status_code)
    )


def _resolved_retryable(*, detail: Any, status_code: int, retryable: bool | None) -> bool:
    if retryable is not None:
        return retryable
    detail_retryable = _optional_bool_detail(detail, "retryable")
    if detail_retryable is not None:
        return detail_retryable
    return status_code in _RETRYABLE_STATUSES


def _detail_message(detail: Any) -> str | None:
    if isinstance(detail, str):
        return detail
    return _optional_str_detail(detail, "message") or _optional_str_detail(detail, "detail")


def _optional_str_detail(detail: Any, key: str) -> str | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get(key)
    if isinstance(value, str):
        return _nonblank_context_value(value)
    return None


def _optional_bool_detail(detail: Any, key: str) -> bool | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get(key)
    return value if isinstance(value, bool) else None


def _optional_int_detail(detail: Any, key: str) -> int | None:
    if not isinstance(detail, dict):
        return None
    value = detail.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _nonblank_context_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _default_client_error_message(status_code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "The request is invalid.",
        status.HTTP_401_UNAUTHORIZED: "Authentication is required.",
        status.HTTP_403_FORBIDDEN: "The caller is not authorized for this operation.",
        status.HTTP_404_NOT_FOUND: "The requested resource was not found.",
        status.HTTP_409_CONFLICT: "The request conflicts with current resource state.",
        HTTP_422_UNPROCESSABLE: "The request could not be processed.",
        status.HTTP_429_TOO_MANY_REQUESTS: "The request rate limit was exceeded.",
    }.get(status_code, "The request failed.")
