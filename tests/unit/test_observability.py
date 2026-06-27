import json
import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest
from starlette.routing import Match

import app.observability as observability
from app.observability import (
    JsonFormatter,
    _bounded_metric_label,
    _bounded_mwr_solver_outcome_labels,
    _bounded_mwr_solver_reason_codes,
    _included_router_route_name,
    _instrumentator_route_name,
    _json_log_payload,
    _log_context_fields,
    _matched_route_name,
    _matching_effective_candidate_path,
    _patch_instrumentator_route_name_resolution,
    _propagation_correlation_id,
    _propagation_request_id,
    _propagation_trace_id,
    _register_queue_collector_once,
    _route_matches,
    _trace_id_from_traceparent,
    build_access_log_fields,
    correlation_id_var,
    propagation_headers,
    record_analytics_freshness_bucket,
    record_calculation_supportability,
    record_mwr_solver_outcome,
    request_id_var,
    resolve_correlation_id,
    resolve_request_id,
    resolve_trace_id,
    setup_logging,
    setup_observability,
    source_product_correlation_id,
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


def test_propagation_id_helpers_apply_override_context_and_generated_fallbacks():
    correlation_id_var.set(" corr-ctx ")
    request_id_var.set(" ")
    trace_id_var.set(" ")

    assert _propagation_correlation_id(" corr-override ") == "corr-override"
    assert _propagation_correlation_id(" ") == "corr-ctx"
    assert _propagation_request_id().startswith("req_")
    assert len(_propagation_trace_id()) == 32


def test_source_product_correlation_id_uses_current_context_value():
    correlation_id_var.set(" corr-source ")

    assert source_product_correlation_id() == "corr-source"


def test_setup_logging_replaces_existing_handlers_with_json_formatter():
    root_logger = logging.getLogger()
    root_logger.addHandler(logging.NullHandler())

    setup_logging("warning")

    assert root_logger.level == logging.WARNING
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0].formatter, JsonFormatter)

    root_logger.handlers.clear()
    setup_logging("info")

    assert root_logger.level == logging.INFO
    assert len(root_logger.handlers) == 1
    assert isinstance(root_logger.handlers[0].formatter, JsonFormatter)


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


def test_setup_observability_adds_request_headers_and_resets_context(monkeypatch):
    class InstrumentatorStub:
        def instrument(self, app):
            return self

        def expose(self, app):
            return self

    monkeypatch.setattr(observability, "Instrumentator", InstrumentatorStub)
    monkeypatch.setattr(observability, "_register_queue_collector_once", lambda: None)

    app = FastAPI()
    setup_observability(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "correlation_id": correlation_id_var.get(),
            "request_id": request_id_var.get(),
            "trace_id": trace_id_var.get(),
        }

    correlation_id_var.set("outer-correlation")
    request_id_var.set("outer-request")
    trace_id_var.set("outer-trace")

    response = TestClient(app).get(
        "/health",
        headers={
            "X-Correlation-Id": "corr-inbound",
            "X-Request-Id": "req-inbound",
            "traceparent": "00-0123456789abcdef0123456789abcdef-0000000000000001-01",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "correlation_id": "corr-inbound",
        "request_id": "req-inbound",
        "trace_id": "0123456789abcdef0123456789abcdef",
    }
    assert response.headers["X-Correlation-Id"] == "corr-inbound"
    assert response.headers["X-Request-Id"] == "req-inbound"
    assert response.headers["X-Trace-Id"] == "0123456789abcdef0123456789abcdef"
    assert response.headers["traceparent"] == "00-0123456789abcdef0123456789abcdef-0000000000000001-01"
    assert correlation_id_var.get() == "outer-correlation"
    assert request_id_var.get() == "outer-request"
    assert trace_id_var.get() == "outer-trace"


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


def test_instrumentator_route_name_falls_back_when_original_resolver_rejects_request(monkeypatch):
    def broken_resolver(request):
        raise AttributeError("included router candidate does not expose path")

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
    monkeypatch.setattr(observability, "_ORIGINAL_INSTRUMENTATOR_ROUTE_NAME_RESOLVER", broken_resolver)

    assert _instrumentator_route_name(request) == "/api/items/{item_id}"


def test_matched_route_name_returns_route_path_only_for_full_matches():
    class RouteStub:
        path = "/api/items/{item_id}"

        def __init__(self, match_result):
            self.match_result = match_result

        def matches(self, scope):
            return self.match_result, scope

    assert _matched_route_name(RouteStub(Match.FULL), {"path": "/api/items/123"}) == "/api/items/{item_id}"
    assert _matched_route_name(RouteStub(Match.PARTIAL), {"path": "/api/items/123"}) is None


def test_included_router_route_name_returns_none_when_no_routes_match():
    app = FastAPI()
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/missing",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": app,
        }
    )

    assert _included_router_route_name(request) is None


def test_matched_route_name_uses_matching_effective_candidate_path():
    class CandidateStub:
        path = "/api/items/{item_id}"

        def __init__(self, match_result):
            self.match_result = match_result

        def matches(self, scope):
            return self.match_result, scope

    class RouteStub:
        path = None
        path_format = None

        def matches(self, scope):
            return Match.FULL, scope

        def effective_candidates(self):
            return [CandidateStub(Match.PARTIAL), CandidateStub(Match.FULL)]

    assert _matched_route_name(RouteStub(), {"path": "/api/items/123"}) == "/api/items/{item_id}"


def test_matching_effective_candidate_path_returns_none_without_callable_candidates():
    class RouteStub:
        effective_candidates = ["not-callable"]

    assert _matching_effective_candidate_path(RouteStub(), {"path": "/api/items/123"}) is None


def test_matching_effective_candidate_path_returns_none_without_full_candidate_match():
    class CandidateStub:
        path = "/api/items/{item_id}"

        def matches(self, scope):
            return Match.PARTIAL, scope

    class RouteStub:
        def effective_candidates(self):
            return [CandidateStub()]

    assert _matching_effective_candidate_path(RouteStub(), {"path": "/api/items/123"}) is None


def test_route_matches_returns_none_for_non_route_objects():
    assert _route_matches(object(), {"path": "/api/items/123"}) == Match.NONE


def test_patch_instrumentator_route_name_resolution_installs_safe_resolver():
    _patch_instrumentator_route_name_resolution()

    assert observability.instrumentator_routing.get_route_name is _instrumentator_route_name


def test_register_queue_collector_once_skips_existing_collector(monkeypatch):
    class RegistryStub:
        _collector_to_names = {observability.DurableQueueCollector(): []}

        def register(self, collector):
            raise AssertionError("collector should already be registered")

    monkeypatch.setattr(observability, "REGISTRY", RegistryStub())

    _register_queue_collector_once()


def test_register_queue_collector_once_registers_when_missing(monkeypatch):
    registered = []

    class RegistryStub:
        _collector_to_names = {}

        def register(self, collector):
            registered.append(collector)

    monkeypatch.setattr(observability, "REGISTRY", RegistryStub())

    _register_queue_collector_once()

    assert len(registered) == 1
    assert isinstance(registered[0], observability.DurableQueueCollector)


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


def test_record_calculation_supportability_and_freshness_metrics_use_bounded_label_families():
    record_calculation_supportability(
        operation="twr_calculation",
        supportability_state="supported",
        reason="fresh",
        freshness_bucket="fresh",
    )
    record_analytics_freshness_bucket(
        operation="returns_series",
        supportability_state="degraded",
        freshness_bucket="stale",
    )

    metrics_text = generate_latest(REGISTRY).decode("utf-8")

    assert (
        'lotus_performance_calculation_supportability_total{freshness_bucket="fresh",operation="twr_calculation",'
        'reason="fresh",supportability_state="supported"}' in metrics_text
    )
    assert (
        'lotus_analytics_freshness_bucket_total{freshness_bucket="stale",operation="returns_series",'
        'service="lotus-performance",supportability_state="degraded"}' in metrics_text
    )


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
