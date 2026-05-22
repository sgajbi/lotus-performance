# Mandate Performance Health Context

`MandatePerformanceHealthContext:v1` gives downstream DPM consumers a bounded performance-owned
health signal for portfolio mandate supportability. It is intentionally narrow: lotus-performance
evaluates supplied portfolio and benchmark period-return evidence, emits active-return posture,
preserves methodology ownership, and records request lineage.

## Endpoint

`POST /performance/mandate-health-context`

The endpoint is synchronous and stateless. It does not retrieve source rows, create DPM review
actions, create rebalance waves, contact clients, place orders, or integrate with OMS or execution
systems.

## Request

Required fields:

- `portfolio_id`
- `as_of_date`
- `period_name`

Performance evidence fields:

- `portfolio_period_return`: portfolio period return in percentage points
- `benchmark_period_return`: benchmark period return in percentage points
- `active_return_attention_threshold`: underperformance threshold in percentage points, default
  `-0.50`

When either portfolio or benchmark return is absent, the response is `health_state="unavailable"`
and no active-return threshold conclusion is emitted.

## Response

The response includes:

- `product_name="MandatePerformanceHealthContext"`
- `product_version="v1"`
- `health_state`: `ready`, `attention`, or `unavailable`
- `threshold_breached`
- `source_metric.metric_name="ACTIVE_RETURN"`
- `source_metric.active_return`
- `methodology_posture.source_service="lotus-performance"`
- `methodology_posture.source_metrics_product="TimeWeightedReturnAnalytics:v1"`
- `methodology_posture.source_route="/performance/twr"`
- `request_fingerprint`
- bounded `reason_codes`

## Consumer Boundary

`lotus-manage` may consume this source product as performance evidence for DPM supportability and
portfolio-memory posture. Downstream services must preserve the emitted methodology posture,
threshold posture, and reason codes. They must not reconstruct active return, reinterpret
performance methodology, or treat this context as a mandate decision, client communication,
trade recommendation, order, OMS action, or execution instruction.
