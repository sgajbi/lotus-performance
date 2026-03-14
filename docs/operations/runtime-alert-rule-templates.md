# Runtime Alert Rule Templates

- Service: `lotus-performance`
- Scope: Prometheus-style alert rule templates for runtime queue pressure, lineage storage pressure, recovery assurance, and retention lifecycle governance
- Related references:
  - `docs/runbooks/runtime-alerts.md`
  - `docs/guides/api_reference.md`
  - `docs/technical/runtime_topology.md`
  - `docs/standards/runtime-alert-policy.md`
  - `docs/standards/runtime-threshold-profiles.md`

These templates are intentionally metric-first and environment-neutral. They convert the
service-owned breach gauges into alert expressions without re-encoding queue or storage
policy logic outside the service. Severity defaults here follow
`docs/standards/runtime-alert-policy.md`.

## Queue Degradation Alerts

### Compute Queue Degraded

```yaml
- alert: LotusPerformanceComputeQueueDegraded
  expr: lotus_performance_compute_queue_degradation_breach > 0
  for: 10m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance compute queue degradation breach"
    description: "One or more compute queue degradation reasons are active."
    runbook: "docs/runbooks/runtime-alerts.md"
```

### Lineage Queue Degraded

```yaml
- alert: LotusPerformanceLineageQueueDegraded
  expr: lotus_performance_lineage_queue_degradation_breach > 0
  for: 10m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance lineage queue degradation breach"
    description: "One or more lineage queue degradation reasons are active."
    runbook: "docs/runbooks/runtime-alerts.md"
```

## Lineage Storage Pressure Alert

```yaml
- alert: LotusPerformanceLineageStoragePressure
  expr: lotus_performance_lineage_storage_pressure_breach > 0
  for: 15m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance lineage storage pressure breach"
    description: "Lineage storage free bytes or free ratio is below the configured threshold."
    runbook: "docs/runbooks/runtime-alerts.md"
```

## Recovery Assurance Alert

```yaml
- alert: LotusPerformanceRecoveryDrillPolicyBreached
  expr: lotus_performance_recovery_drill_degradation_breach > 0
  for: 5m
  labels:
    severity: ticket
    service: lotus-performance
  annotations:
    summary: "lotus-performance recovery drill breach"
    description: "The latest retained recovery drill is stale or failed."
    runbook: "docs/runbooks/runtime-alerts.md"
```

## Runtime Retention Alert

```yaml
- alert: LotusPerformanceRuntimeRetentionPolicyBreached
  expr: lotus_performance_runtime_retention_degradation_breach > 0
  for: 15m
  labels:
    severity: ticket
    service: lotus-performance
  annotations:
    summary: "lotus-performance runtime retention breach"
    description: "The latest retained runtime-retention cleanup is stale or was not applied."
    runbook: "docs/runbooks/runtime-alerts.md"
```

## Source Availability Alerts

Treat source unavailability as distinct from healthy zero values.

```yaml
- alert: LotusPerformanceDurableQueueStoreUnavailable
  expr: lotus_performance_durable_queue_store_availability == 0
  for: 5m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance durable queue store unavailable"
    description: "The queue metrics source is unavailable; breach gauges may be absent."
    runbook: "docs/runbooks/runtime-alerts.md"
```

```yaml
- alert: LotusPerformanceLineageStorageCapacityUnavailable
  expr: lotus_performance_lineage_storage_capacity_availability == 0
  for: 5m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance lineage storage capacity unavailable"
    description: "Lineage storage capacity inspection failed; storage breach gauges are not authoritative."
    runbook: "docs/runbooks/runtime-alerts.md"
```

```yaml
- alert: LotusPerformanceRecoveryDrillHistoryUnavailable
  expr: lotus_performance_recovery_drill_availability == 0
  for: 5m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance recovery drill history unavailable"
    description: "Retained recovery-drill history is unavailable; recovery breach gauges are not authoritative."
    runbook: "docs/runbooks/runtime-alerts.md"
```

```yaml
- alert: LotusPerformanceRuntimeRetentionHistoryUnavailable
  expr: lotus_performance_runtime_retention_availability == 0
  for: 5m
  labels:
    severity: page
    service: lotus-performance
  annotations:
    summary: "lotus-performance runtime retention history unavailable"
    description: "Retained runtime-retention history is unavailable; retention breach gauges are not authoritative."
    runbook: "docs/runbooks/runtime-alerts.md"
```

## Adoption Guidance

- Keep alert expressions pointed at the service-owned breach gauges.
- Do not duplicate threshold logic in Prometheus when the service already exports the breach state.
- Tune `for:` duration per environment, but keep the metric names and runbook target stable.
- Pair these rules with `GET /integration/runtime-status` and `GET /integration/runtime-work-items` during incident handling.
