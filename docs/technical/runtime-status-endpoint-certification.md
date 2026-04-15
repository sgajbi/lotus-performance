# Runtime Status Endpoint Certification

This note records the certification state for `GET /integration/runtime-status`.

## Purpose And Ownership

`GET /integration/runtime-status` is the lotus-performance-owned operator control-plane snapshot for
durable runtime health. It summarizes API draining state, durable metadata availability, compute
queue pressure, lineage queue pressure, lineage storage capacity, recovery-drill assurance,
runtime-retention assurance, active degradation reasons, and the policy thresholds used to interpret
the snapshot.

Use this endpoint when support, platform operations, or an automated monitor needs a bounded
point-in-time view before drilling into:

- `GET /performance/executions/{calculation_id}`
- `GET /performance/lineage/{calculation_id}`
- `GET /integration/runtime-work-items`
- `GET /integration/runtime-recoveries`
- recovery-drill and runtime-retention history endpoints

Do not use this endpoint as an analytics result surface. It reports runtime supportability and
operational assurance only.

## Request Contract

The endpoint has no query parameters or request body.

When `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, this privileged read route requires enterprise
identity headers and capability `operations.runtime.read`. Allowed access is enterprise-audited with
the governed surface and required capability metadata.

## Output Contract

The response model is `app.models.runtime_status.RuntimeStatusResponse`.

Top-level output families:

| Field | Meaning |
| --- | --- |
| `contract_version` | Runtime-status response contract version. |
| `source_service` | Owning service, currently `lotus-performance`. |
| `generated_at` | Snapshot generation timestamp. |
| `runtime_status` | Aggregate status: `ready`, `degraded`, `draining`, or `unavailable`. |
| `runtime_degradation_reasons[]` | All active aggregate degradation or unavailability reasons. |
| `runtime_degradation_details[]` | Observed and threshold values for active runtime breaches. |
| `draining` | Whether the API process is intentionally draining traffic. |
| `durable_metadata_store` | Durable metadata store availability, reason, and remediation hint. |
| `compute_queue` | Compute queue counts, ages, recovery anchors, and degradation state. |
| `lineage_queue` | Lineage queue counts, storage capacity, recovery anchors, and degradation state. |
| `recovery_drill` | Recovery-drill freshness, active-run, reclaim, and latest-outcome state. |
| `runtime_retention` | Runtime-retention freshness, active-run, reclaim, preview, and prunable-count state. |
| `*_policy` | Active thresholds used to decide whether the runtime is degraded. |

## Behavior And Feature Checks

Certified behavior:

- returns `ready` when durable metadata, lineage storage, queues, recovery-drill assurance, and
  runtime-retention assurance are within policy;
- returns `draining` when the API process is intentionally draining;
- returns `unavailable` when the durable metadata store is unavailable;
- returns `degraded` when queue age thresholds, retry backlog thresholds, lease-expiry pressure,
  terminal failure pressure, lineage storage availability, lineage storage capacity, recovery-drill
  freshness, runtime-retention freshness, active governed-action age, or reclaim pressure violates
  policy;
- exposes compute and lineage inspection anchors that link operators to execution and lineage
  drilldowns;
- exposes bounded recent recovery and stale governed-action reclaim lists so operators can
  understand short recent sequences without querying the database or filesystem directly;
- exposes active policy thresholds in the same payload so operators can interpret breaches against
  live configuration.

## Upstream Integration

This endpoint does not call lotus-core or market-data upstreams. It reads lotus-performance-owned
durable stores and local/runtime evidence surfaces:

- durable execution metadata store;
- compute job store;
- lineage metadata store;
- lineage artifact storage readiness and capacity;
- recovery-drill retained evidence;
- runtime-retention retained evidence and dry-run preview;
- governed action lease state for recovery-drill and runtime-retention runs.

The endpoint is intentionally bounded and aggregate. For row-level evidence, use
`GET /integration/runtime-work-items` or `GET /integration/runtime-recoveries`.

## Downstream Consumers

Known downstream posture:

| Consumer | Current behavior | Certification outcome |
| --- | --- | --- |
| Platform operators and runbooks | Runtime alert and durable recovery runbooks direct operators to `GET /integration/runtime-status`. | Correct strategic endpoint. |
| `lotus-risk` docs | Risk endpoint matrix references performance runtime status as part of operational diagnostics. | Documentation-level dependency only; no direct runtime call found. |
| `lotus-gateway` / Workbench | No direct call to this endpoint found during this slice. | No downstream issue needed for runtime status specifically. |

No duplicate lotus-performance runtime-status endpoint was found. `GET /integration/runtime-work-items`
and `GET /integration/runtime-recoveries` are drilldown endpoints, not duplicates.

## GitHub Issue Posture

Open issue searches were run for lotus-performance, lotus-gateway, and lotus-risk using
`runtime-status`, `runtime status`, and `runtime_status` terms.

Results:

- no endpoint-specific open issue was found for runtime status;
- no downstream migration issue was needed;
- existing gateway issue `#110` is about front-office execution/lineage evidence exposure and is not
  a runtime-status defect.

## Swagger Readiness

Swagger now documents:

- endpoint purpose and operator-control-plane usage;
- response model identity;
- aggregate runtime fields;
- compute, lineage, recovery-drill, runtime-retention, and policy response families;
- descriptions and examples for all response fields through OpenAPI enrichment.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model/schema | `tests/unit/models/test_runtime_status_models.py` verifies serialization of queue stats, anchors, recovery events, storage capacity, policies, and unavailable queues. | Strong. |
| Service/unit | `tests/unit/services/test_runtime_status_service.py` covers ready, draining, unavailable, queue failure, storage failure/capacity pressure, recovery-drill, runtime-retention, active-run, reclaim, and policy degradation states. | Strong. |
| Integration route tests | `tests/integration/test_runtime_status_api.py` exercises the public endpoint across durable queue state, degradation reasons, governed action visibility, storage pressure, and unavailable states. | Strong. |
| Docs/OpenAPI | `tests/unit/app/test_runtime_status_openapi_contract.py` and public docs regression lock endpoint purpose, schema families, and sample shape. OpenAPI and vocabulary gates validate contract metadata. | Strong after this pass. |
| Downstream | No direct downstream runtime-status caller found. Runbooks and operator docs use this as the strategic snapshot endpoint. | Adequate. |

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_runtime_status_openapi_contract.py tests/unit/models/test_runtime_status_models.py tests/unit/services/test_runtime_status_service.py tests/integration/test_runtime_status_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/runtime_status.py app/models/runtime_status.py tests/unit/app/test_runtime_status_openapi_contract.py tests/unit/models/test_runtime_status_models.py tests/unit/services/test_runtime_status_service.py tests/integration/test_runtime_status_api.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/runtime_status.py app/models/runtime_status.py tests/unit/app/test_runtime_status_openapi_contract.py tests/unit/models/test_runtime_status_models.py tests/unit/services/test_runtime_status_service.py tests/integration/test_runtime_status_api.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/runtime_status.py app/models/runtime_status.py app/services/runtime_status_service.py
```
