# Lotus Performance OpenAPI Completeness Inventory

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Command: `python scripts/openapi_completeness_inventory.py --limit 80`
Mode: report-only API governance inventory; no blocking gate changed.

## Summary

| Metric | Value |
| --- | ---: |
| OpenAPI operations | 36 |
| API completeness findings | 26 |
| Distinct rules | 2 |
| Endpoints with findings | 6 |

## Findings By Rule

| Rule | Count |
| --- | ---: |
| `ERROR_JSON_MISSING_SCHEMA` | 13 |
| `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | 13 |

## Most Affected Endpoints

| Endpoint | Findings |
| --- | ---: |
| `POST /performance/attribution` | 8 |
| `GET /performance/attribution/results/{calculation_id}` | 4 |
| `POST /performance/composites/twr` | 4 |
| `GET /performance/lineage/{calculation_id}` | 4 |
| `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | 4 |
| `POST /performance/composites/inspect` | 2 |

## Interpretation

The enriched OpenAPI schema has zero findings for missing operation summaries, descriptions, tags,
operation IDs, success responses, error responses, request-body examples, successful JSON response
examples, validation-error examples, and synthetic default problem-detail schemas under this
inventory. The remaining measurable API completeness gap is domain error contract maturity:

1. Several domain error responses expose JSON examples but no explicit error schema.
2. Default and domain error responses are not yet consistently represented as RFC 7807
   `application/problem+json` or named problem/error schemas.

This is real hardening backlog, not a Swagger cosmetics issue. It affects how reliably enterprise
consumers can generate clients, reason about failure modes, and certify error-handling behavior.

## Findings

| Rank | Rule | Endpoint | Response | Description |
| ---: | --- | --- | --- | --- |
| 1 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `400` | JSON error response is missing an explicit schema. |
| 2 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `409` | JSON error response is missing an explicit schema. |
| 3 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `422` | JSON error response is missing an explicit schema. |
| 4 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/attribution` | `500` | JSON error response is missing an explicit schema. |
| 5 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/attribution/results/{calculation_id}` | `404` | JSON error response is missing an explicit schema. |
| 6 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/attribution/results/{calculation_id}` | `409` | JSON error response is missing an explicit schema. |
| 7 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/composites/inspect` | `404` | JSON error response is missing an explicit schema. |
| 8 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/composites/twr` | `404` | JSON error response is missing an explicit schema. |
| 9 | `ERROR_JSON_MISSING_SCHEMA` | `POST /performance/composites/twr` | `422` | JSON error response is missing an explicit schema. |
| 10 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}` | `404` | JSON error response is missing an explicit schema. |
| 11 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}` | `503` | JSON error response is missing an explicit schema. |
| 12 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `404` | JSON error response is missing an explicit schema. |
| 13 | `ERROR_JSON_MISSING_SCHEMA` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `503` | JSON error response is missing an explicit schema. |
| 14 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `400` | Error response does not expose application/problem+json or a named error/problem schema. |
| 15 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `409` | Error response does not expose application/problem+json or a named error/problem schema. |
| 16 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `422` | Error response does not expose application/problem+json or a named error/problem schema. |
| 17 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `500` | Error response does not expose application/problem+json or a named error/problem schema. |
| 18 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/attribution/results/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 19 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/attribution/results/{calculation_id}` | `409` | Error response does not expose application/problem+json or a named error/problem schema. |
| 20 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/composites/inspect` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 21 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/composites/twr` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 22 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/composites/twr` | `422` | Error response does not expose application/problem+json or a named error/problem schema. |
| 23 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 24 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}` | `503` | Error response does not expose application/problem+json or a named error/problem schema. |
| 25 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 26 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/lineage/{calculation_id}/artifacts/{artifact_name}` | `503` | Error response does not expose application/problem+json or a named error/problem schema. |
