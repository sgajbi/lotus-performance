from __future__ import annotations

from core.errors import APIError

_PUBLIC_SUPPORT_SUFFIX = "Use the correlation_id for support."
_PUBLIC_INTERNAL_ERROR_MESSAGE = f"The service encountered an internal error. {_PUBLIC_SUPPORT_SUFFIX}"


def execution_stage_failure_detail(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if detail is None:
        return str(exc)
    return str(detail)


def is_mappable_application_error(exc: Exception) -> bool:
    return isinstance(exc, APIError) or (isinstance(getattr(exc, "status_code", None), int) and hasattr(exc, "detail"))


def public_internal_error_message() -> str:
    return _PUBLIC_INTERNAL_ERROR_MESSAGE


def safe_unexpected_failure_message(operation: str) -> str:
    return f"{operation.strip()} failed unexpectedly. {_PUBLIC_SUPPORT_SUFFIX}"
