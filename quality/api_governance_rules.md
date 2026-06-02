# Lotus Performance API Governance Rules

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Mode: report-only API completeness rules; this artifact introduces no new blocking CI gate.

## Purpose

This document defines the current report-only API completeness inventory used by the performance
hardening stream. The repository already has a blocking OpenAPI gate in
`scripts/openapi_quality_gate.py`; this inventory does not replace it. It gives maintainers a
measurable backlog for API documentation and error-contract hardening before stricter gates are
promoted.

## Local Command

```powershell
python scripts/openapi_completeness_inventory.py --limit 80
```

The command imports `main.app` and reads the same enriched OpenAPI schema used by Swagger and the
blocking OpenAPI quality gate.

## Report-Only Rules

| Rule | Meaning | Gate posture |
| --- | --- | --- |
| `MISSING_SUMMARY` | Operation has no concise summary. | Report-only; already covered by the blocking OpenAPI quality gate. |
| `MISSING_DESCRIPTION` | Operation has no usage-oriented description. | Report-only; already covered by the blocking OpenAPI quality gate. |
| `MISSING_TAGS` | Operation has no governance tag. | Report-only; already covered by the blocking OpenAPI quality gate. |
| `MISSING_OPERATION_ID` | Operation has no stable operationId. | Report-only; should become regression-blocking only after duplicate operationId posture is also represented. |
| `MISSING_RESPONSES` | Operation has no response map. | Report-only; already covered by the blocking OpenAPI quality gate. |
| `MISSING_SUCCESS_RESPONSE` | Operation has no 2xx response contract. | Report-only; already covered by the blocking OpenAPI quality gate. |
| `MISSING_ERROR_RESPONSE` | Operation has no 4xx, 5xx, or default error response. | Report-only; already covered by the blocking OpenAPI quality gate. |
| `MISSING_SUCCESS_JSON_EXAMPLE` | Successful JSON response has no example. | Report-only; already covered by the blocking OpenAPI quality gate where JSON response content exists. |
| `MISSING_REQUEST_JSON_EXAMPLE` | JSON request body has no example. | Report-only; already covered by the blocking OpenAPI quality gate where JSON request content exists. |
| `ERROR_JSON_MISSING_SCHEMA` | JSON error response has no explicit schema. | Report-only; target for future error-model hardening. |
| `ERROR_JSON_MISSING_EXAMPLE` | JSON error response has no example. | Report-only; target for future validation-error and domain-error examples. |
| `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` | Error response does not expose `application/problem+json` or a named problem/error schema. | Report-only; target for future RFC 7807 consistency work. |

## Promotion Guidance

Do not promote these rules directly to a blocking gate until:

1. the current findings are either fixed or intentionally baselined,
2. FastAPI-generated validation errors have a documented exception or shared problem-detail model,
3. domain error responses have reusable schemas and examples,
4. the blocking OpenAPI quality gate and this inventory are reconciled to avoid duplicate failures,
5. Remote Feature Lane has run the report repeatedly without nondeterministic output.

