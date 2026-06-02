# Lotus Performance OpenAPI Completeness Inventory

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Command: `python scripts/openapi_completeness_inventory.py --limit 80`
Mode: report-only API governance inventory; no blocking gate changed.

## Summary

| Metric | Value |
| --- | ---: |
| OpenAPI operations | 36 |
| API completeness findings | 66 |
| Distinct rules | 3 |
| Endpoints with findings | 36 |

## Findings By Rule

| Rule | Count |
| --- | ---: |
| `ERROR_JSON_MISSING_EXAMPLE` | 28 |
| `ERROR_JSON_MISSING_SCHEMA` | 14 |
| `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | 24 |

## Most Affected Endpoints

| Endpoint | Findings |
| --- | ---: |
| `POST /performance/attribution` | 8 |
| `GET /performance/attribution/results/{calculation_id}` | 5 |
| `GET /performance/lineage/{calculation_id}` | 5 |
| `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | 5 |
| `POST /performance/composites/twr` | 4 |
| `POST /performance/composites/inspect` | 3 |
| `GET /performance/executions/{calculation_id}` | 3 |
| `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}` | 3 |
| `GET /performance/inspections/{inspection_id}` | 2 |
| `GET /performance/twr/results/{calculation_id}` | 2 |
| `POST /integration/benchmarks/exposure-context` | 1 |
| `GET /integration/capabilities` | 1 |
| `GET /integration/recovery-drills` | 1 |
| `POST /integration/recovery-drills/run` | 1 |
| `POST /integration/returns/series` | 1 |

## Interpretation

The enriched OpenAPI schema has zero findings for missing operation summaries, descriptions, tags,
operation IDs, success responses, error responses, request-body examples, and successful JSON
response examples under this inventory. The remaining measurable API completeness gap is error
contract maturity:

1. FastAPI-generated validation error responses expose JSON without examples.
2. Several domain error responses expose JSON examples but no explicit error schema.
3. Default and domain error responses are not yet consistently represented as RFC 7807
   `application/problem+json` or named problem/error schemas.

This is real hardening backlog, not a Swagger cosmetics issue. It affects how reliably enterprise
consumers can generate clients, reason about failure modes, and certify error-handling behavior.

## Findings

| Rank | Rule | Endpoint | Response | Description |
| ---: | --- | --- | --- | --- |
| 1 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /integration/benchmarks/exposure-context` | `422` | JSON error response is missing an OpenAPI example. |
| 2 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /integration/capabilities` | `422` | JSON error response is missing an OpenAPI example. |
| 3 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /integration/recovery-drills` | `422` | JSON error response is missing an OpenAPI example. |
| 4 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /integration/recovery-drills/run` | `422` | JSON error response is missing an OpenAPI example. |
| 5 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /integration/returns/series` | `422` | JSON error response is missing an OpenAPI example. |
| 6 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /integration/returns/series/results/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 7 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /integration/runtime-recoveries` | `422` | JSON error response is missing an OpenAPI example. |
| 8 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /integration/runtime-retention-cleanups` | `422` | JSON error response is missing an OpenAPI example. |
| 9 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /integration/runtime-retention-cleanups/run` | `422` | JSON error response is missing an OpenAPI example. |
| 10 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /integration/runtime-work-items` | `422` | JSON error response is missing an OpenAPI example. |
| 11 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/attribution/results/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 12 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/benchmark` | `422` | JSON error response is missing an OpenAPI example. |
| 13 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/benchmark/results/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 14 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/composites/inspect` | `422` | JSON error response is missing an OpenAPI example. |
| 15 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/contribution` | `422` | JSON error response is missing an OpenAPI example. |
| 16 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/contribution/results/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 17 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/executions/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 18 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/inspections/twr` | `422` | JSON error response is missing an OpenAPI example. |
| 19 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/inspections/{inspection_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 20 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}` | `422` | JSON error response is missing an OpenAPI example. |
| 21 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/lineage/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 22 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `422` | JSON error response is missing an OpenAPI example. |
| 23 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/mandate-health-context` | `422` | JSON error response is missing an OpenAPI example. |
| 24 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/mwr` | `422` | JSON error response is missing an OpenAPI example. |
| 25 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/twr` | `422` | JSON error response is missing an OpenAPI example. |
| 26 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/twr/results/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 27 | `ERROR_JSON_MISSING_EXAMPLE` | `POST /performance/workspace-summary` | `422` | JSON error response is missing an OpenAPI example. |
| 28 | `ERROR_JSON_MISSING_EXAMPLE` | `GET /performance/workspace-summary/results/{calculation_id}` | `422` | JSON error response is missing an OpenAPI example. |
| 29 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `400` | JSON error response is missing an explicit schema. |
| 30 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `409` | JSON error response is missing an explicit schema. |
| 31 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `422` | JSON error response is missing an explicit schema. |
| 32 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `500` | JSON error response is missing an explicit schema. |
| 33 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/attribution/results/{calculation_id}` | `404` | JSON error response is missing an explicit schema. |
| 34 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/attribution/results/{calculation_id}` | `409` | JSON error response is missing an explicit schema. |
| 35 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/composites/inspect` | `404` | JSON error response is missing an explicit schema. |
| 36 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/composites/twr` | `404` | JSON error response is missing an explicit schema. |
| 37 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/composites/twr` | `422` | JSON error response is missing an explicit schema. |
| 38 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/executions/{calculation_id}` | `404` | JSON error response is missing an explicit schema. |
| 39 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}` | `404` | JSON error response is missing an explicit schema. |
| 40 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}` | `503` | JSON error response is missing an explicit schema. |
| 41 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `404` | JSON error response is missing an explicit schema. |
| 42 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `503` | JSON error response is missing an explicit schema. |
| 43 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /` | `default` | Error response does not expose application/problem+json or a named error/problem schema. |
| 44 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /health` | `default` | Error response does not expose application/problem+json or a named error/problem schema. |
| 45 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /health/live` | `default` | Error response does not expose application/problem+json or a named error/problem schema. |
| 46 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /health/ready` | `default` | Error response does not expose application/problem+json or a named error/problem schema. |
| 47 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /integration/runtime-status` | `default` | Error response does not expose application/problem+json or a named error/problem schema. |
| 48 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /metrics` | `default` | Error response does not expose application/problem+json or a named error/problem schema. |
| 49 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `400` | Error response does not expose application/problem+json or a named error/problem schema. |
| 50 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `409` | Error response does not expose application/problem+json or a named error/problem schema. |
| 51 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `422` | Error response does not expose application/problem+json or a named error/problem schema. |
| 52 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `500` | Error response does not expose application/problem+json or a named error/problem schema. |
| 53 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/attribution/results/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 54 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/attribution/results/{calculation_id}` | `409` | Error response does not expose application/problem+json or a named error/problem schema. |
| 55 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/composites/inspect` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 56 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/composites/twr` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 57 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/composites/twr` | `422` | Error response does not expose application/problem+json or a named error/problem schema. |
| 58 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/executions/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 59 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/inspections/{inspection_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 60 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 61 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/inspections/{inspection_id}/artifacts/{artifact_name}` | `503` | Error response does not expose application/problem+json or a named error/problem schema. |
| 62 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 63 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}` | `503` | Error response does not expose application/problem+json or a named error/problem schema. |
| 64 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 65 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `503` | Error response does not expose application/problem+json or a named error/problem schema. |
| 66 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/twr/results/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |

