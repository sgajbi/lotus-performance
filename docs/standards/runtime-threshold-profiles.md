# Runtime Threshold Profiles

- Service: `lotus-performance`
- Scope: recommended environment profiles for runtime degradation thresholds, lineage storage pressure, and recovery-drill age policy
- Related references:
  - `app/core/config.py`
  - `docs/standards/runtime-alert-policy.md`
  - `docs/operations/runtime-alert-rule-templates.md`
  - `docs/runbooks/runtime-alerts.md`

## Purpose

- Keep runtime degradation thresholds governed instead of ad hoc per deployment.
- Align alert severity with the underlying threshold values that trigger the breach gauges.
- Make environment promotion explicit: dev is permissive, staging is rehearsal-grade, production is operator-grade.

## Controlled Settings

The following settings define the repo-owned runtime threshold surface:

- `RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT`
- `RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT`
- `RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT`
- `RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT`
- `RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT`
- `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES`
- `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO`
- `RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS`
- `RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT`
- `RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS`
- `RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS`
- `RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT`

## Recommended Profiles

### Development

Use permissive thresholds to avoid noisy alerts during local iteration, but do not leave all thresholds disabled.

| Setting | Development default |
| --- | --- |
| `RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS` | `1800` |
| `RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS` | `900` |
| `RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS` | `1800` |
| `RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT` | `10` |
| `RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT` | `5` |
| `RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT` | `3` |
| `RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS` | `1800` |
| `RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS` | `900` |
| `RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT` | `10` |
| `RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT` | `3` |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES` | `1073741824` |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO` | `0.10` |
| `RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS` | `1209600` |
| `RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `21600` |
| `RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT` | `5` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS` | `1209600` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `21600` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT` | `5` |

### Staging

Use rehearsal-grade thresholds that surface issues early without matching production paging sensitivity exactly.

| Setting | Staging default |
| --- | --- |
| `RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS` | `900` |
| `RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS` | `300` |
| `RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS` | `900` |
| `RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT` | `5` |
| `RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT` | `3` |
| `RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT` | `2` |
| `RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS` | `900` |
| `RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS` | `300` |
| `RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT` | `5` |
| `RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT` | `2` |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES` | `2147483648` |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO` | `0.15` |
| `RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS` | `604800` |
| `RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `7200` |
| `RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT` | `3` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS` | `604800` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `7200` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT` | `3` |

### Production

Use operator-grade thresholds aligned to the alert policy and recovery expectations.

| Setting | Production default |
| --- | --- |
| `RUNTIME_STATUS_COMPUTE_PENDING_AGE_DEGRADE_SECONDS` | `600` |
| `RUNTIME_STATUS_COMPUTE_LEASED_AGE_DEGRADE_SECONDS` | `180` |
| `RUNTIME_STATUS_COMPUTE_RUNNING_AGE_DEGRADE_SECONDS` | `900` |
| `RUNTIME_STATUS_COMPUTE_RETRY_BACKLOG_DEGRADE_COUNT` | `3` |
| `RUNTIME_STATUS_COMPUTE_LEASE_EXPIRY_DEGRADE_COUNT` | `2` |
| `RUNTIME_STATUS_COMPUTE_TERMINAL_FAILURE_DEGRADE_COUNT` | `1` |
| `RUNTIME_STATUS_LINEAGE_PENDING_AGE_DEGRADE_SECONDS` | `600` |
| `RUNTIME_STATUS_LINEAGE_LEASED_AGE_DEGRADE_SECONDS` | `180` |
| `RUNTIME_STATUS_LINEAGE_RETRY_BACKLOG_DEGRADE_COUNT` | `3` |
| `RUNTIME_STATUS_LINEAGE_TERMINAL_FAILURE_DEGRADE_COUNT` | `1` |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_BYTES` | `5368709120` |
| `RUNTIME_STATUS_LINEAGE_STORAGE_MIN_FREE_RATIO` | `0.20` |
| `RUNTIME_STATUS_RECOVERY_DRILL_MAX_AGE_SECONDS` | `259200` |
| `RUNTIME_STATUS_RECOVERY_DRILL_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `3600` |
| `RUNTIME_STATUS_RECOVERY_DRILL_RECLAIM_DEGRADE_COUNT` | `2` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_MAX_AGE_SECONDS` | `259200` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_ACTIVE_RUN_AGE_DEGRADE_SECONDS` | `3600` |
| `RUNTIME_STATUS_RUNTIME_RETENTION_RECLAIM_DEGRADE_COUNT` | `2` |

## Adoption Rules

- Production environments should not leave these thresholds at `0`.
- Any override from the production defaults requires an operational rationale and review.
- Alert definitions should use the breach gauges exported by the service, not restate the thresholds externally.
- If an environment needs stricter local thresholds, update the deployment overlay without changing severity semantics from `docs/standards/runtime-alert-policy.md` unless explicitly approved.

## Deployment Artifacts

Repo-owned example overlays are provided for direct adoption or adaptation:

- `docs/examples/runtime-thresholds.development.env`
- `docs/examples/runtime-thresholds.staging.env`
- `docs/examples/runtime-thresholds.production.env`
- `docs/examples/docker-compose.runtime-thresholds.development.yml`
- `docs/examples/docker-compose.runtime-thresholds.staging.yml`
- `docs/examples/docker-compose.runtime-thresholds.production.yml`

The production examples also carry the enterprise runtime security contract:
`ENTERPRISE_RUNTIME_PROFILE=production`, `ENTERPRISE_ENFORCE_AUTHZ=true`,
`ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, `ENTERPRISE_ENFORCE_RUNTIME_CONFIG=true`, and a
non-blank `ENTERPRISE_PRIMARY_KEY_ID`. Production-like profiles fail closed at startup when these
controls are missing or disabled.
