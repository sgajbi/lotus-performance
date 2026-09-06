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
from prometheus_fastapi_instrumentator import routing as instrumentator_routing
from starlette.routing import Match

from app.observability_contracts import (
    PERFORMANCE_ANALYTICS_FRESHNESS_METRIC_LABELS,
    PERFORMANCE_CALCULATION_SUPPORTABILITY_METRIC_LABELS,
    PERFORMANCE_MWR_SOLVER_OUTCOME_METRIC_LABELS,
)
from app.services.queue_metrics_service import DurableQueueCollector

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
#: The caller-admitted tenant for this request. Empty means ABSENT, which is a
#: refusal at the Core boundary rather than a value to be defaulted.
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")

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

_ORIGINAL_INSTRUMENTATOR_ROUTE_NAME_RESOLVER = instrumentator_routing.get_route_name

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


def _bounded_mwr_solver_reason_codes(reason_codes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    emitted_reason_codes = tuple(reason_codes) if reason_codes else ("NONE",)
    return tuple(
        reason_code if reason_code in _MWR_ALLOWED_REASON_CODES else "OTHER" for reason_code in emitted_reason_codes
    )


def _bounded_metric_label(value: str, *, allowed_values: frozenset[str], fallback: str) -> str:
    return value if value in allowed_values else fallback


def _bounded_mwr_solver_outcome_labels(
    *,
    input_mode: str,
    method: str,
    status: str,
    reason_code: str,
    fallback_used: bool,
) -> dict[str, str]:
    return {
        "input_mode": _bounded_metric_label(input_mode, allowed_values=_MWR_ALLOWED_INPUT_MODES, fallback="other"),
        "method": _bounded_metric_label(method, allowed_values=_MWR_ALLOWED_METHODS, fallback="OTHER"),
        "status": _bounded_metric_label(status, allowed_values=_MWR_ALLOWED_STATUSES, fallback="OTHER"),
        "reason_code": _bounded_metric_label(reason_code, allowed_values=_MWR_ALLOWED_REASON_CODES, fallback="OTHER"),
        "fallback_used": str(fallback_used).lower(),
    }


def _nonblank_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _nonblank_header(request: Request, name: str) -> str | None:
    return _nonblank_value(request.headers.get(name))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_json_log_payload(record))


def _record_extra_fields(record: logging.LogRecord) -> dict[str, object]:
    extra_fields = getattr(record, "extra_fields", None)
    if isinstance(extra_fields, dict):
        return extra_fields
    return {}


def _log_context_fields() -> dict[str, str | None]:
    return {
        "correlation_id": correlation_id_var.get() or None,
        "request_id": request_id_var.get() or None,
        "trace_id": trace_id_var.get() or None,
    }


def _json_log_payload(record: logging.LogRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": record.levelname,
        "service": os.getenv("SERVICE_NAME", "lotus-performance"),
        "environment": os.getenv("ENVIRONMENT", "local"),
        "logger": record.name,
        "message": record.getMessage(),
        **_log_context_fields(),
    }
    payload.update(_record_extra_fields(record))
    return {key: value for key, value in payload.items() if value is not None}


def setup_logging(log_level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    root_logger.setLevel(log_level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)


def setup_worker_logging(log_level: str = "INFO") -> None:
    setup_logging(log_level)


def worker_log_extra(
    *,
    worker_name: str,
    worker_id: str | None = None,
    queue: str | None = None,
    **fields: object,
) -> dict[str, dict[str, object]]:
    extra_fields: dict[str, object] = {"worker_name": worker_name}
    for key, value in {"worker_id": worker_id, "queue": queue, **fields}.items():
        if value is not None:
            extra_fields[key] = value
    return {"extra_fields": extra_fields}


def resolve_correlation_id(request: Request) -> str:
    incoming = _nonblank_header(request, "X-Correlation-Id") or _nonblank_header(request, "X-Correlation-ID")
    return incoming if incoming else f"corr_{uuid4().hex[:12]}"


def resolve_request_id(request: Request) -> str:
    incoming = _nonblank_header(request, "X-Request-Id")
    return incoming if incoming else f"req_{uuid4().hex[:12]}"


def resolve_tenant_id(request: Request) -> str:
    """The caller's tenant exactly as presented, or empty.

    Deliberately without a generated fallback: resolve_correlation_id and
    resolve_request_id synthesise a value when the header is absent, because an
    invented correlation id costs nothing. An invented tenant is a cross-tenant
    read, so absence is preserved as absence and refused at the Core boundary.

    Also deliberately without normalization. This used to strip, which made
    `TenantAuthority.__post_init__` unreachable: that invariant says a padded
    value is a different tenant to Core, and it could never fire because the
    padding was gone before it ran. Stripping does not fix a malformed header,
    it changes which tenant the caller asked for. A wholly blank header still
    resolves to "" -- that is absence, not a value -- and anything else is
    returned byte for byte for the factory to accept or refuse."""

    presented = request.headers.get("X-Tenant-Id")
    if presented is None or not presented.strip():
        return ""
    return presented


def resolve_trace_id(request: Request) -> str:
    traceparent_trace_id = _trace_id_from_traceparent(_nonblank_header(request, "traceparent"))
    if traceparent_trace_id is not None:
        return traceparent_trace_id
    incoming = _nonblank_header(request, "X-Trace-Id")
    return incoming if incoming else uuid4().hex


def _trace_id_from_traceparent(traceparent: str | None) -> str | None:
    if traceparent is None:
        return None
    parts = traceparent.split("-")
    if len(parts) >= 4 and len(parts[1]) == 32:
        return parts[1]
    return None


def propagation_headers(correlation_id: str | None = None) -> dict[str, str]:
    trace_id = _propagation_trace_id()
    return {
        "X-Correlation-Id": _propagation_correlation_id(correlation_id),
        "X-Request-Id": _propagation_request_id(),
        "X-Trace-Id": trace_id,
        "traceparent": f"00-{trace_id}-0000000000000001-01",
    }


def source_product_correlation_id() -> str:
    return _propagation_correlation_id(None)


def _propagation_correlation_id(correlation_id: str | None) -> str:
    return _nonblank_value(correlation_id) or _nonblank_value(correlation_id_var.get()) or f"corr_{uuid4().hex[:12]}"


def _propagation_request_id() -> str:
    return _nonblank_value(request_id_var.get()) or f"req_{uuid4().hex[:12]}"


def _propagation_trace_id() -> str:
    return _nonblank_value(trace_id_var.get()) or uuid4().hex


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
    for reason_code in _bounded_mwr_solver_reason_codes(reason_codes):
        MWR_SOLVER_OUTCOME_TOTAL.labels(
            **_bounded_mwr_solver_outcome_labels(
                input_mode=input_mode,
                method=method,
                status=status,
                reason_code=reason_code,
                fallback_used=fallback_used,
            )
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
    _patch_instrumentator_route_name_resolution()
    Instrumentator().instrument(app).expose(app)

    @app.middleware("http")
    async def _request_observability_middleware(request: Request, call_next):
        logger = logging.getLogger("http.access")
        started = time.perf_counter()

        correlation_id = resolve_correlation_id(request)
        request_id = resolve_request_id(request)
        trace_id = resolve_trace_id(request)
        tenant_id = resolve_tenant_id(request)

        correlation_token = correlation_id_var.set(correlation_id)
        request_token = request_id_var.set(request_id)
        trace_token = trace_id_var.set(trace_id)
        tenant_token = tenant_id_var.set(tenant_id)
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
            # Resetting the tenant matters more than the ids above it: a leaked
            # correlation id mislabels a log line, a leaked tenant lets the next
            # request read under the previous caller's authority.
            tenant_id_var.reset(tenant_token)

        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        response.headers["traceparent"] = f"00-{trace_id}-0000000000000001-01"
        return response


def _register_queue_collector_once() -> None:
    if any(isinstance(collector, DurableQueueCollector) for collector in list(REGISTRY._collector_to_names)):
        return
    REGISTRY.register(DurableQueueCollector())


def _patch_instrumentator_route_name_resolution() -> None:
    instrumentator_routing.get_route_name = _instrumentator_route_name


def _instrumentator_route_name(request: Request) -> str | None:
    try:
        return _ORIGINAL_INSTRUMENTATOR_ROUTE_NAME_RESOLVER(request)
    except AttributeError:
        return _included_router_route_name(request)


def _included_router_route_name(request: Request) -> str | None:
    for route in request.app.routes:
        route_name = _matched_route_name(route, request.scope)
        if route_name:
            return route_name
    return None


def _matched_route_name(route: object, scope: object) -> str | None:
    if _route_matches(route, scope) != Match.FULL:
        return None
    return _route_path(route) or _matching_effective_candidate_path(route, scope)


def _route_path(route: object) -> str | None:
    return getattr(route, "path", None) or getattr(route, "path_format", None)


def _matching_effective_candidate_path(route: object, scope: object) -> str | None:
    effective_candidates = getattr(route, "effective_candidates", None)
    if not callable(effective_candidates):
        return None

    for candidate in effective_candidates():
        if _route_matches(candidate, scope) == Match.FULL:
            return _route_path(candidate)
    return None


def _route_matches(route: object, scope: object) -> Match:
    matches = getattr(route, "matches", None)
    if not callable(matches):
        return Match.NONE
    match, _ = matches(scope)
    return match
