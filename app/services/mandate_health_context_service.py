from __future__ import annotations

from decimal import Decimal

from app.models.mandate_health import (
    MandatePerformanceBenchmarkContext,
    MandatePerformanceHealthContextRequest,
    MandatePerformanceHealthContextResponse,
    MandatePerformanceHealthSourceMetric,
    MandatePerformanceHealthState,
)
from app.observability import source_product_correlation_id
from core.repro import generate_canonical_hash_from_value


def evaluate_mandate_performance_health_context(
    request: MandatePerformanceHealthContextRequest,
) -> MandatePerformanceHealthContextResponse:
    reason_codes = ["PERFORMANCE_METHODOLOGY_SOURCE_OWNED"]
    active_return: Decimal | None = None

    if request.portfolio_period_return is None or request.benchmark_period_return is None:
        health_state: MandatePerformanceHealthState = "unavailable"
        threshold_breached = None
        reason_codes.append("MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_UNAVAILABLE")
    else:
        active_return = request.portfolio_period_return - request.benchmark_period_return
        threshold_breached = active_return < request.active_return_attention_threshold
        health_state = "attention" if threshold_breached else "ready"
        reason_codes.append("MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_SOURCE_READY")
        if threshold_breached:
            reason_codes.append("MANDATE_PERFORMANCE_HEALTH_ACTIVE_RETURN_THRESHOLD_BREACHED")

    request_fingerprint, _ = generate_canonical_hash_from_value(
        request,
        engine_version="mandate-performance-health-context.v1",
    )

    return MandatePerformanceHealthContextResponse(
        correlation_id=source_product_correlation_id(),
        portfolio_id=request.portfolio_id,
        as_of_date=request.as_of_date,
        period_name=request.period_name,
        health_state=health_state,
        threshold_breached=threshold_breached,
        active_return_attention_threshold=request.active_return_attention_threshold,
        source_metric=MandatePerformanceHealthSourceMetric(
            portfolio_period_return=request.portfolio_period_return,
            benchmark_period_return=request.benchmark_period_return,
            active_return=active_return,
        ),
        benchmark_context=MandatePerformanceBenchmarkContext(
            benchmark_available=request.benchmark_period_return is not None
        ),
        request_fingerprint=request_fingerprint,
        reason_codes=reason_codes,
    )
