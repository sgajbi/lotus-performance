# Runtime Recoveries Endpoint Certification

## Purpose And Ownership

`GET /integration/runtime-recoveries` is the lotus-performance operator drill-down surface for
durable compute and lineage recovery events. Use it after `GET /integration/runtime-status` reports
recovery activity, or after `GET /integration/runtime-work-items` shows reclaimable work and support
needs to verify what was recovered, when it was recovered, which queue recovered it, and where to
continue investigation.

This endpoint is operator-facing and integration-facing. It is not an analytics result endpoint and
does not calculate performance figures. It explains runtime recovery behavior for service-owned
durable work queues.

## Request Contract

Method and path:

```text
GET /integration/runtime-recoveries
```

Supported query options:

| Option | Default | Meaning |
| --- | --- | --- |
| `queue` | `both` | Scope inspection to `both`, `compute`, or `lineage` recovery events. |
| `limit` | `10` | Maximum returned events per selected queue; bounded from `1` to `100`. |
| `offset` | `0` | Queue-local offset applied before limiting. |
| `recovered_after` | omitted | Inclusive lower UTC timestamp bound for incident-window filtering. |
| `recovered_before` | omitted | Inclusive upper UTC timestamp bound for incident-window filtering. |
| `cursor_recovered_before` | omitted | Seek cursor timestamp for deterministic traversal of older matching events. |
| `cursor_calculation_id_before` | omitted | Calculation handle paired with the seek cursor timestamp. |
| `compute_analytics_type` | omitted | Compute-only workflow filter, for example `TWR`, `ReturnsSeries`, or `Attribution`. |
| `lineage_calculation_type` | omitted | Lineage-only workflow filter, for example `TWR`, `BENCHMARK`, or `Attribution`. |
| `calculation_id_contains` | omitted | Calculation-handle substring filter applied to selected queues. |

Production-like profiles (`ENTERPRISE_RUNTIME_PROFILE=production`, `prod`, or `staging`) require
`ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true` at startup. The route requires enterprise identity
context and capability `operations.runtime.read`.

## Output Contract

Every response carries:

- contract identity: `contract_version`, `source_service`, `generated_at`
- echoed filter state, including time-window and cursor values
- durable metadata store availability
- queue-specific status for compute and lineage recovery inspection
- queue-specific `total_count`, `returned_count`, optional `next_offset`, and optional next cursor fields
- compute recovery events with calculation handle, analytics type, recovery kind, recovery timestamp,
  attempt count, last durable error type, and direct execution, lineage, and result links
- lineage recovery events with calculation handle, calculation type, recovery kind, recovery timestamp,
  attempt count, and direct execution, lineage, and result links

For hot recovery streams, clients should prefer the cursor fields over offset paging because newly
recovered events can shift offset-based pages.

## Behavior And Feature Checks

Certified behavior:

- compute and lineage recovery events are returned with exact calculation handles
- queue scoping excludes the unselected queue rather than querying it
- `limit` and `offset` provide queue-local bounded paging
- `next_offset` signals additional matching rows
- `recovered_after` and `recovered_before` narrow incident windows
- `cursor_recovered_before` with `cursor_calculation_id_before` provides deterministic seek pagination
- analytics-family and calculation-handle filters are applied before paging
- direct `execution_path`, `lineage_path`, and supported async `result_path` links are emitted
- one queue can degrade to `unavailable` while the other queue remains usable
- durable metadata store failure returns unavailable queue statuses rather than misleading empty data
- partial compute read failure reports `reason="compute_recovery_read_failed"`
- partial lineage read failure reports `reason="lineage_recovery_read_failed"`
- partial read failures emit structured warning log event `runtime_operator_read_degraded` with
  queue source, operation `recovery`, exception class, bounded filters, and calculation-handle
  filter presence instead of raw calculation handles

## Upstream Integration

The endpoint does not call lotus-core, market data, or benchmark vendors. It reads
lotus-performance-owned durable compute and lineage recovery metadata, then builds operator
navigation links to existing lotus-performance execution, lineage, and result endpoints.

This is the correct boundary: recovery history is service-owned runtime evidence, not upstream
portfolio source data.

## Downstream Consumers

Known downstream posture:

- `docs/runbooks/runtime-alerts.md` instructs operators to use this endpoint during runtime alert triage.
- `GET /integration/runtime-status` references this endpoint as the recovery-event drill-down.
- `lotus-gateway` should expose this surface only on privileged operator/support workflows, not ordinary
  front-office analytics panels.
- No duplicate lotus-performance recovery-event endpoint was found.

## GitHub Issue Posture

Open issue searches were run for `runtime-recoveries`, `runtime recoveries`, and
`RuntimeRecoveries` in `sgajbi/lotus-performance`. No open endpoint-specific defect was found.

No downstream migration issue was created for this slice because there is no duplicate endpoint and
no stale downstream caller was found during local source search.

## Operator Partial-Failure Triage

When `compute_queue.status` or `lineage_queue.status` is `unavailable`, use the stable queue-state
`reason` first. `compute_recovery_read_failed` means compute recovery inspection could not read the
compute durable recovery stream; `lineage_recovery_read_failed` means lineage recovery inspection
could not read lineage recovery metadata. The endpoint intentionally keeps the other queue
available when it can. Join the response `correlation_id` from the HTTP envelope/log context with
structured service log event `runtime_operator_read_degraded`; the log includes queue source,
operation, exception class, limit, offset, incident-window filters, cursor presence, workflow-type
filters, and whether a calculation-handle substring filter was present. The log does not emit the
raw calculation-handle substring or cursor calculation handle.

## Swagger Readiness

Swagger now explains when to use the endpoint, what each option does, how offset and cursor
pagination differ, how incident time windows are applied, and which drill-down/result-link output
families are returned. The response schemas carry descriptions and examples for every returned
field.

## Test Pyramid Assessment

Current test posture is production-grade for this endpoint:

- store/unit tests cover durable recovery filtering, counts, time windows, offset paging, and seek cursors
- service tests cover queue exclusion, partial queue failure, durable-store failure, and filter propagation
- model tests cover navigation-link serialization and result-route mapping
- integration tests cover filtered events, paging, cursor traversal, time windows, and result paths
- OpenAPI/docs tests prevent Swagger and public-reference drift

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_runtime_recoveries_openapi_contract.py tests/unit/models/test_runtime_recoveries_models.py tests/unit/services/test_runtime_recovery_service.py tests/integration/test_runtime_recoveries_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/runtime_recoveries.py app/models/runtime_recoveries.py app/services/runtime_recovery_service.py tests/unit/app/test_runtime_recoveries_openapi_contract.py tests/unit/models/test_runtime_recoveries_models.py tests/unit/services/test_runtime_recovery_service.py tests/integration/test_runtime_recoveries_api.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/runtime_recoveries.py app/models/runtime_recoveries.py app/services/runtime_recovery_service.py tests/unit/app/test_runtime_recoveries_openapi_contract.py tests/unit/models/test_runtime_recoveries_models.py tests/unit/services/test_runtime_recovery_service.py tests/integration/test_runtime_recoveries_api.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/runtime_recoveries.py app/models/runtime_recoveries.py app/services/runtime_recovery_service.py
```
