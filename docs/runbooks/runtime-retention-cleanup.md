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

## Guardrails

- Always run the dry run before `--apply`.
- Do not shorten retention during an active incident unless the goal is deliberate emergency cleanup.
- Do not use this script as a substitute for durable metadata recovery.
- If runtime state or lineage artifacts are needed for an open investigation, preserve them before cleanup.

## Post-Cleanup Validation

- `GET /health/ready`
- `GET /integration/runtime-status`
- `GET /integration/runtime-retention-cleanups`
- confirm `runtime_retention.preview_status="available"` and review the current prunable counts under the active policy
- verify no active execution or lineage work was removed
- if cleanup was substantial, capture the JSON summary as an operator artifact

## Evidence to Capture

- operator running the cleanup
- trigger mode and any automation job identity
- retention window used
- dry-run summary
- apply summary
- any reason for deviating from the default retention window
