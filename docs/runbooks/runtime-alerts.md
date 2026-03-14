# Runtime Alert Runbook

- Service: `lotus-performance`
- Scope: first-response handling for queue-pressure, recovery-assurance, and lineage-storage alerts exported through `/metrics`
- Related references:
  - `docs/guides/api_reference.md`
  - `docs/technical/runtime_topology.md`
  - `docs/runbooks/durable-metadata-recovery.md`
  - `docs/operations/runtime-alert-rule-templates.md`
  - `docs/standards/runtime-alert-policy.md`

## Primary Alert Gauges

Treat these as the first-class alert surfaces:

- `lotus_performance_compute_queue_degradation_breach{reason=...}`
- `lotus_performance_lineage_queue_degradation_breach{reason=...}`
- `lotus_performance_lineage_storage_pressure_breach{reason=...}`
- `lotus_performance_recovery_drill_degradation_breach{reason=...}`

Always inspect the matching availability gauges first:

- `lotus_performance_durable_queue_store_availability{store=...}`
- `lotus_performance_lineage_storage_capacity_availability`
- `lotus_performance_recovery_drill_availability`

Do not treat a missing breach sample as healthy if the corresponding availability gauge is `0`.

## First Response Sequence

1. Check `GET /health/ready`.
2. Check `GET /integration/runtime-status`.
3. If queue pressure is present, inspect:
   - `GET /integration/runtime-work-items`
   - `GET /integration/runtime-recoveries`
4. If lineage storage is degraded, validate filesystem availability and free capacity before restarting workers.
5. If recovery-drill policy is degraded, inspect `GET /integration/recovery-drills` and compare the latest retained drill against the configured age policy.

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
- First actions:
  - inspect `GET /integration/recovery-drills`
  - identify the latest retained drill `operator_id`, `backup_identifier`, and evidence file
  - rerun `python scripts/durable_recovery_drill.py --operator-id <operator> --backup-identifier <backup-id>` if the latest drill is stale or failed
  - update retained evidence and confirm `latest.json` plus `manifest.json` are refreshed

## Escalation Rule

Escalate immediately when any of the following is true:

- readiness is unavailable for a durability or lineage-storage reason
- breach gauges remain active after the first response sequence
- queue breach plus storage-pressure breach are active together
- recovery-drill breach is active and no recent passing drill evidence exists
