# Migration Contract Standard

- Service: `lotus-performance`
- Persistence mode: **durable metadata schema** in current architecture.
- Migration policy: **versioned migration contract** remains mandatory as a governance control.
- Runtime schema ownership: `scripts/durable_schema_apply.py` / `make migration-apply` is the
  explicit apply/verify owner. API and compute, lineage, and retention worker startup verify the
  installed schema without DDL, before serving or polling. Missing or incompatible truth raises
  `DURABLE_SCHEMA_MIGRATION_REQUIRED`; restarting a workload does not repair it.
- Composite tenant scoping is fail-closed for retained ownerless rows. Bootstrap never assigns a
  default tenant or uses first-reader ownership. An operator must first provide a complete reviewed
  source-to-tenant ownership mapping through a separately governed data migration. Until that
  mapping is applied, bootstrap aborts in the same transaction and leaves both schema and rows
  unchanged. A pre-tenant schema is rebuilt automatically only when every composite table is
  proven empty, because no ownership or financial evidence can be lost or inferred.
- The prerequisite migration must use an authoritative, operator-reviewed row-to-tenant mapping
  covering definitions, memberships, facts, and publications. It must reject missing, duplicate,
  blank, or ambiguous ownership; rebuild tenant-derived opaque keys and tenant-prefixed uniqueness
  in one transaction; reconcile per-table row counts and composite/fact/publication relationships;
  and commit only after every retained row validates against the target schema. Bootstrap can be
  retried after that migration commits. A startup flag or first-reader assignment is not supported.
- The target composite schema rejects non-canonical tenant values, enforces one definition per
  `(tenant_id, composite_id)`, and binds definition reads to the tenant, external id, and derived
  key together. Bootstrap refuses populated schemas with missing or stale managed tenant checks
  before DDL; it does not accept a merely present `tenant_id` column as proof that ownership
  integrity is complete. Empty partial schemas are rebuilt transactionally with canonical checks.
  Membership, fact, and publication rows also require named foreign keys from
  `(tenant_id, composite_id)` to that definition identity. Supported writers perform an explicit
  tenant-local parent lookup for a typed, non-disclosing refusal; the foreign key closes the
  concurrent delete/write race for direct and supported writers.

## Deterministic Checks

Run commands from the repository root with `LINEAGE_METADATA_DATABASE_URL` set to the same
database for the owner and every workload. Direct local startup requires successful
`make migration-apply` before `make run`. Compose runs `performance-schema-apply` from the same
provenance build and gates all workloads on its successful completion. It waits for database health
and lineage-volume initialization; an owner failure prevents workload startup.

Apply evidence uses `lotus-performance-durable-schema-apply.v2`. Success requires all six store
verification checks, including composite materializations and managed guards; table names or
additive-column presence alone are insufficient. Verification reports bounded contract identifiers,
not retained business rows. A same-named stale index or constraint is not accepted as current.

- `make migration-apply` runs the executable durable metadata bootstrap apply/verify path against
  the configured runtime metadata database and emits structured evidence under
  `artifacts/durable-schema-apply/`. A fail-closed bootstrap validation is recorded as failed
  evidence with its bounded `bootstrap_error`; it is not converted into a successful apply.
- `make migration-smoke` validates this document, durable schema inventory language, recovery
  runbook language, and restore-drill behavior.
- CI executes `make migration-smoke` on all PRs.
- Durable-store schema tests must prove new columns/indexes can be applied without breaking existing metadata tables.
- Runtime bootstrap and apply evidence must fail closed when a populated existing composite
  publication table lacks `expected_families_json` or `source_fingerprint`; table-name presence
  alone is not successful migration evidence. An empty partial table may be rebuilt atomically
  because it contains no lineage authority to preserve or infer.
- The pre-tenant composite immutable-fact upgrade historically backfilled legacy rows to
  `restatement_sequence=1`. That is not a supported identity inference for retained tenant-owned
  facts: a populated partial schema missing sequence identity requires an explicit reviewed
  migration before any DDL. Current upgrades preserve existing opaque primary keys and payloads
  and add idempotent unique indexes for numeric
  sequence identity and source version-label identity plus durable reporting-currency,
  `restatement_sequence >= 1`, and nonblank-version constraints. Valid lowercase legacy currency
  codes made only of original ASCII letters are canonicalized without changing their economic meaning;
  Unicode lookalikes are never normalized into an accepted code, and malformed currency evidence
  fails migration closed. A retained blank or overlong source version label also fails upgrade
  explicitly; blank includes whitespace-only values such as tabs or newlines, and the migration
  neither invents nor truncates a label.
  PostgreSQL enforces that same whitespace definition for direct writers. Bootstrap atomically
  replaces the earlier space-only named check after retained rows pass validation, so an existing
  schema cannot remain weaker than a fresh schema. A validated nullable legacy version column is
  promoted to non-null before the database begins serving.
  Fresh SQLite schemas enforce the same nonblank and 64-character bounds on direct inserts and
  updates. They also require integer-typed positive fact and publication sequences, and require
  publication boundaries to be real ISO calendar dates in Python's year 0001 through 9999 domain
  rather than merely lexically ordered text. Existing SQLite tables receive equivalent
  canonical-currency definition/fact/publication, positive-integer-sequence, fact-version-label,
  and publication-period write triggers after retained-row validation. Bootstrap replaces any
  same-named older SQLite guard in one explicit `BEGIN IMMEDIATE` transaction. Managed guards are
  dropped before legacy normalization, recreated only after validation, and restored with the
  original data if any upgrade step rolls back; a stale immutable trigger cannot block the
  corrective normalization and leave the stronger guards uninstalled.
  Fresh definitions carry the same currency constraint. API models reject non-ASCII lookalikes before uppercasing.
  Retained publication lineage must contain a non-null JSON-list manifest of exact, unique,
  in-window portfolio/period families and a nonblank fingerprint of at most 256 characters.
  PostgreSQL promotes both lineage columns to non-null, while PostgreSQL and SQLite install
  direct-insert guards enforcing the same structure for future rows.
  After legacy normalization and validation complete, both PostgreSQL and SQLite install durable
  mutation guards on member-return facts: updates are rejected because corrections require a new
  restatement sequence, and facts belonging to a completed publication cannot be deleted. The
  completed publication manifest cannot be updated or deleted directly. Supported administrative
  clear methods first acquire the tenant maintenance fence (exclusive for tenant-wide cleanup;
  shared followed by sorted exclusive composite locks for selected cleanup), then acquire the
  fact-table and publication-table lock order, suspend only managed
  guards, delete the manifest before its facts, recreate the guards, and commit as one local
  transaction. Rollback restores both records and guards. Older cleanup or demo-seed binaries must
  not overlap this migrated schema; use the matching application revision for maintenance.
  Retained publication periods must have canonical `YYYY-MM-DD` boundaries and a nonnegative interval:
  SQLite stores date values as text; PostgreSQL uses mapped `DATE` columns. Arbitrary PostgreSQL
  `TEXT` date columns are not a supported automatic conversion. PostgreSQL promotes supported
  boundaries and the validated publication currency to non-null;
  PostgreSQL also retrofits the definition currency constraint. An incomplete or malformed period fails
  closed rather than becoming a serving-time error. Fresh
  and upgraded schemas both default omitted legacy-writer sequences
  to `1`. Source version labels are capped at 64 characters. Lost predecessors are not invented.

## Rollback and Forward-Fix

- Drain API writes and stop compute, lineage, retention and maintenance processes before owner
  apply. Capture a restorable database backup, lineage-volume identity and application revision.
  Use the same database URL and application revision for apply and workload verification.
- The owner can repair legacy SQLite lineage tables whose declared primary key is nullable.
  It preflights every affected table before replacement inside `BEGIN IMMEDIATE`, preserves
  retained values and indexes, and changes only primary-key nullability. NULL identities,
  custom columns/indexes/triggers, foreign-key dependencies or replacement-name collisions
  refuse without mutation. A later failure rolls back both original rows and schema.
- Retained unsupported identity or a stale same-named index needs a reviewed forward migration;
  startup does not repair it. Never delete evidence, assign tenants or infer missing sequences
  to obtain successful verification. Re-run apply and require all six v2 checks before restart.
- If cutover fails, keep workloads stopped. Correct the migration forward or restore the captured
  backup into an isolated target and qualify it using the matching revision and recovery runbook.
  Do not start an older mutating-startup binary against a partly upgraded database.
- Schema changes are **forward-only**.
- Contract violations are corrected through additive forward-fix and CI re-run.
- Any incompatible schema change requires an explicit **rollback runbook** and ADR/RFC approval before merge.

## Durable Upgrade Rules

1. Keep **versioned migration** notes in the governing RFC/ADR for every durable schema change.
2. Prefer deterministic additive upgrades:
   - add nullable columns
   - backfill deterministically
   - add indexes idempotently
3. Upgrade logic must be deterministic and safe against already-initialized local/runtime stores.
4. Runtime bootstrap must not rely on destructive reset or manual table recreation.
5. Any non-additive change requires:
   - explicit compatibility analysis
   - rollback runbook
   - environment validation evidence
