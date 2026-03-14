# Runtime Alert Policy

- Service: `lotus-performance`
- Scope: severity, expected response class, and ownership policy for runtime breach gauges and their availability signals
- Related references:
  - `docs/operations/runtime-alert-rule-templates.md`
  - `docs/runbooks/runtime-alerts.md`
  - `docs/standards/scalability-availability.md`

## Policy Goals

- Keep alert severity aligned to service-owned runtime semantics.
- Avoid environment-by-environment reinterpretation of the same breach gauge.
- Distinguish operator-page conditions from governance/ticket conditions.

## Severity Classes

- `page`
  - immediate operator response required
  - use for live runtime availability, queue degradation, and lineage storage pressure
- `ticket`
  - remediation is required, but the condition is governance or readiness drift rather than immediate runtime outage
  - use for stale or failed retained recovery drills unless the environment chooses a stricter local policy

## Alert Policy Matrix

| Metric family | Expected severity | Why |
| --- | --- | --- |
| `lotus_performance_compute_queue_degradation_breach` | `page` | Compute backlog or failure pressure directly threatens executor-backed analytics completion. |
| `lotus_performance_lineage_queue_degradation_breach` | `page` | Lineage backlog or failure pressure threatens audit artifact completeness and reproducibility. |
| `lotus_performance_lineage_storage_pressure_breach` | `page` | Storage pressure is a pre-failure signal for lineage write outages and should be treated before artifacts stop materializing. |
| `lotus_performance_recovery_drill_degradation_breach` | `ticket` | Recovery assurance drift weakens operational readiness, but does not necessarily mean the live service is failing now. |
| `lotus_performance_durable_queue_store_availability` == `0` | `page` | Queue telemetry source loss makes queue-health and breach gauges non-authoritative. |
| `lotus_performance_lineage_storage_capacity_availability` == `0` | `page` | Storage-capacity blindness removes early warning before lineage write failure. |
| `lotus_performance_recovery_drill_availability` == `0` | `page` | Recovery evidence becomes unreadable, so recovery-governance signals are no longer trustworthy. |

## Response Targets

- `page`
  - inspect within 15 minutes
  - use `docs/runbooks/runtime-alerts.md`
- `ticket`
  - investigate within 1 business day
  - retain evidence of the corrective action in recovery-drill history or change-management records

## Escalation Rule

Promote a `ticket`-class recovery-drill alert to `page` when either condition is true:

- `/health/ready` is unavailable for a durability or lineage-storage reason
- a recovery-drill breach is active together with any queue-degradation or lineage-storage-pressure breach

## Change Control

- Repo-owned alert templates and runbooks must align to this policy.
- Any environment-specific severity override requires explicit operational approval and a documented rationale.
