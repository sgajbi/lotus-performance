# Runtime Topology

`lotus-performance` runs as four cooperating services in local docker and production-style
deployments:

1. `performance-analytics`
2. `performance-compute-executor`
3. `performance-lineage-worker`
4. `performance-lineage-db`

Source of truth for the local topology is [docker-compose.yml](/C:/Users/Sandeep/projects/lotus-performance/docker-compose.yml).

## Service roles

### `performance-analytics`

- serves the public API
- performs synchronous calculations where the policy keeps work inline
- writes durable execution state, compute jobs, async results, and lineage payload metadata
- exposes `/health`, `/health/live`, `/health/ready`, and `/metrics`
- exposes durable queue-pressure metrics for compute and lineage backlog state

### `performance-compute-executor`

- polls durable compute jobs
- leases work with PostgreSQL row-lock semantics
- executes heavy returns-series, contribution, and attribution workloads
- records durable success/failure results and retry state
- supports explicit quiescence via a worker stop signal instead of relying on process kill semantics

### `performance-lineage-worker`

- polls durable lineage payload metadata
- materializes artifact files asynchronously
- updates durable lineage status for polling and retrieval
- retries failed lineage materialization within a bounded attempt budget before marking terminal failure
- supports explicit quiescence via a worker stop signal instead of relying on process kill semantics

### `performance-lineage-db`

- PostgreSQL backing durable operational state
- stores:
  - execution records
  - execution stages
  - compute jobs
  - async results
  - lineage metadata
  - upstream retrieval snapshots

## Readiness model

`/health/ready` is intentionally stricter than liveness:

- returns `503 {"status":"draining"}` when the API is draining
- returns `503 {"status":"unavailable","reason":"durable_metadata_store_unreachable"}` when the durable metadata store is unreachable
- returns `200 {"status":"ready"}` only when the API can actually support executor-backed and lineage-backed workflows

## Polling model

- execution lifecycle: `GET /performance/executions/{calculation_id}`
- runtime queue snapshot: `GET /integration/runtime-status`
- async returns-series result: `GET /integration/returns/series/results/{calculation_id}`
- async contribution result: `GET /performance/contribution/results/{calculation_id}`
- async attribution result: `GET /performance/attribution/results/{calculation_id}`
- lineage retrieval: `GET /performance/lineage/{calculation_id}`

## Metrics model

Queue-pressure metrics are exposed from the API process by reading durable store state:

- `lotus_performance_compute_queue_jobs{status=...}`
- `lotus_performance_compute_queue_failure_pressure_jobs{category=...}`
- `lotus_performance_compute_queue_oldest_pending_age_seconds`
- `lotus_performance_compute_queue_oldest_leased_age_seconds`
- `lotus_performance_compute_queue_oldest_running_age_seconds`
- `lotus_performance_compute_queue_degradation_breach{reason=...}`
- `lotus_performance_lineage_queue_pending_payloads`
- `lotus_performance_lineage_queue_failure_pressure_payloads{category=...}`
- `lotus_performance_lineage_queue_oldest_pending_age_seconds`
- `lotus_performance_lineage_queue_degradation_breach{reason=...}`
- `lotus_performance_lineage_storage_capacity_availability`
- `lotus_performance_lineage_storage_capacity_bytes{segment=...}`
- `lotus_performance_lineage_storage_free_ratio`
- `lotus_performance_lineage_storage_pressure_threshold{threshold=...}`
- `lotus_performance_lineage_storage_pressure_breach{reason=...}`
- `lotus_performance_recovery_drill_availability`
- `lotus_performance_recovery_drill_latest_age_seconds`
- `lotus_performance_recovery_drill_policy_threshold{threshold=...}`
- `lotus_performance_recovery_drill_degradation_breach{reason=...}`

Operator first response for these breach gauges is governed in
[runtime-alerts.md](/C:/Users/Sandeep/projects/lotus-performance/docs/runbooks/runtime-alerts.md).
Prometheus-style rule templates for the same gauges are governed in
[runtime-alert-rule-templates.md](/C:/Users/Sandeep/projects/lotus-performance/docs/operations/runtime-alert-rule-templates.md).
Severity and response defaults for those rules are governed in
[runtime-alert-policy.md](/C:/Users/Sandeep/projects/lotus-performance/docs/standards/runtime-alert-policy.md).
Recommended dev, staging, and production threshold values are governed in
[runtime-threshold-profiles.md](/C:/Users/Sandeep/projects/lotus-performance/docs/standards/runtime-threshold-profiles.md).

For point-in-time operator drill-down, `GET /integration/runtime-status` exposes the same
durable queue state as a JSON control-plane snapshot, including the oldest pending, leased,
and running compute-job ages plus retry-backlog, lease-expiry, and terminal-failure counts
for compute and lineage. If configured age thresholds are exceeded, the runtime-status surface
degrades proactively instead of only reporting raw queue numbers. Runtime status can also
degrade when configured failure-pressure thresholds are crossed for compute retry backlog,
compute lease-expiry recoveries, compute terminal failures, lineage retry backlog, or lineage
terminal failures. For degraded runtimes, the response now carries queue-level
`degradation_reasons` lists and a top-level `runtime_degradation_reasons` summary so operators
can see every active trigger without inferring from counters manually. These queue snapshots are
derived through SQL-side aggregate queries rather than Python-side row scans so control-plane and
metrics reads remain bounded as durable queue tables grow. The runtime-status payload also exposes
the active compute and lineage degradation-policy thresholds so support can interpret a degraded
runtime against live configuration without reading environment variables separately. For each
active degradation, the control plane also returns the observed value and breached threshold so
incident handling can distinguish "what fired" from "by how much" without reconstructing it from
raw queue counters.

## Failure recovery model

- expired compute leases are reconciled durably
- retryable executor failures are requeued within bounded retry policy
- terminal failures are persisted in both execution state and async result state
- lineage failures remain visible through durable metadata instead of being lost in worker-local logs
