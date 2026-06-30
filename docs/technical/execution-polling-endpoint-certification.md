# Execution Polling Endpoint Certification

This note records the certification state for `GET /performance/executions/{calculation_id}`.

## Purpose And Ownership

`GET /performance/executions/{calculation_id}` is the lotus-performance-owned lifecycle polling
contract for calculations that run inline or through the durable compute executor. It is the
canonical `poll_path` advertised by async-capable analytics endpoints.

Use this endpoint to decide whether an accepted calculation is still pending or running, completed,
or failed. Once the execution status is complete, clients should retrieve the endpoint-specific
result from the accepted `result_path`.

Do not treat this endpoint as a replacement for TWR, MWR, benchmark, workspace-summary,
returns-series, contribution, attribution, or inspection results. It is an operator and downstream
coordination surface, not a performance result surface.

## Request Contract

| Path parameter | Meaning |
| --- | --- |
| `calculation_id` | Durable calculation identifier returned by the originating analytics endpoint. |

Error behavior:

| Status | Meaning |
| --- | --- |
| `200` | A durable execution record exists and lifecycle metadata is returned. |
| `403` | Enterprise privileged-read authorization is enabled and the caller has neither `operations.runtime.read` nor a matching `X-Portfolio-Id` entitlement for the durable execution `portfolio_id`. |
| `404` | No durable execution record exists for the supplied calculation id. |

When `ENTERPRISE_ENFORCE_PRIVILEGED_READ_AUTHZ=true`, callers must send the normal enterprise
identity headers and either `X-Capabilities: operations.runtime.read` for privileged
operator/support access or `X-Portfolio-Id` matching the durable execution `portfolio_id` for
same-portfolio delegated access. A bare calculation id is not sufficient authority.

## Output Contract

The response model is `app.models.execution_polling.ExecutionResponse`.

Top-level fields:

| Field | Meaning |
| --- | --- |
| `calculation_id` | Durable calculation handle. |
| `analytics_type` | Analytics family, for example `TWR`, `ReturnsSeries`, or `Attribution`. |
| `portfolio_id` | Portfolio identifier when the calculation is portfolio-scoped. |
| `execution_mode` | `sync` or `async`. |
| `status` | Overall lifecycle status such as `pending`, `running`, `complete`, or `failed`. |
| `requested_window` | Normalized request-window metadata captured for support and downstream polling. |
| `input_fingerprint` | Fingerprint of submitted or resolved input where available. |
| `calculation_hash` | Hash of completed output where available. |
| `error_message` | Top-level failure message for failed executions. |
| `created_at_utc`, `started_at_utc`, `completed_at_utc` | Lifecycle timestamps. |

Nested output families:

| Field | Meaning |
| --- | --- |
| `stages[]` | Ordered stage state for submission, retrieval, normalization, execution, lineage, or endpoint-specific stages. |
| `upstream_snapshots[]` | Stateful upstream source provenance, request and response fingerprints, retrieval status, and paging metadata. |
| `compute_job` | Async executor job state, attempt count, lease state, worker identity, and retry or failure details. |
| `async_result` | Endpoint-specific result materialization state and terminal error details. |

## Behavior And Feature Checks

Certified behavior:

- synchronous TWR executions expose completed execution and lineage-materialization stages;
- stateful TWR, MWR, contribution, returns-series, benchmark, and workspace-summary executions expose
  retrieval, normalization, execution, and upstream snapshot metadata where applicable;
- async TWR, benchmark, workspace-summary, returns-series, contribution, and attribution executions
  expose pending compute jobs before worker drain and complete async results after worker drain;
- retryable compute failures expose `compute_job.attempt_count`, `error_type`, `last_error_at_utc`,
  and a pending job state while retry budget remains;
- terminal compute failures expose failed top-level execution state and failed `async_result`
  metadata;
- privileged-read enforcement denies UUID-only or cross-portfolio polling attempts with the
  standard `authorization_policy_denied` envelope while preserving `404` for unknown ids;
- unknown calculation ids return `404` without fabricating a lifecycle record.

## Upstream Integration

This endpoint does not call lotus-core or other upstream services at request time. It reads
lotus-performance durable execution, compute-job, async-result, and upstream snapshot stores.

Upstream source truth is represented through `upstream_snapshots[]`. For stateful analytics-input
surfaces, those snapshots are produced by the analytics endpoint or worker during calculation
sourcing through the lotus-core query-control-plane contracts governed by
`CORE_CONTROL_PLANE_BASE_URL`.

## Downstream Consumers

Known direct downstream consumer:

| Consumer | Current behavior | Certification outcome |
| --- | --- | --- |
| `lotus-risk` | Polls the accepted `poll_path` while waiting for async returns-series integration results. | Uses the canonical path and handles pending, complete, failed, invalid accepted payloads, and polling-budget exhaustion in unit coverage. |

`lotus-gateway` currently handles synchronous performance analytics integration and accepted-payload
replay behavior, but no direct call to `/performance/executions/{calculation_id}` was found during
this slice.

No duplicate lotus-performance polling endpoint was found. Endpoint-specific result routes remain
the strategic result surfaces; this endpoint remains the strategic lifecycle polling surface.

## GitHub Issue Posture

Open issue searches were run for lotus-performance, lotus-risk, and lotus-gateway using execution,
execution status, and performance-executions terms.

Results:

- lotus-performance issue `#83` remains a broad historical stateful-sourcing architecture issue; it
  is not specific to this endpoint and is not closed by this certification slice;
- no endpoint-specific open issue was found for execution polling;
- no downstream migration issue was needed because the known direct downstream consumer already uses
  the canonical `poll_path`.

## Swagger Readiness

Swagger now documents:

- endpoint purpose and result-route relationship;
- `calculation_id` path parameter meaning and example;
- 404 behavior;
- every top-level response field with descriptions and examples;
- stage, upstream snapshot, compute-job, and async-result nested fields.

## Test Pyramid Assessment

| Layer | Coverage | Assessment |
| --- | --- | --- |
| Model/schema | `tests/unit/models/test_execution_polling_models.py` proves translation from durable records into typed polling responses. | Strong for response assembly. |
| Integration route tests | `tests/integration/test_execution_api.py` covers sync, async, stateful stages, retryable compute failure, terminal failure, result availability, portfolio/privileged-read authorization, and 404 behavior. | Strong for endpoint behavior. |
| Docs/OpenAPI | `tests/unit/app/test_execution_openapi_contract.py` checks operation purpose, 404 behavior, path parameter docs, and nested response field descriptions. | Strong after this pass. |
| Downstream | `lotus-risk` polling client tests cover accepted payload validation, pending polling, failure surfacing, and polling-budget exhaustion. | Adequate with no migration issue required. |
| Live proof | Existing integration tests exercise the endpoint through real TestClient requests and worker drain paths. | Adequate for this durable-store polling endpoint. |

## Validation Commands

Focused validation for this certification slice:

```bash
python -m pytest tests/unit/app/test_execution_openapi_contract.py tests/unit/models/test_execution_polling_models.py tests/integration/test_execution_api.py tests/unit/docs/test_public_docs_contract.py -q
python scripts/openapi_quality_gate.py
python scripts/api_vocabulary_inventory.py --validate-only
python -m ruff check app/api/endpoints/executions.py app/models/execution_polling.py tests/unit/app/test_execution_openapi_contract.py tests/unit/models/test_execution_polling_models.py tests/integration/test_execution_api.py tests/unit/docs/test_public_docs_contract.py
python -m ruff format --check app/api/endpoints/executions.py app/models/execution_polling.py tests/unit/app/test_execution_openapi_contract.py tests/unit/models/test_execution_polling_models.py tests/integration/test_execution_api.py tests/unit/docs/test_public_docs_contract.py
python -m mypy --config-file mypy.ini app/api/endpoints/executions.py app/models/execution_polling.py
```
