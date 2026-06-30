from app.observability import correlation_id_var, request_id_var, trace_id_var
from app.services.async_observability_context import (
    ASYNC_OBSERVABILITY_CONTEXT_FIELD,
    async_observability_request_payload,
    current_async_observability_context,
)


def test_current_async_observability_context_trims_and_omits_blank_values():
    correlation_token = correlation_id_var.set(" corr-1 ")
    request_token = request_id_var.set(" ")
    trace_token = trace_id_var.set(" trace-1 ")

    try:
        context = current_async_observability_context()
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert context == {
        "correlation_id": "corr-1",
        "trace_id": "trace-1",
    }


def test_async_observability_request_payload_adds_transient_context_when_present():
    correlation_token = correlation_id_var.set("corr-2")
    request_token = request_id_var.set("req-2")
    trace_token = trace_id_var.set("trace-2")

    try:
        payload = async_observability_request_payload({"portfolio_id": "P1"})
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert payload == {
        "portfolio_id": "P1",
        ASYNC_OBSERVABILITY_CONTEXT_FIELD: {
            "correlation_id": "corr-2",
            "request_id": "req-2",
            "trace_id": "trace-2",
        },
    }


def test_async_observability_request_payload_preserves_payload_when_context_absent():
    correlation_token = correlation_id_var.set("")
    request_token = request_id_var.set("")
    trace_token = trace_id_var.set("")
    original_payload = {"portfolio_id": "P1"}

    try:
        payload = async_observability_request_payload(original_payload)
    finally:
        correlation_id_var.reset(correlation_token)
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)

    assert payload is original_payload
