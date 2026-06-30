# Runtime Work Items Endpoint Certification

## Purpose And Ownership

`GET /integration/runtime-work-items` is the lotus-performance operator drill-down surface for
concrete durable compute and lineage work items. Use it after `GET /integration/runtime-status`
reports active, failed, or reclaimable queue pressure and support needs exact calculation handles,
workflow family, age, attempts, failure context, and navigation links without querying the durable
metadata database directly.

This endpoint is operator-facing and integration-facing. It is not a front-office analytics result
endpoint, and it does not calculate TWR, MWR, contribution, attribution, benchmark, or returns
figures. Analytics conclusions remain on their endpoint-specific result contracts.

## Request Contract

Method and path:

```text
GET /integration/runtime-work-items
```

Supported query options:

| Option | Default | Meaning |
| --- | --- | --- |
| `queue` | `both` | Scope inspection to `both`, `compute`, or `lineage` queues. |
| `status` | `active` | Select `active`, `failed`, `all`, or `reclaimable` lifecycle views. |
| `limit` | `10` | Maximum returned items per selected queue; bounded from `1` to `100`. |
| `offset` | `0` | Queue-local offset applied before limiting. |
| `min_age_seconds` | `0.0` | Minimum work-item age for stale-item triage. |
| `compute_analytics_type` | omitted | Compute-only workflow filter, for example `TWR`, `ReturnsSeries`, or `Attribution`. |
| `lineage_calculation_type` | omitted | Lineage-only workflow filter, for example `TWR`, `BENCHMARK`, or `Attribution`. |
| `calculation_id_contains` | omitted | Calculation-handle substring filter applied to selected queues. |

Production-like profiles (`ENTERPRISE_RUNTIME_PROFILE=production`, `prod`, or `staging`) require
`ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true` at startup. The route requires enterprise identity
context and capability `operations.runtime.read`.

## Output Contract

Every response carries:

- contract identity: `contract_version`, `source_service`, `generated_at`
- echoed filter state: `queue_filter`, `status_filter`, `limit`, `offset`,
  `min_age_seconds`, `compute_analytics_type`, `lineage_calculation_type`,
  `calculation_id_contains`
- durable metadata store availability
- queue-specific status for compute and lineage inspection
- queue-specific `total_count`, `returned_count`, and optional `next_offset`
- compute work items with calculation handle, analytics type, lifecycle state, age, attempts,
  durable failure context, and direct execution, lineage, and result links
- lineage work items with calculation handle, calculation type, lifecycle state, age, attempts,
  durable failure context, and direct execution, lineage, and result links

`next_offset` is queue-local and appears only when additional matching work items remain for that
queue. `result_path` appears only when the analytics family has a stable async result route.

## Behavior And Feature Checks

Certified behavior:

- active compute and lineage work items are returned with exact calculation handles
- failed compute and lineage work items preserve durable error context
- `queue=compute` and `queue=lineage` exclude the unselected queue instead of querying it
- `status=reclaimable` isolates expired-lease work eligible for recovery or re-lease
- `limit` and `offset` provide queue-local bounded paging
- `next_offset` signals additional matching rows without client-side count arithmetic
- `min_age_seconds` supports stale-work triage
- analytics-family and calculation-handle filters are applied before pagination
- direct `execution_path`, `lineage_path`, and supported async `result_path` links are emitted
- one queue can degrade to `unavailable` while the other queue remains usable
- durable metadata store failure returns unavailable queue statuses rather than misleading empty data

## Upstream Integration

The endpoint does not call lotus-core, market data, or benchmark vendors. It reads
lotus-performance-owned durable metadata stores for compute and lineage work queues, then builds
operator navigation links to existing lotus-performance execution, lineage, and result endpoints.

This is the correct boundary: upstream source-data contracts are irrelevant for this endpoint, and
runtime work-item inspection remains service-owned operational state.

## Downstream Consumers

Known downstream posture:

- `docs/runbooks/runtime-alerts.md` instructs operators to use this endpoint after runtime queue,
  lineage storage, or recovery-drill alerts.
- `GET /integration/runtime-status` references this endpoint as the concrete work-item drill-down.
- `lotus-gateway` should expose this surface only on privileged operator/support workflows, not
  ordinary front-office analytics panels.
- No duplicate lotus-performance work-item endpoint was found.

## GitHub Issue Posture

Open issue searches were run for `runtime-work-items`, `runtime work items`, and
`RuntimeWorkItems` in `sgajbi/lotus-performance`. No open endpoint-specific defect was found.

No downstream migration issue was created for this slice because there is no duplicate endpoint and
no stale downstream caller was found during local source search. Gateway issue `#110` remains
focused on execution and lineage evidence exposure, not this runtime-work-items contract.

## Swagger Readiness

Swagger now explains when to use the endpoint, what each option does, the lifecycle filter semantics,
the queue-local paging model, and the drill-down/result-link output families. The response schemas
carry descriptions and examples for every returned field.

## Test Pyramid Assessment

Current test posture is production-grade for this endpoint:

- store/unit tests cover durable filtering, counts, paging, and reclaimable lease semantics
- service tests cover queue exclusion, partial queue failure, durable-store failure, and filter propagation
- model tests cover navigation-link serialization and result-route mapping
- integration tests cover active, failed, reclaimable, paging, targeted filters, partial failure, and result paths
- OpenAPI/docs tests prevent Swagger and public-reference drift

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_runtime_work_items_openapi_contract.py tests/unit/models/test_runtime_work_items_models.py tests/unit/services/test_runtime_work_item_service.py tests/integration/test_runtime_work_items_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/runtime_work_items.py app/models/runtime_work_items.py app/services/runtime_work_item_service.py tests/unit/app/test_runtime_work_items_openapi_contract.py tests/unit/models/test_runtime_work_items_models.py tests/unit/services/test_runtime_work_item_service.py tests/integration/test_runtime_work_items_api.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/runtime_work_items.py app/models/runtime_work_items.py app/services/runtime_work_item_service.py tests/unit/app/test_runtime_work_items_openapi_contract.py tests/unit/models/test_runtime_work_items_models.py tests/unit/services/test_runtime_work_item_service.py tests/integration/test_runtime_work_items_api.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/runtime_work_items.py app/models/runtime_work_items.py app/services/runtime_work_item_service.py
```
