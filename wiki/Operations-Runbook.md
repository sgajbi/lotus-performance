# Operations Runbook

## Operator surface summary

Primary runtime surfaces:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `GET /integration/runtime-status`
- `GET /integration/runtime-work-items`
- `GET /integration/runtime-recoveries`
- `GET /integration/recovery-drills`
- `POST /integration/recovery-drills/run`
- `GET /integration/runtime-retention-cleanups`
- `POST /integration/runtime-retention-cleanups/run`
- `GET /performance/executions/{calculation_id}`
- `GET /performance/lineage/{calculation_id}`

## TWR supportability metric

`POST /performance/twr` emits a bounded calculation supportability posture on completed
synchronous responses and increments:

`lotus_performance_calculation_supportability_total{operation="twr",supportability_state,reason,freshness_bucket}`

Use `supportability_state="stale"` or `supportability_state="empty"` as operator attention signals
for front-office TWR surfaces. The labels are intentionally bounded and must not carry portfolio,
client, tenant, account, or security identifiers.

## Readiness semantics

`/health/ready` is intentionally strict. It returns ready only when the API can support durable
executor-backed and lineage-backed workflows.

## First-response documents

- alert handling:
  [docs/runbooks/runtime-alerts.md](../docs/runbooks/runtime-alerts.md)
- durable recovery:
  [docs/runbooks/durable-metadata-recovery.md](../docs/runbooks/durable-metadata-recovery.md)
- retention cleanup:
  [docs/runbooks/runtime-retention-cleanup.md](../docs/runbooks/runtime-retention-cleanup.md)

## Runtime thresholds and overlays

Threshold policy and compose overlays live in:

- [docs/standards/runtime-alert-policy.md](../docs/standards/runtime-alert-policy.md)
- [docs/standards/runtime-threshold-profiles.md](../docs/standards/runtime-threshold-profiles.md)
- [docs/examples](../docs/examples)

## Related pages

- [Architecture](Architecture)
- [Troubleshooting](Troubleshooting)
