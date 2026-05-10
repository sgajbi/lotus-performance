# MWR Alert And Dashboard Templates

- Service: `lotus-performance`
- Scope: Prometheus-style alert rules and dashboard panels for `/performance/mwr` solver ambiguity,
  fallback, and source-data rejection posture
- Related references:
  - `docs/operations/mwr-production-support-playbook.md`
  - `docs/guides/mwr.md`
  - `docs/technical/mwr-endpoint-certification.md`
  - `docs/technical/mwr-industry-review-findings.md`
  - `docs/runbooks/runtime-alerts.md`
  - `docs/standards/runtime-alert-policy.md`

These templates use service-owned, bounded-label metrics. They must not introduce portfolio,
client, tenant, account, calculation, trace, correlation, request, or response identifiers into
Prometheus labels.

## Metric Contract

MWR solver outcomes are emitted through:

`lotus_performance_mwr_solver_outcome_total{input_mode,method,status,reason_code,fallback_used}`

Source-data supportability posture is read from the shared calculation-supportability metric:

`lotus_performance_calculation_supportability_total{operation,supportability_state,reason,freshness_bucket}`

## Recording Queries

Use a 30-minute observation window for operator dashboards and a 15-minute window only in
high-volume environments where the sample count is large enough to avoid noisy ratios.

```promql
sum(increase(lotus_performance_mwr_solver_outcome_total[30m]))
```

```promql
sum(increase(lotus_performance_mwr_solver_outcome_total{fallback_used="true"}[30m]))
/
clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)
```

```promql
sum(increase(lotus_performance_mwr_solver_outcome_total{reason_code="NO_ROOT_FOUND"}[30m]))
/
clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)
```

```promql
sum(increase(lotus_performance_mwr_solver_outcome_total{reason_code="MULTIPLE_IRR_ROOTS_DETECTED"}[30m]))
/
clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)
```

```promql
sum(increase(lotus_performance_calculation_supportability_total{
  operation="mwr",
  supportability_state=~"empty|stale"
}[30m]))
/
clamp_min(sum(increase(lotus_performance_calculation_supportability_total{operation="mwr"}[30m])), 1)
```

## Alert Rule Templates

Thresholds below are production defaults for portfolio-advisory operations. Environments with low
MWR volume should pair each ratio alert with a minimum sample count before paging.

```yaml
- alert: LotusPerformanceMWRFallbackRateElevated
  expr: |
    (
      sum(increase(lotus_performance_mwr_solver_outcome_total{fallback_used="true"}[30m]))
      /
      clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)
    ) > 0.05
    and
    sum(increase(lotus_performance_mwr_solver_outcome_total[30m])) >= 20
  for: 30m
  labels:
    severity: ticket
    service: lotus-performance
    product: mwr
  annotations:
    summary: "lotus-performance MWR fallback rate elevated"
    description: "More than 5% of recent MWR calculations used a labeled fallback."
    runbook: "docs/operations/mwr-production-support-playbook.md"
```

```yaml
- alert: LotusPerformanceMWRNoRootRateElevated
  expr: |
    (
      sum(increase(lotus_performance_mwr_solver_outcome_total{reason_code="NO_ROOT_FOUND"}[30m]))
      /
      clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)
    ) > 0.02
    and
    sum(increase(lotus_performance_mwr_solver_outcome_total[30m])) >= 20
  for: 30m
  labels:
    severity: ticket
    service: lotus-performance
    product: mwr
  annotations:
    summary: "lotus-performance MWR no-root rate elevated"
    description: "More than 2% of recent MWR calculations could not find an XIRR root."
    runbook: "docs/operations/mwr-production-support-playbook.md"
```

```yaml
- alert: LotusPerformanceMWRMultipleRootRateElevated
  expr: |
    (
      sum(increase(lotus_performance_mwr_solver_outcome_total{reason_code="MULTIPLE_IRR_ROOTS_DETECTED"}[30m]))
      /
      clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)
    ) > 0.01
    and
    sum(increase(lotus_performance_mwr_solver_outcome_total[30m])) >= 20
  for: 30m
  labels:
    severity: ticket
    service: lotus-performance
    product: mwr
  annotations:
    summary: "lotus-performance MWR multiple-root rate elevated"
    description: "More than 1% of recent MWR calculations detected multiple valid IRR roots."
    runbook: "docs/operations/mwr-production-support-playbook.md"
```

```yaml
- alert: LotusPerformanceMWRSourceDataRejectionRateElevated
  expr: |
    (
      sum(increase(lotus_performance_calculation_supportability_total{
        operation="mwr",
        supportability_state=~"empty|stale"
      }[30m]))
      /
      clamp_min(sum(increase(lotus_performance_calculation_supportability_total{operation="mwr"}[30m])), 1)
    ) > 0.03
    and
    sum(increase(lotus_performance_calculation_supportability_total{operation="mwr"}[30m])) >= 20
  for: 30m
  labels:
    severity: ticket
    service: lotus-performance
    product: mwr
  annotations:
    summary: "lotus-performance MWR source-data rejection rate elevated"
    description: "More than 3% of recent MWR calculations reported empty or stale source supportability."
    runbook: "docs/operations/mwr-production-support-playbook.md"
```

## Dashboard Panels

Use these panels for production operations, support review, and client-demo readiness checks:

| Panel | Query | Audience |
| --- | --- | --- |
| MWR request volume | `sum(increase(lotus_performance_mwr_solver_outcome_total[30m]))` | operations, engineering |
| Fallback rate | `sum(increase(lotus_performance_mwr_solver_outcome_total{fallback_used="true"}[30m])) / clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)` | operations, support, business users |
| No-root rate | `sum(increase(lotus_performance_mwr_solver_outcome_total{reason_code="NO_ROOT_FOUND"}[30m])) / clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)` | operations, engineering |
| Multiple-root rate | `sum(increase(lotus_performance_mwr_solver_outcome_total{reason_code="MULTIPLE_IRR_ROOTS_DETECTED"}[30m])) / clamp_min(sum(increase(lotus_performance_mwr_solver_outcome_total[30m])), 1)` | support, business users |
| Source-data rejection rate | `sum(increase(lotus_performance_calculation_supportability_total{operation="mwr",supportability_state=~"empty|stale"}[30m])) / clamp_min(sum(increase(lotus_performance_calculation_supportability_total{operation="mwr"}[30m])), 1)` | operations, upstream data owners |

## Response Guidance

- Treat `MULTIPLE_IRR_ROOTS_DETECTED` as a business-explainability signal, not as a platform outage.
- Treat `NO_ROOT_FOUND` as a data-shape or economics review signal until a runtime failure is proven.
- Treat elevated source-data rejection as a data mesh escalation to the `lotus-core` source-data
  owner when stateful stale or insufficient observations are confirmed.
- Pair every alert investigation with a sample response review so supportability fields and
  client-safe explanations stay aligned with `docs/operations/mwr-production-support-playbook.md`.
