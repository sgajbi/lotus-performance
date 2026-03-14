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

### `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}`

- purpose: download a specific lineage artifact through a controlled calculation/artifact route
- execution mode: synchronous file retrieval
- contract note:
  - only artifacts listed in the lineage record are downloadable
  - unknown artifact names return `404`

## Integration APIs

### `GET /integration/capabilities`

- purpose: advertise lotus-performance capabilities to downstream consumers
- response model: integration capabilities contract in `app.api.endpoints.integration_capabilities`

### `GET /integration/runtime-status`

- purpose: expose an operational snapshot of runtime state for support and platform operators
- response includes:
  - aggregate runtime status
  - aggregate `runtime_degradation_reasons`
  - aggregate `runtime_degradation_details`
  - draining state
  - durable metadata store availability
  - active compute and lineage degradation-policy thresholds
  - compute queue backlog details
  - oldest pending, leased, and running compute-job ages
  - retry-backlog, lease-expiry, reclaimable, and terminal-failure compute-job counts
  - compute inspection anchors for the oldest pending, leased, and running work plus the latest terminal failure
  - compute `degradation_reasons`
  - compute `degradation_details`
  - lineage queue backlog details
  - retry-backlog, reclaimable, and terminal-failure lineage payload counts
  - lineage inspection anchors for the oldest pending and leased work plus the latest terminal failure
  - lineage `degradation_details`
  - lineage `degradation_reasons`
- runtime may report `degraded` when configured queue-age or failure-pressure thresholds are exceeded
- use the inspection anchors to jump directly to:
  - `/performance/executions/{calculation_id}`
  - `/performance/lineage/{calculation_id}`

### `GET /integration/runtime-work-items`

- purpose: return exact compute and lineage work items for operator drill-down
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
  - queue-specific `total_count` and `returned_count`
  - `reclaimable` isolates work whose durable worker lease already expired and is eligible for recovery or re-lease
  - echoed targeted filters for operator auditability
  - filtered compute work items with calculation handle, lifecycle state, age, attempts, and failure context
  - filtered lineage work items with calculation handle, lifecycle state, age, attempts, and failure context
- use this when runtime-status tells you there is pressure, and you need the actual work items behind it without querying the database directly

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
- failure contract:
  - `503 {"status":"draining"}`
  - `503 {"status":"unavailable","reason":"durable_metadata_store_unreachable"}`

### `GET /metrics`

- Prometheus metrics surface

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
