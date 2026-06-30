from __future__ import annotations

from core.errors import APIError


def execution_stage_failure_detail(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if detail is None:
        return str(exc)
    return str(detail)


def is_mappable_application_error(exc: Exception) -> bool:
    return isinstance(exc, APIError) or (isinstance(getattr(exc, "status_code", None), int) and hasattr(exc, "detail"))
