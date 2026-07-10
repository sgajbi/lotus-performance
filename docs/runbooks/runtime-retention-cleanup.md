# Runtime Retention Cleanup Runbook

- Service: `lotus-performance`
- Scope: controlled cleanup of terminal runtime state and lineage artifacts older than the governed retention window
- Related references:
  - `docs/guides/api_reference.md`
  - `docs/runbooks/durable-metadata-recovery.md`
  - `docs/architecture/CODEBASE-REVIEW-LEDGER.md`

## Purpose

Use this runbook to prune retained runtime records that are no longer needed for active execution,
recent async result retrieval, or near-term lineage inspection.

The cleanup script only targets terminal state older than the retention cutoff. It does **not**
prune pending, leased, running, or otherwise active work.

## Controlled Scope

The cleanup covers records older than the selected retention cutoff in:

- `analytics_execution` for terminal executions
- `analytics_compute_job` for terminal compute jobs
- `analytics_async_result`
- `lineage_records` and `lineage_payloads` for terminal lineage entries
- matching lineage artifact directories under `LINEAGE_STORAGE_PATH`

## Storage And Query Posture

Runtime retention is designed for production-volume cleanup, not ad hoc row walking.

- dry-run counts use database-native count queries where calculation ids are not needed;
- apply cleanup uses set-based deletion for async results, compute jobs, execution children, and
  lineage metadata rows;
- execution and lineage cleanup still enumerate calculation ids because lineage artifact
  directories must be counted or deleted deterministically;
- runtime schema creation repairs retention indexes for existing durable stores with
  `CREATE INDEX IF NOT EXISTS`.

Expected retention indexes:

- `analytics_async_result(updated_at_utc)`
- `analytics_compute_job(job_status, completed_at_utc, created_at_utc)`
- `analytics_execution(status, completed_at_utc, created_at_utc)`
- `lineage_records(status, timestamp_utc, calculation_id)`

## Restart Safety And Evidence

Apply mode writes durable evidence before destructive deletion starts. The initial evidence status is
`in_progress` and includes:

- cleanup run id, operator identity, tenant/correlation context, trigger mode, and job id;
- retention window and cutoff;
- selected execution ids and lineage ids;
- selected lineage artifact paths;
- selected compute-job and async-result counts.

The same evidence file is rewritten after cleanup with `applied` or `failed` status. Apply evidence
records per-phase target, deleted, skipped, and failed counts for compute jobs, async results,
lineage artifacts, lineage records, and executions. If a phase fails, operators should correct the
cause and rerun the same governed cleanup path; already-deleted database rows and missing artifact
directories are reconciled idempotently instead of being treated as new failures. Failed or
in-progress evidence is not treated as a successful idempotent replay.

## Default Retention Policy

- Default setting: `RUNTIME_RETENTION_DAYS`
- Current repo-owned default: `30`

Override the default only with an explicit operator or environment-level reason.

## Safe Execution Sequence

1. Run a dry run first:
   - `python scripts/runtime_retention_cleanup.py`
2. Review the JSON summary:
   - `prunable_execution_count`
   - `prunable_compute_job_count`
   - `prunable_async_result_count`
   - `prunable_lineage_record_count`
   - `prunable_lineage_artifact_count`
   - `protected_execution_count`
   - `protected_compute_job_count`
   - `protected_async_result_count`
   - `protected_lineage_record_count`
   - `protected_lineage_artifact_count`
   - `protected_reason_counts`
   - for apply evidence, `target_manifest` and `phase_results`
3. If the counts are expected, apply the cleanup:
   - `python scripts/runtime_retention_cleanup.py --apply`
4. If a non-default window is required, use:
   - `python scripts/runtime_retention_cleanup.py --retention-days <days>`
   - `python scripts/runtime_retention_cleanup.py --retention-days <days> --apply`
5. For governed scheduled automation, use:
   - `python scripts/runtime_retention_cleanup.py --scheduled --apply`
   - confirm the retained evidence records `trigger_mode="scheduled"` and the expected automation `job_id`
   - for a safe scheduled dry run, use `make runtime-retention-smoke`
   - for continuous scheduled execution, enable the optional `performance-runtime-retention-worker` compose service
6. For a service-owned operator action path, use:
   - `POST /integration/runtime-retention-cleanups/run`
   - start with `{"apply": false}` and review the retained evidence summary
   - when enterprise write auth is enabled, include the enterprise identity headers and capability `operations.runtime.manage`
   - use `job_id` when the cleanup is tied to a ticket, incident, or operator workflow

## Guardrails

- Always run the dry run before `--apply`.
- Do not shorten retention during an active incident unless the goal is deliberate emergency cleanup.
- Do not use this script as a substitute for durable metadata recovery.
- If runtime state or lineage artifacts are needed for an open investigation, preserve them before cleanup.
- Place a legal hold before cleanup when calculations are needed for client disputes, regulatory records, audit freezes,
  model-validation, incident, or investigation evidence.
- Legal-hold placement and removal require an operator ticket or approval reference. Do not remove
  a hold merely to reduce prunable counts.

## Legal Hold Exclusions

Runtime retention reads legal holds from `RUNTIME_RETENTION_LEGAL_HOLD_PATH`
(`artifacts/runtime-retention-holds/legal-holds.json` by default). The file is a durable operator
source, not generated cleanup evidence.

Example hold file:

```json
{
  "holds": [
    {
      "calculation_id": "3b5ed4f6-4f7d-4a64-bb23-2e6fa85a0a98",
      "reason_code": "client_dispute",
      "source": "INC-2026-0042"
    }
  ]
}
```

To place a hold:

1. Add the `calculation_id`, bounded `reason_code`, and approval or case `source`.
2. Run `python scripts/runtime_retention_cleanup.py` and confirm protected counts and
   `protected_reason_counts` are present before apply.
3. Keep the hold file under the configured durable artifact location for every API, worker, and
   scheduled cleanup process that can run retention.

To inspect holds, read the configured JSON file and compare the latest dry-run evidence
`target_manifest.protected_*` fields with the case/ticket register. To remove a hold, delete only
the approved hold entry, retain the approval evidence externally, and run another dry run before any
apply action.

## Post-Cleanup Validation

- `GET /health/ready`
- `GET /integration/runtime-status`
- `GET /integration/runtime-retention-cleanups`
- optional: `POST /integration/runtime-retention-cleanups/run` for a fresh governed dry run before apply
- confirm `runtime_retention.preview_status="available"` and review the current prunable counts under the active policy
- verify no active execution or lineage work was removed
- if cleanup was substantial, capture the JSON summary as an operator artifact

## Evidence to Capture

- operator running the cleanup
- tenant and correlation context when the cleanup is run through the governed API surface
- trigger mode and any automation job identity
- any operator ticket or workflow `job_id`
- retention window used
- dry-run summary
- apply summary
- apply target manifest and per-phase results
- protected counts and `protected_reason_counts`
- legal-hold file path and approval/case source when any protected count is non-zero
- any reason for deviating from the default retention window
