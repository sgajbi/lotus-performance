import json
import logging
import os
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from prometheus_client import REGISTRY, Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.services.queue_metrics_service import DurableQueueCollector

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

PERFORMANCE_CALCULATION_SUPPORTABILITY_TOTAL = Counter(
    "lotus_performance_calculation_supportability_total",
    "Performance calculation supportability posture by operation, bounded reason, and freshness bucket.",
    ["operation", "supportability_state", "reason", "freshness_bucket"],
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": os.getenv("SERVICE_NAME", "lotus-performance"),
            "environment": os.getenv("ENVIRONMENT", "local"),
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get() or None,
            "request_id": request_id_var.get() or None,
            "trace_id": trace_id_var.get() or None,
        }
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            payload.update(record.extra_fields)
        return json.dumps({k: v for k, v in payload.items() if v is not None})


def setup_logging(log_level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.setLevel(log_level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)


def resolve_correlation_id(request: Request) -> str:
    incoming = request.headers.get("X-Correlation-Id") or request.headers.get("X-Correlation-ID")
    return incoming if incoming else f"corr_{uuid4().hex[:12]}"


def resolve_request_id(request: Request) -> str:
    incoming = request.headers.get("X-Request-Id")
    return incoming if incoming else f"req_{uuid4().hex[:12]}"


def resolve_trace_id(request: Request) -> str:
    traceparent = request.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 4 and len(parts[1]) == 32:
            return parts[1]
    incoming = request.headers.get("X-Trace-Id")
    return incoming if incoming else uuid4().hex


def propagation_headers(correlation_id: str | None = None) -> dict[str, str]:
    trace_id = trace_id_var.get() or uuid4().hex
    return {
        "X-Correlation-Id": correlation_id or correlation_id_var.get() or f"corr_{uuid4().hex[:12]}",
        "X-Request-Id": request_id_var.get() or f"req_{uuid4().hex[:12]}",
        "X-Trace-Id": trace_id,
        "traceparent": f"00-{trace_id}-0000000000000001-01",
    }


def record_calculation_supportability(
    *,
    operation: str,
    supportability_state: str,
    reason: str,
    freshness_bucket: str,
) -> None:
    PERFORMANCE_CALCULATION_SUPPORTABILITY_TOTAL.labels(
        operation=operation,
        supportability_state=supportability_state,
        reason=reason,
        freshness_bucket=freshness_bucket,
    ).inc()


def build_access_log_fields(*, request: Request, duration_ms: float) -> dict[str, str | float]:
    """Builds standard access-log fields expected by Lotus platform QA checks."""
    return {
        "http_method": request.method,
        "endpoint": request.url.path,
        "duration_ms": duration_ms,
        # Keep legacy key for backwards compatibility with existing log consumers.
        "latency_ms": duration_ms,
    }


def setup_observability(app: FastAPI, *, log_level: str = "INFO") -> None:
    setup_logging(log_level)
    _register_queue_collector_once()
    Instrumentator().instrument(app).expose(app)

    @app.middleware("http")
    async def _request_observability_middleware(request: Request, call_next):
        logger = logging.getLogger("http.access")
        started = time.perf_counter()

        correlation_id = resolve_correlation_id(request)
        request_id = resolve_request_id(request)
        trace_id = resolve_trace_id(request)

        correlation_token = correlation_id_var.set(correlation_id)
        request_token = request_id_var.set(request_id)
        trace_token = trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request.completed",
                extra={"extra_fields": build_access_log_fields(request=request, duration_ms=duration_ms)},
            )
            correlation_id_var.reset(correlation_token)
            request_id_var.reset(request_token)
            trace_id_var.reset(trace_token)

        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        response.headers["traceparent"] = f"00-{trace_id}-0000000000000001-01"
        return response


def _register_queue_collector_once() -> None:
    if any(isinstance(collector, DurableQueueCollector) for collector in list(REGISTRY._collector_to_names)):
        return
    REGISTRY.register(DurableQueueCollector())
