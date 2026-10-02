# Durability and Consistency Standard (lotus-performance)

- Standard reference: `lotus-platform/Durability and Consistency Standard.md`
- Scope: advanced analytics with lotus-core-sourced canonical inputs and stateless request mode.
- Change control: RFC required for rule changes; ADR required for temporary deviations.

## Workflow Consistency Classification

- Strong consistency:
  - deterministic analytics output for same canonical input + same `as_of_date`
  - reproducibility metadata in analytics responses
- Eventual consistency:
  - external lotus-core data refresh cadence prior to analysis request execution

## Idempotency and Write Semantics

- lotus-performance primary APIs are analytical compute endpoints and do not mutate lotus-core
  business records. Async execution metadata and results are durable service-owned state.
- lotus-performance does not mutate lotus-core core records.
- `POST /performance/attribution` accepts an optional tenant-scoped `Idempotency-Key`. Keyed work is
  accepted durably, exact retries return the original handle, and changed material requests return
  a typed non-retryable conflict. Engine upgrades do not change submission identity. A retained
  response fences re-execution while lineage is pending and serves as the authorized fallback after
  shorter-lived result/job rows are removed. Retry also repairs a submission stage interrupted after
  durable job registration; concurrent stage creation is serialized on the execution row. Only a
  SHA-256 key hash is retained. An ambiguous job-registration outcome preserves the binding so retry
  cannot admit a second execution beside a possibly committed job.
- New durable write or submission endpoints must implement the same replay-safe principle.
- Evidence:
  - `app/api/endpoints/performance.py`
  - `app/services/execution_registry.py`
  - `app/services/submission_fencing_service.py`

## Atomicity Boundaries

- Each analytics request computes within request-local deterministic context.
- Failures return explicit error responses; partial persisted side effects are not allowed.
- Evidence:
  - `core/envelope.py`
  - `core/repro.py`

## As-Of and Reproducibility Semantics

- `as_of_date` is required in canonical request models.
- Responses include engine/config metadata for deterministic replay.
- Evidence:
  - `app/models/*requests.py`
  - `app/api/endpoints/integration_capabilities.py`
  - `core/repro.py`

## Concurrency and Conflict Policy

- No process-local mutable state may be the source of durable replay identity.
- Deterministic canonical hashing is used for reproducibility evidence.
- Idempotency identity excludes caller-generated `calculation_id`, includes the material request and
  versioned source-resolution policy, and is uniquely scoped by tenant and analytics type.
- Evidence:
  - `core/repro.py`
  - `tests/unit/core/test_repro.py`

## Integrity Constraints

- Input schema validation and deterministic envelope normalization prevent malformed data processing.
- Evidence:
  - `app/models/*`
  - `core/envelope.py`

## Release-Gate Tests

- Unit: `tests/unit/*`
- Integration: `tests/integration/*`
- E2E: `tests/e2e/*`

## Deviations

- Any write-side mutation introduced in lotus-performance without idempotency/atomic controls requires ADR with expiry review date.
