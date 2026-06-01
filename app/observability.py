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

from app.observability_contracts import (
    PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS,
    PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
    PERFORMANCE_MWR_SOLVER_OUTCOME_METRIC_LABELS,
)
from app.services.queue_metrics_service import DurableQueueCollector

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

PERFORMANCE_CALCULATION_SUPPORTABILITY_TOTAL = Counter(
    "lotus_performance_calculation_supportability_total",
    "Performance calculation supportability posture by operation, bounded reason, and freshness bucket.",
    PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
)
ANALYTICS_FRESHNESS_BUCKET_TOTAL = Counter(
    "lotus_analytics_freshness_bucket_total",
    "Backend analytics freshness and supportability posture by service, operation, and bounded freshness bucket.",
    PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS,
)
MWR_SOLVER_OUTCOME_TOTAL = Counter(
    "lotus_performance_mwr_solver_outcome_total",
    "MWR solver outcomes by bounded input mode, method, status, reason code, and fallback flag.",
    PERFORMANCE_MWR_SOLVER_OUTCOME_METRIC_LABELS,
)

_MWR_ALLOWED_INPUT_MODES = frozenset({"stateless", "stateful"})
_MWR_ALLOWED_METHODS = frozenset({"XIRR", "MODIFIED_DIETZ", "DIETZ"})
_MWR_ALLOWED_STATUSES = frozenset({"CALCULATED", "FALLBACK_USED", "NOT_APPLICABLE", "NOT_CALCULABLE"})
_MWR_ALLOWED_REASON_CODES = frozenset(
    {
        "NONE",
        "DIETZ_FALLBACK_USED",
        "MULTIPLE_IRR_ROOTS_DETECTED",
        "NO_ECONOMIC_CONTENT",
        "NO_POSITIVE_AND_NEGATIVE_CASH_FLOW",
        "NO_ROOT_FOUND",
        "SOLVER_DID_NOT_CONVERGE",
        "ZERO_DENOMINATOR",
    }
)


def _nonblank_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _nonblank_header(request: Request, name: str) -> str | None:
    return _nonblank_value(request.headers.get(name))


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
    incoming = _nonblank_header(request, "X-Correlation-Id") or _nonblank_header(request, "X-Correlation-ID")
    return incoming if incoming else f"corr_{uuid4().hex[:12]}"


def resolve_request_id(request: Request) -> str:
    incoming = _nonblank_header(request, "X-Request-Id")
    return incoming if incoming else f"req_{uuid4().hex[:12]}"


def resolve_trace_id(request: Request) -> str:
    traceparent = _nonblank_header(request, "traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 4 and len(parts[1]) == 32:
            return parts[1]
    incoming = _nonblank_header(request, "X-Trace-Id")
    return incoming if incoming else uuid4().hex


def propagation_headers(correlation_id: str | None = None) -> dict[str, str]:
    trace_id = _nonblank_value(trace_id_var.get()) or uuid4().hex
    return {
        "X-Correlation-Id": _nonblank_value(correlation_id)
        or _nonblank_value(correlation_id_var.get())
        or f"corr_{uuid4().hex[:12]}",
        "X-Request-Id": _nonblank_value(request_id_var.get()) or f"req_{uuid4().hex[:12]}",
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


def record_analytics_freshness_bucket(
    *,
    operation: str,
    freshness_bucket: str,
    supportability_state: str,
) -> None:
    ANALYTICS_FRESHNESS_BUCKET_TOTAL.labels(
        service="lotus-performance",
        operation=operation,
        freshness_bucket=freshness_bucket,
        supportability_state=supportability_state,
    ).inc()


def record_mwr_solver_outcome(
    *,
    input_mode: str,
    method: str,
    status: str,
    reason_codes: list[str] | tuple[str, ...],
    fallback_used: bool,
) -> None:
    bounded_input_mode = input_mode if input_mode in _MWR_ALLOWED_INPUT_MODES else "other"
    bounded_method = method if method in _MWR_ALLOWED_METHODS else "OTHER"
    bounded_status = status if status in _MWR_ALLOWED_STATUSES else "OTHER"
    emitted_reason_codes = tuple(reason_codes) if reason_codes else ("NONE",)

    for reason_code in emitted_reason_codes:
        bounded_reason_code = reason_code if reason_code in _MWR_ALLOWED_REASON_CODES else "OTHER"
        MWR_SOLVER_OUTCOME_TOTAL.labels(
            input_mode=bounded_input_mode,
            method=bounded_method,
            status=bounded_status,
            reason_code=bounded_reason_code,
            fallback_used=str(fallback_used).lower(),
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
