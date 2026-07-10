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
- any reason for deviating from the default retention window
