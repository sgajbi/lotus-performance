from __future__ import annotations

from app.observability import correlation_id_var, request_id_var, trace_id_var

ASYNC_OBSERVABILITY_CONTEXT_FIELD = "observability_context"


def _nonblank_context_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def current_async_observability_context() -> dict[str, str]:
    context = {
        "correlation_id": _nonblank_context_value(correlation_id_var.get()),
        "request_id": _nonblank_context_value(request_id_var.get()),
        "trace_id": _nonblank_context_value(trace_id_var.get()),
    }
    return {field: value for field, value in context.items() if value is not None}


def async_observability_request_payload(payload: dict[str, object]) -> dict[str, object]:
    observability_context = current_async_observability_context()
    if not observability_context:
        return payload
    return {
        **payload,
        ASYNC_OBSERVABILITY_CONTEXT_FIELD: observability_context,
    }
