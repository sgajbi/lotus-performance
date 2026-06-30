from __future__ import annotations


def execution_stage_failure_detail(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if detail is None:
        return str(exc)
    return str(detail)
