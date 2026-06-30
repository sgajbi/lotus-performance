# Recovery Drills Endpoint Certification

## Purpose And Ownership

`GET /integration/recovery-drills` and `POST /integration/recovery-drills/run` are the
lotus-performance governed recovery-assurance control-plane endpoints. They expose retained
recovery-drill evidence and allow an authorized operator or automation identity to execute a
service-owned durable recovery drill without shell access.

The endpoints are operator-facing and integration-facing. They do not calculate portfolio
performance figures. They prove that lotus-performance can restore and process its own durable
metadata, compute, async-result, execution, lineage, and artifact paths.

## Request Contracts

History:

```text
GET /integration/recovery-drills
```

Supported history query options:

| Option | Default | Meaning |
| --- | --- | --- |
| `limit` | `10` | Maximum retained drill entries to return; bounded from `1` to `100`; `next_offset` is emitted when more retained entries remain. |
| `offset` | `0` | Offset into the filtered retained history. |
| `operator_id` | omitted | Filter by operator or automation identity. |
| `backup_identifier` | omitted | Filter by backup or restore-set identifier. |
| `status` | omitted | Filter by drill outcome status. |
| `generated_after` | omitted | Inclusive lower ISO-8601 timestamp bound. |
| `generated_before` | omitted | Inclusive upper ISO-8601 timestamp bound. |

Run:

```text
POST /integration/recovery-drills/run
```

Request body:

```json
{
  "backup_identifier": "backup-2026-03-29"
}
```

The run endpoint requires `X-Actor-Id` or `X-Service-Identity`. It also captures optional
`X-Tenant-Id` and `X-Correlation-Id`. When enterprise write authorization is enabled, it requires
the governed runtime-management capability configured for sensitive operator write surfaces.

## Output Contract

History responses include:

- contract identity and source service
- retained history availability and explicit unavailable reason
- artifact directory, latest file, retained file names, and retention policy
- `total_entries`, `matched_entries`, `returned_entries`, and optional `next_offset`
- `applied_filters` for auditability
- summarized retained entries with evidence file, generation time, operator, tenant, correlation,
  backup identifier, and outcome status

Implementation ownership is split so shared operator-action history semantics stay reviewable:

| Module | Ownership |
| --- | --- |
| `app.services.recovery_drill_history_service` | Recovery-drill history snapshot assembly, recovery-specific manifest entry validation, filtering by operator/backup/outcome, and unavailable-history projection. |
| `app.services.operator_action_history_manifest` | Shared retained-history manifest header validation for safe evidence file names, retention metadata, retained file names, entries list shape, and latest-file consistency. |
| `app.services.operator_action_history_filters` | Shared generated-at bounds, applied-filter echo construction, and inclusive time-window matching used by governed operator-action histories. |
| `app.services.operator_action_history_pagination` | Shared offset/limit pagination and next-offset projection for retained operator-action histories. |

Run responses include:

- contract identity and source service
- drill identity, generated timestamp, evidence file, operator, tenant, correlation, and backup identifier
- outcome status
- durable database path and schema restore mode
- owned durable tables confirmed present
- compute job processed count, async result status, and execution status
- lineage payload processed count and materialized artifact path/existence proof

## Behavior And Feature Checks

Certified behavior:

- missing artifact directory and missing/invalid manifest return structured unavailable history
- history filtering supports operator, backup identifier, status, generated-after, and generated-before filters
- history paging reports total, matched, returned, and next offset
- run requests fail fast without operator identity
- exact repeated run requests can return idempotent replay evidence
- cooldown guards prevent uncontrolled manual drill repetition
- stale action leases can be reclaimed through the governed lease path
- successful runs retain timestamped evidence and manifest state
- run evidence covers compute, async result, execution, lineage, schema, and artifact proof

## Upstream Integration

These endpoints do not call lotus-core, market data, or benchmark vendors. They operate on
lotus-performance-owned recovery artifacts and durable metadata stores. That is the correct
boundary because recovery assurance is service-owned operational evidence, not upstream source data.

## Downstream Consumers

Known downstream posture:

- `docs/runbooks/runtime-alerts.md` instructs operators to inspect `GET /integration/recovery-drills`
  when recovery-drill policy is degraded.
- `GET /integration/runtime-status` includes recovery-drill readiness and policy context that points
  operators toward the retained history.
- `lotus-gateway` should expose these endpoints only in privileged operator/support workflows.
- No duplicate lotus-performance recovery-drill endpoint was found.

## GitHub Issue Posture

Open issue searches were run for `recovery-drills`, `recovery drill`, and `RecoveryDrill` in
`sgajbi/lotus-performance`. No open endpoint-specific defect was found.

No downstream migration issue was created for this slice because no duplicate endpoint or stale
downstream caller was found during local source search.

## Swagger Readiness

Swagger now explains when to use retained history versus governed run execution, what each query
option does, which operator headers matter, and the compute, lineage, schema, and artifact evidence
families returned by the run response. Request and response schemas carry descriptions and examples
for every field.

## Test Pyramid Assessment

Current test posture is production-grade for this endpoint family:

- service tests cover manifest validation, malformed artifacts, shared filter helpers, paging, and time windows
- model tests cover history and run response serialization
- integration tests cover unavailable history, retained history, filtered history, run identity,
  replay, cooldown, stale-lease, and response evidence behavior
- OpenAPI/docs tests prevent Swagger and public-reference drift

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_recovery_drill_openapi_contract.py tests/unit/models/test_recovery_drill_history_models.py tests/unit/services/test_operator_action_history_manifest.py tests/unit/services/test_operator_action_history_filters.py tests/unit/services/test_operator_action_history_pagination.py tests/unit/services/test_recovery_drill_history_service.py tests/integration/test_recovery_drill_history_api.py tests/integration/test_recovery_drill_run_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/recovery_drill_history.py app/models/recovery_drill_history.py app/services/operator_action_history_manifest.py app/services/operator_action_history_filters.py app/services/operator_action_history_pagination.py app/services/recovery_drill_history_service.py tests/unit/app/test_recovery_drill_openapi_contract.py tests/unit/models/test_recovery_drill_history_models.py tests/unit/services/test_operator_action_history_manifest.py tests/unit/services/test_operator_action_history_filters.py tests/unit/services/test_operator_action_history_pagination.py tests/unit/services/test_recovery_drill_history_service.py tests/integration/test_recovery_drill_history_api.py tests/integration/test_recovery_drill_run_api.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/recovery_drill_history.py app/models/recovery_drill_history.py app/services/operator_action_history_manifest.py app/services/operator_action_history_filters.py app/services/operator_action_history_pagination.py app/services/recovery_drill_history_service.py tests/unit/app/test_recovery_drill_openapi_contract.py tests/unit/models/test_recovery_drill_history_models.py tests/unit/services/test_operator_action_history_manifest.py tests/unit/services/test_operator_action_history_filters.py tests/unit/services/test_operator_action_history_pagination.py tests/unit/services/test_recovery_drill_history_service.py tests/integration/test_recovery_drill_history_api.py tests/integration/test_recovery_drill_run_api.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/recovery_drill_history.py app/models/recovery_drill_history.py app/services/operator_action_history_manifest.py app/services/operator_action_history_filters.py app/services/operator_action_history_pagination.py app/services/recovery_drill_history_service.py
```
