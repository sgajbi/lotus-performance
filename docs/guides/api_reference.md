# API Reference

Canonical machine-readable contract:

- Swagger UI: `/docs`
- OpenAPI JSON: `/openapi.json`

This guide is a human-oriented map of the current endpoint surface. Model-level field
descriptions and examples are maintained in the generated OpenAPI contract.

## Performance APIs

### `POST /performance/twr`

- purpose: calculate time-weighted return
- request model: `app.models.requests.PerformanceRequest`
- response model: `app.models.responses.PerformanceResponse`
- execution mode: synchronous
- lineage: durable lineage metadata is written and artifacts are materialized asynchronously

### `POST /performance/mwr`

- purpose: calculate money-weighted return
- request model: `app.models.mwr_requests.MoneyWeightedReturnRequest`
- response model: `app.models.mwr_responses.MoneyWeightedReturnResponse`
- execution mode: synchronous
- lineage: durable lineage metadata is written and artifacts are materialized asynchronously

### `POST /performance/contribution`

- purpose: calculate position contribution
- request model: `app.models.contribution_requests.ContributionRequest`
- response model:
  - sync: `app.models.contribution_responses.ContributionResponse`
  - async accepted: `app.models.contribution_responses.ContributionAcceptedResponse`
- execution mode:
  - synchronous for smaller position sets
  - `202 Accepted` with `calculation_id`, `poll_path`, and `result_path` when offloaded to the compute executor

### `GET /performance/contribution/results/{calculation_id}`

- purpose: retrieve the durable async contribution result
- response model:
  - completed: `ContributionResponse`
  - still running: `ContributionAcceptedResponse`

### `POST /performance/attribution`

- purpose: calculate multi-level attribution
- request model: `app.models.attribution_requests.AttributionRequest`
- response model:
  - sync: `app.models.attribution_responses.AttributionResponse`
  - async accepted: `app.models.attribution_responses.AttributionAcceptedResponse`
- execution mode:
  - synchronous for smaller input sets
  - `202 Accepted` when offloaded to the compute executor

### `GET /performance/attribution/results/{calculation_id}`

- purpose: retrieve the durable async attribution result
- response model:
  - completed: `AttributionResponse`
  - still running: `AttributionAcceptedResponse`

### `GET /performance/executions/{calculation_id}`

- purpose: poll durable execution state
- response includes:
  - execution status
  - execution stages
  - upstream snapshots
  - compute job state
  - async result metadata

### `GET /performance/lineage/{calculation_id}`

- purpose: retrieve durable lineage status and artifact URLs
- response model: `app.api.endpoints.lineage.LineageResponse`
- integrity note:
  - complete lineage requires a readable `manifest.json` that is structurally valid and consistent with the durable lineage record
  - complete lineage also requires every declared artifact to exist on disk before URLs are returned
  - inconsistent or corrupted manifests return `503` instead of silently serving drifted audit metadata

### `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`

- purpose: download a specific lineage artifact through a controlled calculation/artifact route
- execution mode: synchronous file retrieval
- contract note:
  - only artifacts listed in the lineage record are downloadable
  - unknown artifact names return `404`
  - missing or inconsistent lineage manifests return `503`
  - artifacts declared in durable lineage but missing from storage return `503`

## Integration APIs

### `GET /integration/capabilities`

- purpose: advertise lotus-performance capabilities to downstream consumers
- response model: integration capabilities contract in `app.api.endpoints.integration_capabilities`

### `GET /integration/runtime-status`

- purpose: expose an operational snapshot of runtime state for support and platform operators
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - aggregate runtime status
  - aggregate `runtime_degradation_reasons`
  - aggregate `runtime_degradation_details`
  - draining state
  - durable metadata store availability
  - remediation hints for durable metadata store and lineage queue unavailability reasons when the service knows the next recovery step
  - lineage storage availability folded into `lineage_queue.status` / `lineage_queue.reason`
  - lineage storage capacity details:
    - `storage_total_bytes`
    - `storage_used_bytes`
    - `storage_free_bytes`
    - `storage_free_ratio`
  - active compute and lineage degradation-policy thresholds
  - compute queue backlog details
  - oldest pending, leased, and running compute-job ages
  - retry-backlog, lease-expiry, reclaimable, and terminal-failure compute-job counts
  - compute inspection anchors for the oldest pending, leased, and running work plus the latest terminal failure
  - compute inspection anchors also include the latest recovered compute job returned to pending after retry or stale-lease recovery
  - a bounded `recent_recoveries` list for compute showing the latest requeued items, recovery kind, timestamp, and attempt count
  - compute `degradation_reasons`
  - compute `degradation_details`
  - lineage queue backlog details
  - retry-backlog, reclaimable, and terminal-failure lineage payload counts
  - lineage inspection anchors for the oldest pending and leased work plus the latest terminal failure
  - lineage inspection anchors also include the latest recovered lineage item returned to pending after a retryable materialization failure
  - a bounded `recent_recoveries` list for lineage showing the latest requeued items, recovery kind, timestamp, and attempt count
  - lineage `degradation_details`
  - lineage `degradation_reasons`
  - retained runtime-retention cleanup assurance with latest operator, cleanup mode, retention window, freshness, and live dry-run preview counts under the current policy
- runtime may report `degraded` when configured queue-age or failure-pressure thresholds are exceeded
- runtime also reports `degraded` when lineage storage is missing, invalid, or unreadable even if the durable DB remains healthy
- runtime can also report lineage-storage saturation pressure before writes fail:
  - `lineage_storage_free_bytes_below_threshold`
  - `lineage_storage_free_ratio_below_threshold`
- lineage queue policy now exposes:
  - `storage_min_free_bytes`
  - `storage_min_free_ratio`
- use the inspection anchors to jump directly to:
  - `/performance/executions/{calculation_id}`
  - `/performance/lineage/{calculation_id}`

### `GET /integration/runtime-work-items`

- purpose: return exact compute and lineage work items for operator drill-down
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- query parameters:
  - `queue`: `both`, `compute`, or `lineage`
  - `status`: `active`, `failed`, `all`, or `reclaimable`
  - `limit`: max items returned per queue
  - `offset`: zero-based page offset applied per queue
  - `min_age_seconds`: optional stale-item filter for operator triage
  - `compute_analytics_type`: optional compute-only analytics family filter
  - `lineage_calculation_type`: optional lineage-only calculation family filter
  - `calculation_id_contains`: optional calculation-handle substring filter across selected queues
- response includes:
  - durable metadata store availability
  - queue-specific availability for compute and lineage inspection
  - queue-specific `total_count`, `returned_count`, and `next_offset`
  - `reclaimable` isolates work whose durable worker lease already expired and is eligible for recovery or re-lease
  - echoed targeted filters for operator auditability
  - filtered compute work items with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, lifecycle state, age, attempts, and failure context
  - filtered lineage work items with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, lifecycle state, age, attempts, and failure context
- use this when runtime-status tells you there is pressure, and you need the actual work items behind it without querying the database directly
- `next_offset` is queue-local and only appears when additional filtered work items remain for that queue

### `GET /integration/runtime-recoveries`

- purpose: return recent compute and lineage recovery events for operator drill-down
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- query parameters:
  - `queue`: `both`, `compute`, or `lineage`
  - `limit`: max recovery events returned per queue
  - `offset`: zero-based page offset applied per queue
  - `recovered_after`: optional inclusive lower UTC timestamp bound on recovery-event timestamps
  - `recovered_before`: optional inclusive upper UTC timestamp bound on recovery-event timestamps
  - `cursor_recovered_before`: optional seek cursor timestamp for deterministic traversal of older matching events
  - `cursor_calculation_id_before`: optional seek cursor calculation handle paired with the cursor timestamp
  - `compute_analytics_type`: optional compute-only analytics family filter
  - `lineage_calculation_type`: optional lineage-only calculation family filter
  - `calculation_id_contains`: optional calculation-handle substring filter across selected queues
- response includes:
  - durable metadata store availability
  - queue-specific availability for compute and lineage recovery inspection
  - queue-specific `total_count`, `returned_count`, `next_offset`, `next_cursor_recovered_before`, and `next_cursor_calculation_id_before`
  - filtered compute recovery events with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, analytics type, recovery kind, recovery timestamp, attempt count, and last durable error type
  - filtered lineage recovery events with calculation handle, direct execution/lineage drill-down paths, optional async `result_path`, calculation type, recovery kind, recovery timestamp, and attempt count
- use this when runtime-status shows recent recovery activity and you need the concrete event stream behind the bounded status snapshot without querying the database directly
- `next_offset` is queue-local and only appears when additional filtered events remain for that queue
- the cursor fields give deterministic seek pagination for hot recovery streams where offset paging may drift as new recoveries arrive

### `GET /integration/recovery-drills`

- purpose: inspect retained durable recovery-drill evidence and manifest state
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - retained recovery-drill evidence artifacts
  - latest retained drill summary
  - filtering by operator, backup identifier, status, and bounded time window
  - retained enterprise request context when available:
    - `tenant_id`
    - `correlation_id`

### `POST /integration/recovery-drills/run`

- purpose: execute a governed durable recovery drill through the service-owned control plane
- privileged-write auth:
  - when `ENTERPRISE_ENFORCE_AUTHZ=true`, this route requires enterprise identity headers
  - default governed capability: `operations.runtime.manage`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- request includes:
  - `backup_identifier`
- response includes:
  - immediate recovery-drill summary for the run that just executed
  - operator identity carried from `X-Actor-Id` or `X-Service-Identity`
  - retained enterprise request context from `X-Tenant-Id` and `X-Correlation-Id` when supplied
  - same-correlation retries for the same governed request replay the original retained evidence with `X-Idempotent-Replay: true`
  - `409` plus `Retry-After` when a recent manual drill already completed inside the configured cooldown window
- use this when an operator needs an audited recovery drill without shell access

### `GET /integration/runtime-retention-cleanups`

- purpose: inspect retained runtime-retention cleanup evidence and manifest state
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - retained cleanup evidence artifacts
  - latest retained cleanup summary
  - filtering by operator, trigger mode, job identity, cleanup mode, status, and bounded time window
  - retained enterprise request context when available:
    - `tenant_id`
    - `correlation_id`

### `POST /integration/runtime-retention-cleanups/run`

- purpose: execute a governed runtime-retention dry run or apply action through the service-owned control plane
- privileged-write auth:
  - when `ENTERPRISE_ENFORCE_AUTHZ=true`, this route requires enterprise identity headers
  - default governed capability: `operations.runtime.manage`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- request includes:
  - `apply`
  - optional `retention_days`
  - optional `job_id`
- response includes:
  - retained cleanup evidence summary for the run that just executed
  - operator identity carried from `X-Actor-Id` or `X-Service-Identity`
  - retained enterprise request context from `X-Tenant-Id` and `X-Correlation-Id` when supplied
  - `trigger_mode="manual"` for this control-plane action path
  - same-correlation retries for the same governed request replay the original retained evidence with `X-Idempotent-Replay: true`
  - `apply=true` requires a recent matching `dry_run` preview for the same governed request shape before execution
  - `409` plus `Retry-After` when a recent manual cleanup already completed inside the configured cooldown window
- use this when an operator needs an audited cleanup preview or a deliberate apply action without shell access

### `POST /integration/returns/series`

- purpose: return canonical portfolio, benchmark, and risk-free return series for downstream analytics
- request model: `app.models.returns_series.ReturnsSeriesRequest`
- response model:
  - sync: `app.models.returns_series.ReturnsSeriesResponse`
  - async accepted: `app.models.returns_series.ReturnsSeriesAcceptedResponse`
- execution mode:
  - synchronous for stateless and smaller stateful windows
  - `202 Accepted` for long-window stateful requests offloaded to the compute executor

### `GET /integration/returns/series/results/{calculation_id}`

- purpose: retrieve the durable async returns-series result
- response model:
  - completed: `ReturnsSeriesResponse`
  - still running: `ReturnsSeriesAcceptedResponse`

## Health and observability

### `GET /health`

- returns basic process health

### `GET /health/live`

- returns liveness state

### `GET /health/ready`

- returns readiness only when:
  - the service is not draining
  - the durable metadata store is reachable
  - lineage storage is present and usable
- lineage storage usability includes a real write/delete health probe by default, not just path existence checks
- failure contract:
  - `503 {"status":"draining"}`
  - `503 {"status":"unavailable","reason":"durable_metadata_store_unreachable"}`
  - `503 {"status":"unavailable","reason":"lineage_storage_path_missing"}`
  - `503 {"status":"unavailable","reason":"lineage_storage_write_probe_failed"}`
- readiness failures may also include `remediation_hint` when the service has a concrete recovery recommendation

### `GET /metrics`

- Prometheus metrics surface
- includes durable queue metrics for compute and lineage backlog/failure pressure
- operator runbook:
  - `docs/runbooks/runtime-alerts.md` is the governed first-response guide for queue, storage, and recovery-drill breach gauges
- alert templates:
  - `docs/operations/runtime-alert-rule-templates.md` provides Prometheus-style expressions for the breach and availability gauges exported here
- alert policy:
  - `docs/standards/runtime-alert-policy.md` defines the default severity and response class for these breach and availability gauges
- threshold profiles:
  - `docs/standards/runtime-threshold-profiles.md` defines recommended dev, staging, and production values for the runtime degradation settings behind these gauges
  - `docs/examples/runtime-thresholds.production.env` and its dev/staging companions provide concrete env overlays for those settings
  - `docs/examples/docker-compose.runtime-thresholds.production.yml` and its dev/staging companions provide compose-ready override files for the same thresholds
- includes alert-ready queue policy breach metrics:
  - `lotus_performance_compute_queue_degradation_breach{reason=...}`
  - `lotus_performance_lineage_queue_degradation_breach{reason=...}`
- includes recovery assurance metrics:
  - `lotus_performance_recovery_drill_availability`
  - `lotus_performance_recovery_drill_latest_age_seconds`
  - `lotus_performance_recovery_drill_policy_threshold{threshold="max_age_seconds"}`
  - `lotus_performance_recovery_drill_degradation_breach{reason="recovery_drill_latest_not_passed|recovery_drill_age_exceeded"}`
- includes runtime-retention lifecycle metrics:
  - `lotus_performance_runtime_retention_availability`
  - `lotus_performance_runtime_retention_preview_availability`
  - `lotus_performance_runtime_retention_latest_age_seconds`
  - `lotus_performance_runtime_retention_policy_threshold{threshold="max_age_seconds"}`
  - `lotus_performance_runtime_retention_degradation_breach{reason="runtime_retention_latest_not_applied|runtime_retention_age_exceeded"}`
  - `lotus_performance_runtime_retention_prunable_items{category="execution|compute_job|async_result|lineage_record|lineage_artifact"}`
- includes lineage storage capacity metrics:
  - `lotus_performance_lineage_storage_capacity_availability`
  - `lotus_performance_lineage_storage_capacity_bytes{segment="total|used|free"}`
  - `lotus_performance_lineage_storage_free_ratio`
  - `lotus_performance_lineage_storage_pressure_threshold{threshold="min_free_bytes|min_free_ratio"}`

## Runtime Operations

### `python scripts/runtime_retention_cleanup.py`

- purpose: inspect or prune retained terminal runtime state and lineage artifacts beyond the configured retention window
- governed runbook:
  - `docs/runbooks/runtime-retention-cleanup.md`
- default behavior:
  - dry run only
  - prints a JSON summary of prunable runtime records and lineage artifact directories
- apply behavior:
  - `python scripts/runtime_retention_cleanup.py --apply`
- override behavior:
  - `python scripts/runtime_retention_cleanup.py --retention-days <days>`
- scheduled automation behavior:
  - `python scripts/runtime_retention_cleanup.py --scheduled --apply`
  - evidence records `trigger_mode` plus the configured automation `job_id`
  - `make runtime-retention-smoke` runs the governed scheduled dry-run path with retained evidence
- safety contract:
  - only terminal executions, terminal compute jobs, async results, terminal lineage metadata, and matching lineage artifacts older than the cutoff are eligible
  - active runtime work is not pruned
  - each execution persists timestamped evidence plus refreshed `latest.json` and `manifest.json` under the configured retention artifact directory

### `GET /integration/runtime-retention-cleanups`

- purpose: inspect retained runtime-retention cleanup evidence and history
- privileged-read auth:
  - when `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this route requires enterprise identity headers plus capability `operations.runtime.read`
  - allowed access is enterprise-audited with governed surface and required-capability metadata
- response includes:
  - retained cleanup artifact directory
  - latest retained cleanup evidence file
  - configured cleanup-history retention policy
  - paged retained cleanup entries with operator, trigger mode, optional job identity, cleanup mode, status, retention window, and prunable record counts
- query parameters:
  - `limit`
  - `offset`
  - `operator_id`
  - `trigger_mode`
  - `job_id`
  - `cleanup_mode`
  - `status`
  - `generated_after`
  - `generated_before`
- governed runbook:
  - `docs/runbooks/runtime-retention-cleanup.md`
  - the optional runtime-retention worker uses the same scheduled automation identity and persisted evidence path
  - `lotus_performance_lineage_storage_pressure_breach{reason="lineage_storage_free_bytes_below_threshold|lineage_storage_free_ratio_below_threshold"}`

## Async execution pattern

Executor-backed endpoints use one common pattern:

1. client submits a calculation request
2. API returns either a final result or `202 Accepted`
3. client polls `/performance/executions/{calculation_id}`
4. client retrieves the endpoint-specific async result at the provided `result_path`

`calculation_id` is a durable execution handle, not a best-effort correlation field:

- async endpoints treat an exact resubmission with the same `calculation_id` as an idempotent replay and return the same accepted handle
- reusing the same `calculation_id` with a different payload returns `409 Conflict`
- synchronous endpoints require a fresh `calculation_id` for each new submission

## Contract guidance

- prefer Swagger/OpenAPI for exact field-level descriptions and examples
- use the execution polling endpoint as the source of truth for async lifecycle state
- use lineage retrieval for artifact discovery, not as a proxy for execution completion
