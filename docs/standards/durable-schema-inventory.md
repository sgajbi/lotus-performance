# Durable Schema Inventory

- Service: `lotus-performance`
- Scope: durable operational metadata owned by RFC-041 runtime components and composite persisted-fact metadata
- Persistence class: control-plane metadata, async execution state, lineage metadata, composite persisted facts
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
- Lease ownership: `worker_id` remains the configured executor identity exposed to operators, while nullable
  `lease_owner_id` stores the bounded internal per-acquisition fence used to validate renew, success, and
  failure finalization without letting stale workers mutate a newer attempt. Existing schemas are bootstrapped
  with an idempotent column-add path so concurrent service startup does not depend on a single process owning
  the upgrade window.
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

### `composite_definitions`

- Owner: `app/services/composite_metadata_store.py`
- Purpose: durable composite definition metadata for persisted composite performance facts
- Identity integrity: canonical uppercase three-letter ASCII reporting currency is enforced by the
  request model and durable database. PostgreSQL retrofits the named constraint and non-null column;
  SQLite additive upgrades install insert/update guards after retained-row validation.
- Recovery role: supports composite performance reconstruction without reclassifying source-owned portfolio facts

### `composite_memberships`

- Owner: `app/services/composite_metadata_store.py`
- Purpose: durable effective-dated composite membership metadata
- Recovery role: supports composite member selection and period reconstruction after restart or restore

### `composite_member_return_facts`

- Owner: `app/services/composite_metadata_store.py`
- Purpose: append-only member-level return facts separated by return view, reporting currency,
  source version label, and positive numeric restatement sequence, with source fingerprints and
  reason-code evidence. Unique dimensional indexes fence immutable identities and a named database
  PostgreSQL check constraints enforce canonical uppercase three-letter reporting currency and
  `restatement_sequence >= 1`; supported writers enforce the same model rules in local SQLite. A
  fresh SQLite schema also constrains direct inserts and updates to nonblank version labels of at
  most 64 characters using the model's whitespace set, and rejects sequences whose SQLite storage
  class is not integer. The sequence has the same server-side default of `1` on fresh and upgraded schemas, while version labels are `VARCHAR(64)` and
  constrained nonblank. PostgreSQL applies the same version-label rules to direct SQL writers.
- Upgrade behavior: legacy lowercase three-letter currency values composed of original ASCII letters are canonicalized across
  composite definitions, member-return facts, and publication manifests in both PostgreSQL and
  supported local SQLite stores. Retained values containing whitespace, digits, symbols, or other
  non-ASCII currency characters make the upgrade fail closed before the store serves reads.
  Existing null, nonpositive, fractional, or nonnumeric restatement sequences also fail upgrade
  explicitly rather than disappearing from selection; no historical sequence is invented.
  PostgreSQL makes the validated sequence column non-null.
  PostgreSQL then applies the fact-table database constraint and atomically strengthens an existing
  earlier space-only named constraint after retained-row validation. It also promotes a validated
  nullable legacy version column to non-null. SQLite additive upgrade replaces the managed future-insert
  canonical-currency, positive-integer-sequence, and version-label guards after retained-row
  validation without rebuilding the existing table.
- Recovery role: source of deterministic latest or explicit historical persisted-fact evidence for
  composite TWR calculations and inspections after restart
- Mutation boundary: fact rows are insert-only after admission. Database triggers reject direct
  updates in PostgreSQL and SQLite, and reject deletion while a matching completed publication
  exists. Corrections are new immutable sequences; supported scoped cleanup removes the publication
  before its facts in the same database transaction.

### `composite_member_return_fact_publications`

- Owner: `app/services/composite_metadata_store.py`
- Purpose: immutable completion evidence for one composite, return view, reporting currency, and
  numeric restatement sequence. The row declares its inclusive covered period, the exact
  source-declared portfolio/period family set, and its publication fingerprint. A publication only
  participates in latest selection when its period covers the requested window.
- Recovery role: distinguishes a complete generation that intentionally removes a prior family from
  a partial or interrupted write, without fabricating replacement financial facts
- Read eligibility: an unpinned latest read requires a covering completed publication; durable fact
  rows without that completion evidence remain available only through an explicit sequence replay.
- Concurrency: PostgreSQL uses shared writer and exclusive completion advisory locks; supported
  local SQLite mode uses `BEGIN IMMEDIATE` so completion cannot attest a family set while another
  fact writer commits between the read and manifest insert. Writer and completion lookups use the
  logical composite/view/currency/sequence identity, preserving the fence when a legacy lowercase
  currency is canonicalized but its identity-derived primary key predates that normalization.
- Payload integrity: completed family-set comparison is paired with database mutation guards. A
  direct writer cannot change economics or lineage on an existing fact while retaining the same
  family identity, cannot rewrite a completed manifest's period, family set, or fingerprint, and
  cannot delete a completed fact without first removing its manifest.
- Upgrade behavior: retained null, nonpositive, fractional, or nonnumeric sequences fail closed.
  A pre-existing publication table must also retain `expected_families_json` and
  `source_fingerprint`; runtime bootstrap refuses the table rather than fabricating lineage.
  Retained publication periods also fail closed when either boundary is null, uses a non-text
  SQLite storage class, is not the exact canonical `YYYY-MM-DD` representation, or when the end
  precedes the start. PostgreSQL makes the validated sequence, reporting currency, and both period boundaries non-null and
  retrofits the canonical-currency, positive-sequence, and valid-period checks before serving.
  SQLite publication tables reject non-integer sequences and non-calendar ISO date text on direct
  insert or update, including SQLite's otherwise valid astronomical year zero. Additive upgrades
  replace equivalent named triggers after retained rows pass validation; lexical ordering alone is not
  accepted as calendar validity.

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
- Backup and restore validation must include these owned tables before go-live and verify the
  composite fact sequence plus publication period, expected-family, fingerprint, and sequence
  columns rather than accepting table-name presence alone.
- Environment runbooks must document restore order and worker restart order for the durable schema.

## Validation

- `python scripts/durable_schema_apply.py`
- `make migration-apply`
- `python scripts/durable_schema_inventory_check.py`
- `make migration-smoke`
