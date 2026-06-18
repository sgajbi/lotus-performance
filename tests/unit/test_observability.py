import json
import logging

from fastapi import APIRouter, FastAPI, Request
from prometheus_client import REGISTRY, generate_latest

from app.observability import (
    JsonFormatter,
    _bounded_metric_label,
    _bounded_mwr_solver_outcome_labels,
    _bounded_mwr_solver_reason_codes,
    _instrumentator_route_name,
    _json_log_payload,
    _log_context_fields,
    _trace_id_from_traceparent,
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


def test_trace_id_from_traceparent_accepts_only_traceparent_with_32_character_trace_id():
    assert (
        _trace_id_from_traceparent("00-0123456789abcdef0123456789abcdef-0000000000000001-01")
        == "0123456789abcdef0123456789abcdef"
    )
    assert _trace_id_from_traceparent(None) is None
    assert _trace_id_from_traceparent("  ") is None
    assert _trace_id_from_traceparent("invalid") is None
    assert _trace_id_from_traceparent("00-short-0000000000000001-01") is None


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


def test_log_context_fields_preserves_present_ids_and_normalizes_empty_ids():
    correlation_id_var.set("corr-log")
    request_id_var.set("")
    trace_id_var.set("trace-log")

    assert _log_context_fields() == {
        "correlation_id": "corr-log",
        "request_id": None,
        "trace_id": "trace-log",
    }


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


def test_instrumentator_route_name_resolves_fastapi_included_router_context():
    router = APIRouter()

    @router.get("/items/{item_id}")
    async def read_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    app = FastAPI()
    app.include_router(router, prefix="/api")
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/items/123",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": app,
        }
    )

    assert _instrumentator_route_name(request) == "/api/items/{item_id}"


def test_bounded_mwr_solver_reason_codes_defaults_and_filters_unsafe_values():
    assert _bounded_mwr_solver_reason_codes([]) == ("NONE",)
    assert _bounded_mwr_solver_reason_codes(["NO_ROOT_FOUND", "portfolio-123"]) == ("NO_ROOT_FOUND", "OTHER")


def test_bounded_metric_label_preserves_allowed_values_and_collapses_unsafe_values():
    allowed_values = frozenset({"stateful", "stateless"})

    assert _bounded_metric_label("stateful", allowed_values=allowed_values, fallback="other") == "stateful"
    assert _bounded_metric_label("portfolio-123", allowed_values=allowed_values, fallback="other") == "other"


def test_bounded_mwr_solver_outcome_labels_filter_unsafe_values():
    labels = _bounded_mwr_solver_outcome_labels(
        input_mode="portfolio-123",
        method="CUSTOM",
        status="SURPRISE",
        reason_code="account-456",
        fallback_used=True,
    )

    assert labels == {
        "input_mode": "other",
        "method": "OTHER",
        "status": "OTHER",
        "reason_code": "OTHER",
        "fallback_used": "true",
    }


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
