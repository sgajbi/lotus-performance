# Migration Contract Standard

- Service: `lotus-performance`
- Persistence mode: **durable metadata schema** in current architecture.
- Migration policy: **versioned migration contract** remains mandatory as a governance control.
- Runtime schema ownership: application/bootstrap code may create or extend durable metadata tables only through deterministic, test-backed, **additive upgrade** logic.

## Deterministic Checks

- `make migration-apply` runs the executable durable metadata bootstrap apply/verify path against
  the configured runtime metadata database and emits structured evidence under
  `artifacts/durable-schema-apply/`. A fail-closed bootstrap validation is recorded as failed
  evidence with its bounded `bootstrap_error`; it is not converted into a successful apply.
- `make migration-smoke` validates this document, durable schema inventory language, recovery
  runbook language, and restore-drill behavior.
- CI executes `make migration-smoke` on all PRs.
- Durable-store schema tests must prove new columns/indexes can be applied without breaking existing metadata tables.
- Runtime bootstrap and apply evidence must fail closed when an existing composite publication table lacks
  `expected_families_json` or `source_fingerprint`; table-name presence alone is not successful
  migration evidence.
- The composite immutable-fact upgrade backfills legacy rows to `restatement_sequence=1`, preserves
  their existing opaque primary keys and payloads, and adds idempotent unique indexes for numeric
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
  same-named older SQLite guard in the same transaction so a stale weak definition cannot survive.
  Fresh definitions carry the same currency constraint. API models reject non-ASCII lookalikes before uppercasing.
  After legacy normalization and validation complete, both PostgreSQL and SQLite install durable
  mutation guards on member-return facts: updates are rejected because corrections require a new
  restatement sequence, and facts belonging to a completed publication cannot be deleted. The
  completed publication manifest is also update-immutable. The supported administrative clear
  path removes the publication manifest first, then its facts, in one local transaction.
  Retained publication periods must have two text-backed canonical `YYYY-MM-DD` date boundaries and a nonnegative interval
  before PostgreSQL promotes both boundaries and the validated publication currency to non-null;
  PostgreSQL also retrofits the definition currency constraint. An incomplete or malformed period fails
  closed rather than becoming a serving-time error. Fresh
  and upgraded schemas both default omitted legacy-writer sequences
  to `1`. Source version labels are capped at 64 characters. Lost predecessors are not invented.

## Rollback and Forward-Fix

- Schema changes are **forward-only**.
- Contract violations are corrected through additive forward-fix and CI re-run.
- Any incompatible schema change requires an explicit **rollback runbook** and ADR/RFC approval before merge.

## Durable Upgrade Rules

1. Keep **versioned migration** notes in the governing RFC/ADR for every durable schema change.
2. Prefer additive evolution:
   - add nullable columns
   - backfill deterministically
   - add indexes idempotently
3. Upgrade logic must be deterministic and safe against already-initialized local/runtime stores.
4. Runtime bootstrap must not rely on destructive reset or manual table recreation.
5. Any non-additive change requires:
   - explicit compatibility analysis
   - rollback runbook
   - environment validation evidence
