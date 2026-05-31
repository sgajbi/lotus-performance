# Runtime Retention Endpoint Certification

## Purpose And Ownership

`GET /integration/runtime-retention-cleanups` and
`POST /integration/runtime-retention-cleanups/run` are the lotus-performance governed
runtime-retention control-plane endpoints. They expose retained cleanup evidence and allow an
authorized operator or automation identity to run dry-run previews or apply actions without shell
access.

The endpoints are operator-facing and integration-facing. They do not calculate portfolio
performance figures. They govern service-owned retention of terminal executions, compute jobs,
async results, lineage records, and lineage artifacts.

## Request Contracts

History:

```text
GET /integration/runtime-retention-cleanups
```

Supported history query options:

| Option | Default | Meaning |
| --- | --- | --- |
| `limit` | omitted | Maximum retained cleanup entries to return; bounded from `1` to `100`. |
| `offset` | `0` | Offset into the filtered retained history. |
| `operator_id` | omitted | Filter by operator or automation identity. |
| `trigger_mode` | omitted | Filter by `manual` or scheduled automation trigger mode. |
| `job_id` | omitted | Filter by scheduler, ticket, or automation job identity. |
| `cleanup_mode` | omitted | Filter by `dry_run` or apply cleanup mode. |
| `status` | omitted | Filter by cleanup outcome status. |
| `generated_after` | omitted | Inclusive lower ISO-8601 timestamp bound. |
| `generated_before` | omitted | Inclusive upper ISO-8601 timestamp bound. |

Run:

```text
POST /integration/runtime-retention-cleanups/run
```

Request body:

```json
{
  "apply": false,
  "retention_days": 30,
  "job_id": "ops-ticket-123"
}
```

The run endpoint requires `X-Actor-Id` or `X-Service-Identity`. It also captures optional
`X-Tenant-Id` and `X-Correlation-Id`. Apply mode requires a recent matching preview before the
governed cleanup can delete or prune terminal runtime records.

## Output Contract

History responses include:

- contract identity and source service
- retained history availability and explicit unavailable reason
- artifact directory, latest file, retained file names, and retention policy
- `total_entries`, `matched_entries`, `returned_entries`, and optional `next_offset`
- `applied_filters` for auditability
- summarized retained cleanup entries with operator, tenant, correlation, trigger mode, job id,
  cleanup mode, status, retention window, and prunable counts

Implementation ownership is split so shared operator-action history semantics stay reviewable:

| Module | Ownership |
| --- | --- |
| `app.services.runtime_retention_history_service` | Runtime-retention history snapshot assembly, cleanup-specific manifest entry validation, filtering by operator/trigger/job/mode/outcome, and unavailable-history projection. |
| `app.services.operator_action_history_manifest` | Shared retained-history manifest header validation for safe evidence file names, retention metadata, retained file names, entries list shape, and latest-file consistency. |
| `app.services.operator_action_history_filters` | Shared generated-at bounds, applied-filter echo construction, and inclusive time-window matching used by governed operator-action histories. |
| `app.services.operator_action_history_pagination` | Shared offset/limit pagination and next-offset projection for retained operator-action histories. |

Run responses include:

- contract identity and source service
- cleanup identity, generated timestamp, evidence file, operator, tenant, correlation, trigger mode, and job id
- cleanup mode, status, retention window, and cutoff timestamp
- prunable terminal execution, compute job, async result, lineage record, and lineage artifact counts

## Behavior And Feature Checks

Certified behavior:

- missing artifact directory and missing/invalid manifest return structured unavailable history
- history filtering supports operator, trigger mode, job id, cleanup mode, status, and time windows
- history paging reports total, matched, returned, and next offset
- run requests fail fast without operator identity
- dry-run preview returns prunable counts without applying cleanup
- apply mode requires a recent matching preview
- exact repeated run requests can return idempotent replay evidence
- cooldown guards prevent uncontrolled manual cleanup repetition
- stale action leases can be reclaimed through the governed lease path
- retained evidence carries operator, tenant, correlation, mode, retention window, cutoff, and prunable counts

## Upstream Integration

These endpoints do not call lotus-core, market data, or benchmark vendors. They operate on
lotus-performance-owned runtime metadata stores and retained cleanup artifacts. That is the correct
boundary because retention cleanup is service-owned operational evidence, not upstream source data.

## Downstream Consumers

Known downstream posture:

- `docs/runbooks/runtime-alerts.md` instructs operators to inspect runtime-retention history when
  retention policy is degraded.
- `GET /integration/runtime-status` includes runtime-retention readiness and policy context.
- `lotus-gateway` should expose these endpoints only in privileged operator/support workflows.
- No duplicate lotus-performance runtime-retention endpoint was found.

## GitHub Issue Posture

Open issue searches were run for `runtime-retention-cleanups`, `runtime retention`, and
`RuntimeRetention` in `sgajbi/lotus-performance`. No open endpoint-specific defect was found.

No downstream migration issue was created for this slice because no duplicate endpoint or stale
downstream caller was found during local source search.

## Swagger Readiness

Swagger now explains when to use retained history versus governed cleanup execution, how dry-run and
apply differ, what each filter does, and the prunable count families returned. Request and response
schemas carry descriptions and examples for every field.

## Test Pyramid Assessment

Current test posture is production-grade for this endpoint family:

- service tests cover manifest validation, malformed artifacts, shared filter helpers, paging, and time windows
- execution tests cover preview/apply behavior and prunable count calculation
- integration tests cover unavailable history, retained history, filtered history, run identity,
  replay, cooldown, preview-before-apply, stale lease, and response evidence behavior
- OpenAPI/docs tests prevent Swagger and public-reference drift

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_runtime_retention_openapi_contract.py tests/unit/models/test_runtime_retention_history_models.py tests/unit/services/test_operator_action_history_manifest.py tests/unit/services/test_operator_action_history_filters.py tests/unit/services/test_operator_action_history_pagination.py tests/unit/services/test_runtime_retention_history_service.py tests/integration/test_runtime_retention_history_api.py tests/integration/test_runtime_retention_run_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/runtime_retention_history.py app/models/runtime_retention_history.py app/services/operator_action_history_manifest.py app/services/operator_action_history_filters.py app/services/operator_action_history_pagination.py app/services/runtime_retention_history_service.py tests/unit/app/test_runtime_retention_openapi_contract.py tests/unit/models/test_runtime_retention_history_models.py tests/unit/services/test_operator_action_history_manifest.py tests/unit/services/test_operator_action_history_filters.py tests/unit/services/test_operator_action_history_pagination.py tests/unit/services/test_runtime_retention_history_service.py tests/integration/test_runtime_retention_history_api.py tests/integration/test_runtime_retention_run_api.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/runtime_retention_history.py app/models/runtime_retention_history.py app/services/operator_action_history_manifest.py app/services/operator_action_history_filters.py app/services/operator_action_history_pagination.py app/services/runtime_retention_history_service.py tests/unit/app/test_runtime_retention_openapi_contract.py tests/unit/models/test_runtime_retention_history_models.py tests/unit/services/test_operator_action_history_manifest.py tests/unit/services/test_operator_action_history_filters.py tests/unit/services/test_operator_action_history_pagination.py tests/unit/services/test_runtime_retention_history_service.py tests/integration/test_runtime_retention_history_api.py tests/integration/test_runtime_retention_run_api.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/runtime_retention_history.py app/models/runtime_retention_history.py app/services/operator_action_history_manifest.py app/services/operator_action_history_filters.py app/services/operator_action_history_pagination.py app/services/runtime_retention_history_service.py
```
