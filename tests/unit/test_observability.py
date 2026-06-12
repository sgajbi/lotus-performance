import json
import logging

from fastapi import Request
from prometheus_client import REGISTRY, generate_latest

from app.observability import (
    JsonFormatter,
    _json_log_payload,
    build_access_log_fields,
    correlation_id_var,
    propagation_headers,
    record_mwr_solver_outcome,
    request_id_var,
    resolve_correlation_id,
    resolve_request_id,
    resolve_trace_id,
    trace_id_var,
)


def _request_with_headers(headers: dict[str, str]) -> Request:
    asgi_headers = [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in headers.items()]
    scope = {"type": "http", "headers": asgi_headers}
    return Request(scope)


def test_resolve_correlation_id_primary_and_alias():
    assert resolve_correlation_id(_request_with_headers({"X-Correlation-Id": " corr-1 "})) == "corr-1"
    assert resolve_correlation_id(_request_with_headers({"X-Correlation-ID": " corr-2 "})) == "corr-2"


def test_resolve_correlation_id_generates_when_blank():
    value = resolve_correlation_id(_request_with_headers({"X-Correlation-Id": "  "}))
    assert value.startswith("corr_")


def test_resolve_request_id_trims_and_generates_when_missing_or_blank():
    assert resolve_request_id(_request_with_headers({"X-Request-Id": " req-1 "})) == "req-1"
    value = resolve_request_id(_request_with_headers({"X-Request-Id": "  "}))
    assert value.startswith("req_")


def test_resolve_trace_id_prefers_traceparent_then_header_then_generated():
    traceparent_value = " 00-0123456789abcdef0123456789abcdef-0000000000000001-01 "
    assert resolve_trace_id(_request_with_headers({"traceparent": traceparent_value})) == (
        "0123456789abcdef0123456789abcdef"
    )
    assert resolve_trace_id(_request_with_headers({"traceparent": "invalid", "X-Trace-Id": " trace-1 "})) == "trace-1"
    generated = resolve_trace_id(_request_with_headers({"traceparent": "invalid", "X-Trace-Id": "  "}))
    assert len(generated) == 32


def test_propagation_headers_use_context_values():
    correlation_id_var.set(" corr-ctx ")
    request_id_var.set(" req-ctx ")
    trace_id_var.set(" 0123456789abcdef0123456789abcdef ")
    headers = propagation_headers(correlation_id=" corr-override ")
    assert headers["X-Correlation-Id"] == "corr-override"
    assert headers["X-Request-Id"] == "req-ctx"
    assert headers["traceparent"] == "00-0123456789abcdef0123456789abcdef-0000000000000001-01"

    headers = propagation_headers()
    assert headers["X-Correlation-Id"] == "corr-ctx"
    assert headers["X-Request-Id"] == "req-ctx"
    assert headers["traceparent"] == "00-0123456789abcdef0123456789abcdef-0000000000000001-01"


def test_propagation_headers_generates_when_context_absent():
    correlation_id_var.set(" ")
    request_id_var.set(" ")
    trace_id_var.set(" ")
    headers = propagation_headers()
    assert headers["X-Correlation-Id"].startswith("corr_")
    assert headers["X-Request-Id"].startswith("req_")
    assert len(headers["X-Trace-Id"]) == 32


def test_json_formatter_includes_standard_and_extra_fields(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "lotus-performance-test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    correlation_id_var.set("corr-log")
    request_id_var.set("req-log")
    trace_id_var.set("trace-log")

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="unit.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="log-message",
        args=(),
        exc_info=None,
    )
    record.extra_fields = {"endpoint": "/health", "duration_ms": 12.3}
    payload = json.loads(formatter.format(record))
    assert payload["service"] == "lotus-performance-test"
    assert payload["environment"] == "test"
    assert payload["message"] == "log-message"
    assert payload["endpoint"] == "/health"
    assert payload["duration_ms"] == 12.3


def test_json_log_payload_filters_empty_context_and_ignores_non_dict_extra_fields():
    correlation_id_var.set("")
    request_id_var.set("")
    trace_id_var.set("")

    record = logging.LogRecord(
        name="unit.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="log-message",
        args=(),
        exc_info=None,
    )
    record.extra_fields = ["ignored"]

    payload = _json_log_payload(record)

    assert payload["service"] == "lotus-performance"
    assert payload["environment"] == "local"
    assert payload["message"] == "log-message"
    assert "correlation_id" not in payload
    assert "request_id" not in payload
    assert "trace_id" not in payload
    assert "extra_fields" not in payload


def test_build_access_log_fields_contains_platform_duration_and_legacy_latency():
    request = _request_with_headers({"host": "testserver"})
    request.scope["method"] = "GET"
    request.scope["path"] = "/health"

    fields = build_access_log_fields(request=request, duration_ms=10.5)

    assert fields["http_method"] == "GET"
    assert fields["endpoint"] == "/health"
    assert fields["duration_ms"] == 10.5
    assert fields["latency_ms"] == 10.5


def test_record_mwr_solver_outcome_uses_bounded_support_safe_labels():
    record_mwr_solver_outcome(
        input_mode="stateful",
        method="MODIFIED_DIETZ",
        status="FALLBACK_USED",
        reason_codes=["MULTIPLE_IRR_ROOTS_DETECTED"],
        fallback_used=True,
    )
    record_mwr_solver_outcome(
        input_mode="portfolio-123",
        method="CUSTOM",
        status="SURPRISE",
        reason_codes=["portfolio-123"],
        fallback_used=False,
    )

    metrics_text = generate_latest(REGISTRY).decode("utf-8")

    assert (
        'lotus_performance_mwr_solver_outcome_total{fallback_used="true",input_mode="stateful",'
        'method="MODIFIED_DIETZ",reason_code="MULTIPLE_IRR_ROOTS_DETECTED",status="FALLBACK_USED"}' in metrics_text
    )
    assert (
        'lotus_performance_mwr_solver_outcome_total{fallback_used="false",input_mode="other",'
        'method="OTHER",reason_code="OTHER",status="OTHER"}' in metrics_text
    )
