# Durable Schema Inventory

- Service: `lotus-performance`
- Scope: durable operational metadata owned by RFC-041 runtime components
- Persistence class: control-plane metadata, async execution state, lineage metadata
- Change control: RFC/ADR required for schema ownership changes; see `docs/standards/migration-contract.md`

## Owned Tables

### `analytics_execution`

- Owner: `app/services/execution_registry.py`
- Purpose: canonical execution handle, analytics type, status, input fingerprint, calculation hash, and top-level failure state
- Recovery role: source of truth for execution polling and lifecycle reconciliation

### `analytics_execution_stage`

- Owner: `app/services/execution_registry.py`
- Purpose: per-stage status for submission, retrieval, normalization, execution, and lineage materialization
- Recovery role: supports failure reconciliation and operator drill-down without inferring stage state from logs

### `analytics_upstream_snapshot`

- Owner: `app/services/execution_registry.py`
- Purpose: durable capture of stateful upstream retrieval fingerprints and paging metadata
- Recovery role: reproducibility and source-retrieval traceability

### `analytics_compute_job`

- Owner: `app/services/compute_job_store.py`
- Purpose: executor-backed async compute queue with claim, retry, and terminal-failure state
- Recovery role: durable job recovery after worker crash or lease expiry

### `analytics_async_result`

- Owner: `app/services/async_result_store.py`
- Purpose: durable async success/failure payloads for result retrieval endpoints
- Recovery role: poll/result APIs remain available across process restarts

### `lineage_records`

- Owner: `app/services/lineage_metadata_store.py`
- Purpose: durable lineage job status, artifact registry, and terminal error state
- Recovery role: source of truth for lineage status APIs and worker retry visibility

### `lineage_payloads`

- Owner: `app/services/lineage_metadata_store.py`
- Purpose: durable lineage materialization queue with attempt count and lease metadata
- Recovery role: replay-safe lineage worker claiming and materialization recovery

## Upgrade Rules

- Upgrades must be **additive upgrade** changes by default.
- Runtime bootstrap may create missing tables and add compatible columns/indexes deterministically.
- Existing metadata stores must continue to bootstrap without destructive reset.
- Incompatible changes require explicit RFC/ADR approval plus rollback runbook.

## Recovery and Operations

- Durable metadata is required for:
  - execution polling
  - async result retrieval
  - lineage status retrieval
  - queue pressure and degradation visibility
- Backup and restore validation must include these owned tables before go-live.
- Environment runbooks must document restore order and worker restart order for the durable schema.

## Validation

- `python scripts/durable_schema_inventory_check.py`
- `make migration-smoke`
