# Migration Contract Standard

- Service: `lotus-performance`
- Persistence mode: **durable metadata schema** in current architecture.
- Migration policy: **versioned migration contract** remains mandatory as a governance control.
- Runtime schema ownership: application/bootstrap code may create or extend durable metadata tables only through deterministic, test-backed, **additive upgrade** logic.

## Deterministic Checks

- `make migration-apply` runs the executable durable metadata bootstrap apply/verify path against
  the configured runtime metadata database and emits structured evidence under
  `artifacts/durable-schema-apply/`.
- `make migration-smoke` validates this document, durable schema inventory language, recovery
  runbook language, and restore-drill behavior.
- CI executes `make migration-smoke` on all PRs.
- Durable-store schema tests must prove new columns/indexes can be applied without breaking existing metadata tables.

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

