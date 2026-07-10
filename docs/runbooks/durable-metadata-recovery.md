# Durable Metadata Recovery Runbook

- Service: `lotus-performance`
- Scope: recovery of durable operational metadata backing execution polling, async results, lineage status, and composite persisted facts
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
- `composite_definitions`
- `composite_memberships`
- `composite_member_return_facts`

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
- `make migration-apply`
  - verify the emitted evidence shows `status="passed"` and no `missing_owned_tables`
  - verify `artifacts/durable-schema-apply/latest.json` records the applied bootstrap stores and additive column checks
- synthetic smoke drill:
  `python scripts/durable_recovery_drill.py --operator-id <operator> --backup-identifier <backup-id>`
  - verify the emitted evidence shows both `compute_async_result_status="complete"` and lineage artifact materialization success
  - use this in CI and fast local validation because it creates a temporary SQLite database and does not prove that a real backup was restored
  - verify `artifacts/durable-recovery-drill/` contains a timestamped evidence file, refreshed `latest.json`, and `manifest.json`
  - verify retained drill history respects both the configured retention limit and maximum age policy
- real restore-validation drill:
  `python scripts/durable_recovery_drill.py --validation-mode restore-validation --restored-database-url <restored-sqlalchemy-url> --backup-source <backup-system-or-uri> --backup-identifier <backup-id> --backup-created-at-utc <timestamp> --restore-started-at-utc <timestamp> --restore-completed-at-utc <timestamp> --operator-id <operator>`
  - run this only against a restored, non-primary durable metadata target such as a restored Postgres database in a production-like drill environment
  - verify evidence records `validation_mode="restore_validation"`, backup source/id, restore timestamp, backup age/RPO, restore duration/RTO, restored owned-table row counts, schema/readiness status, and representative execution/lineage retrieval checks
  - do not point restore-validation mode at the primary production database; it is read-only by design but should still be isolated to the restored target being certified
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
- timestamped recovery evidence artifact path
- manifest/index entry for the retained drill history
- retention policy values applied to retained drill history
- schema bootstrap/upgrade output
- readiness result after restore
- runtime-status snapshot after worker restart
- structured recovery evidence JSON from `scripts/durable_recovery_drill.py`
- real restore-validation evidence when a production-like restore objective is being certified:
  backup source/id, restore timestamp, backup age/RPO, restore duration/RTO, restored table row
  counts, schema/readiness status, and representative execution/lineage retrieval checks
