# Durable Metadata Recovery Runbook

- Service: `lotus-performance`
- Scope: recovery of durable operational metadata backing execution polling, async results, and lineage status
- Related standards:
  - `docs/standards/migration-contract.md`
  - `docs/standards/durable-schema-inventory.md`
  - `docs/technical/runtime_topology.md`

## Triggers

Use this runbook when any of the following occurs:

- durable metadata database loss or corruption
- restore from backup for `lotus-performance` control-plane state
- schema-upgrade rollback or forward-fix recovery
- worker restart after metadata recovery

## Owned Durable Tables

Recovery must include:

- `analytics_execution`
- `analytics_execution_stage`
- `analytics_upstream_snapshot`
- `analytics_compute_job`
- `analytics_async_result`
- `lineage_records`
- `lineage_payloads`

## Backup and Restore Order

1. Stop write traffic to `performance-analytics`.
2. Stop `performance-compute-executor`.
3. Stop `performance-lineage-worker`.
4. Restore the durable metadata database from the selected backup.
5. Run schema bootstrap/upgrade once against the restored database.
6. Verify owned tables exist and health/readiness can reach the durable metadata store.

## Worker Restart Order

1. Start `performance-analytics`.
2. Verify `/health/ready` returns success against the restored durable metadata store.
3. Start `performance-compute-executor`.
4. Start `performance-lineage-worker`.
5. Verify `/integration/runtime-status` for backlog, retry, leased, and terminal-failure visibility.

## Post-Restore Validation

- `make migration-smoke`
- `python scripts/durable_recovery_drill.py --output artifacts/durable-recovery-drill/latest.json`
- `GET /health/ready`
- `GET /integration/runtime-status`
- verify durable execution polling for a known `calculation_id`
- verify lineage status retrieval for a known `calculation_id`

## Forward-Fix Rule

- Recovery changes are **forward-only** unless an explicit rollback runbook has been approved for an incompatible schema change.
- Any recovery-time schema issue must be corrected through additive forward-fix and rerun of validation.

## Evidence to Capture

- backup identifier and restore timestamp
- operator performing restore
- schema bootstrap/upgrade output
- readiness result after restore
- runtime-status snapshot after worker restart
- structured recovery evidence JSON from `scripts/durable_recovery_drill.py`
