# Lotus Performance OpenAPI Completeness Inventory

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Command: `python scripts/openapi_completeness_inventory.py --limit 80`
Mode: report-only API governance inventory; no blocking gate changed.

## Summary

| Metric | Value |
| --- | ---: |
| OpenAPI operations | 36 |
| API completeness findings | 12 |
| Distinct rules | 2 |
| Endpoints with findings | 2 |

## Findings By Rule

| Rule | Count |
| --- | ---: |
| `ERROR_JSON_MISSING_SCHEMA` | 6 |
| `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | 6 |

## Most Affected Endpoints

| Endpoint | Findings |
| --- | ---: |
| `POST /performance/attribution` | 8 |
| `GET /performance/attribution/results/{calculation_id}` | 4 |

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
| 7 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `400` | Error response does not expose application/problem+json or a named error/problem schema. |
| 8 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `409` | Error response does not expose application/problem+json or a named error/problem schema. |
| 9 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `422` | Error response does not expose application/problem+json or a named error/problem schema. |
| 10 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `POST /performance/attribution` | `500` | Error response does not expose application/problem+json or a named error/problem schema. |
| 11 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/attribution/results/{calculation_id}` | `404` | Error response does not expose application/problem+json or a named error/problem schema. |
| 12 | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | `GET /performance/attribution/results/{calculation_id}` | `409` | Error response does not expose application/problem+json or a named error/problem schema. |
