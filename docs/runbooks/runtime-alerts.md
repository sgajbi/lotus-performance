# Runtime Alert Runbook

- Service: `lotus-performance`
- Scope: first-response handling for queue-pressure, recovery-assurance, runtime-retention, and lineage-storage alerts exported through `/metrics`
- Related references:
  - `monitoring/prometheus/lotus-performance-alerts.prometheusrule.json`
  - `monitoring/grafana/lotus-performance-operability-dashboard.json`
  - `docs/guides/api_reference.md`
  - `docs/technical/runtime_topology.md`
  - `docs/runbooks/durable-metadata-recovery.md`
  - `docs/operations/runtime-alert-rule-templates.md`
  - `docs/standards/runtime-alert-policy.md`

Deployable alert rules and dashboard panels live under `monitoring/` and are validated by
`make quality-observability-readiness-gate`. The Markdown template pages explain the intent and
operator response, but the JSON artifacts are the repo-owned adoption source.

## Primary Alert Gauges

Treat these as the first-class alert surfaces:

- `lotus_performance_compute_queue_degradation_breach{reason=...}`
- `lotus_performance_lineage_queue_degradation_breach{reason=...}`
- `lotus_performance_lineage_storage_pressure_breach{reason=...}`
- `lotus_performance_recovery_drill_degradation_breach{reason=...}`
- `lotus_performance_runtime_retention_degradation_breach{reason=...}`

Always inspect the matching availability gauges first:

- `lotus_performance_durable_queue_store_availability{store=...}`
- `lotus_performance_lineage_storage_capacity_availability`
- `lotus_performance_recovery_drill_availability`
- `lotus_performance_runtime_retention_availability`

Do not treat a missing breach sample as healthy if the corresponding availability gauge is `0`.

## First Response Sequence

1. Check `GET /health/ready`.
2. Check `GET /integration/runtime-status`.
3. If queue pressure is present, inspect:
   - `GET /integration/runtime-work-items`
   - `GET /integration/runtime-recoveries`
4. If lineage storage is degraded, validate filesystem availability and free capacity before restarting workers.
5. If recovery-drill policy is degraded, inspect `GET /integration/recovery-drills` and compare the latest retained drill against the configured age policy.
6. If runtime-retention policy is degraded, inspect `GET /integration/runtime-retention-cleanups` and compare the latest retained cleanup against the configured age policy and apply-mode expectation.

Partial operator-read handling:

- If `runtime-work-items` or `runtime-recoveries` returns a failed compute queue but a healthy
  lineage queue, use `compute_work_item_read_failed` or `compute_recovery_read_failed` as the
  stable triage code and inspect the `runtime_operator_read_degraded` log event.
- If the failed queue is lineage, use `lineage_work_item_read_failed` or
  `lineage_recovery_read_failed` and inspect the same log event.
- The log event carries source, operation, exception class, and safe filter context. It must not
  carry raw calculation-id fragments, cursor calculation ids, request payloads, or response
  payloads.

Readiness timeout handling:

- `durable_metadata_schema_discovery_failed` means the database ping succeeded but required-table discovery failed; inspect catalog permissions, schema visibility, database metadata responsiveness, and migration state.
- `durable_metadata_readiness_timeout` means the database ping or table-discovery probe exceeded `DURABLE_READINESS_TIMEOUT_SECONDS`; inspect database latency, connectivity, and catalog responsiveness before accepting traffic.
- `lineage_storage_readiness_timeout` means the lineage storage path or write/fsync probe exceeded `DURABLE_READINESS_TIMEOUT_SECONDS`; inspect mount latency, filesystem health, and write behavior before restarting workers.
- A readiness timeout is a dependency health signal, not a reason to disable durable readiness checks.

Runtime-status unexpected-read handling:

- Reason codes such as `compute_queue_status_read_failed`,
  `lineage_queue_status_read_failed`, `recovery_drill_history_read_failed`,
  `runtime_retention_history_read_failed`, `runtime_retention_preview_read_failed`,
  `recovery_drill_operator_action_read_failed`, or
  `runtime_retention_operator_action_read_failed` indicate the status snapshot could not read one
  component, not that the component necessarily breached its configured policy.
- Join the response reason to structured log event `runtime_status_read_degraded`; use the logged
  component, operation, exception class, correlation id, and request id to identify the failing
  store, filesystem evidence path, or governed-action lease snapshot.

## Queue Breach Guidance

### Compute Queue

- Reasons such as `compute_pending_age_exceeded`, `compute_leased_age_exceeded`, or `compute_running_age_exceeded` indicate stuck or slow executor progress.
- Reasons such as `compute_retry_backlog_exceeded`, `compute_lease_expiry_recoveries_exceeded`, or `compute_terminal_failures_exceeded` indicate executor failure pressure rather than simple backlog.
- First actions:
  - inspect `GET /integration/runtime-work-items?queue=compute`
  - inspect `GET /integration/runtime-recoveries?queue=compute`
  - inspect `GET /performance/executions/{calculation_id}` for the oldest or latest failed calculation IDs returned by runtime status

### Lineage Queue

- Reasons such as `lineage_pending_age_exceeded` or `lineage_leased_age_exceeded` indicate stuck materialization backlog.
- Reasons such as `lineage_retry_backlog_exceeded` or `lineage_terminal_failures_exceeded` indicate repeated lineage materialization failure.
- First actions:
  - inspect `GET /integration/runtime-work-items?queue=lineage`
  - inspect `GET /integration/runtime-recoveries?queue=lineage`
  - inspect `GET /performance/lineage/{calculation_id}` for the latest failed or oldest stuck calculation IDs returned by runtime status

## Lineage Storage Pressure Guidance

- `lineage_storage_free_bytes_below_threshold` means the storage path is approaching the configured absolute free-space floor.
- `lineage_storage_free_ratio_below_threshold` means the storage path is approaching the configured proportional free-space floor.
- First actions:
  - inspect `GET /integration/runtime-status` for:
    - `storage_free_bytes`
    - `storage_free_ratio`
    - active storage thresholds
  - reclaim or expand the lineage storage path before restarting workers
  - do not rely on worker restarts to fix storage exhaustion

## Recovery Drill Guidance

- `recovery_drill_latest_not_passed` means the most recent retained recovery drill ended in failure.
- `recovery_drill_age_exceeded` means the latest retained recovery drill is older than the configured max-age policy.
- `recovery_drill_active_run_age_exceeded` means the oldest active governed recovery drill has been in flight longer than the configured execution-age policy and may be stuck.
- `recovery_drill_reclaim_pressure_exceeded` means stale governed recovery-drill leases have been reclaimed often enough to indicate unstable or interrupted operator-action execution.
- First actions:
  - inspect `GET /integration/recovery-drills`
  - identify the latest retained drill `operator_id`, `backup_identifier`, and evidence file
  - rerun `python scripts/durable_recovery_drill.py --operator-id <operator> --backup-identifier <backup-id>` if the latest drill is stale or failed
  - update retained evidence and confirm `latest.json` plus `manifest.json` are refreshed

## Runtime Retention Guidance

- `runtime_retention_latest_not_applied` means the latest retained cleanup evidence only proves a dry run, not an applied retention cleanup.
- `runtime_retention_age_exceeded` means the latest retained cleanup evidence is older than the configured max-age policy.
- `runtime_retention_active_run_age_exceeded` means the oldest active governed runtime-retention cleanup has been in flight longer than the configured execution-age policy and may be stuck.
- `runtime_retention_reclaim_pressure_exceeded` means stale governed runtime-retention cleanup leases have been reclaimed often enough to indicate unstable or interrupted operator-action execution.
- First actions:
  - inspect `GET /integration/runtime-retention-cleanups`
  - identify the latest retained cleanup `operator_id`, `cleanup_mode`, and `retention_days`
  - rerun `python scripts/runtime_retention_cleanup.py --operator-id <operator> --apply` after validating the dry-run summary if the retained cleanup is stale or only planned
  - confirm retained cleanup evidence refreshed `latest.json` plus `manifest.json`

## Escalation Rule

Escalate immediately when any of the following is true:

- readiness is unavailable for a durability or lineage-storage reason
- breach gauges remain active after the first response sequence
- queue breach plus storage-pressure breach are active together
- recovery-drill breach is active and no recent passing drill evidence exists
- runtime-retention breach is active and no recent applied cleanup evidence exists
