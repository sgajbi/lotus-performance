# RFC 048 Slice 5 - API Contract, OpenAPI, and Error Handling Certification

Date: 2026-05-11

Branch: `feat/rfc-048-attribution-industry-alignment`

## Scope

Slice 5 certified the attribution API contract after the RFC 048 status, reason, residual
materiality, supportability, and stateful source-alignment work. The purpose was to make the API
usable by Gateway, Workbench, operations, and implementation reviewers without relying on code
inspection.

## Implementation

The implementation strengthened the API contract in three areas:

1. `POST /performance/attribution` now documents success, async, request, conflict, source-contract,
   and unexpected-failure paths in OpenAPI.
2. `GET /performance/attribution/results/{calculation_id}` now documents pending, missing, and
   failed async result states.
3. Attribution request and response schemas now include implementation-backed private-banking
   examples for stateful sourcing, controlled period status, reason codes, supportability evidence,
   and residual materiality.

The contract continues to expose only supported attribution truth. It does not promote fixed-income
factor attribution, derivative attribution, sleeve attribution, composite attribution, benchmark
version, classification version, calendar policy, derivative/short flags, or fee/tax/income
breakout claims.

## Error Contract

| Error path | Contract posture |
| --- | --- |
| Invalid request shape | `400`/validation detail depending on FastAPI/Pydantic request stage. |
| No resolved periods | `400` engine input error. |
| Duplicate async payload drift | `409` conflict. |
| Missing async result | `404` on result retrieval. |
| Failed async execution | `409` on result retrieval. |
| Missing benchmark assignment | `422` source-contract failure in stateful mode. |
| Unsupported stateful mode or group dimension | `422` source-contract/request capability failure. |
| Missing FX for mixed-currency stateful attribution | `422` source-contract failure. |
| Upstream source unavailable or inconsistent source alignment | `503` from stateful source-normalization paths. |
| Unexpected request resolution failure | `500` with controlled request-resolution detail. |

## Tests Added Or Strengthened

1. `tests/unit/app/test_attribution_openapi_contract.py`
   - proves attribution endpoint descriptions include front-office/private-banking usage guidance;
   - proves documented response paths include `202`, `400`, `409`, `422`, and `500`;
   - proves async result retrieval documents pending, missing, and failed-result states;
   - proves request examples and response examples include implementation-backed attribution
     status, reason, supportability, and residual-materiality fields.
2. Existing attribution model and integration tests were rerun to ensure schema documentation did
   not drift from runtime behavior.

## Validation Evidence

```powershell
python -m ruff check app\api\endpoints\performance.py app\models\attribution_analytics_requests.py app\models\attribution_responses.py tests\unit\app\test_attribution_openapi_contract.py
# All checks passed.

python -m pytest tests\unit\app\test_attribution_openapi_contract.py tests\unit\models\test_attribution_models.py tests\integration\test_attribution_api.py -q
# 43 passed.

python scripts\openapi_quality_gate.py
# OpenAPI quality gate passed for lotus-performance.

python scripts\api_vocabulary_inventory.py --validate-only
# API vocabulary inventory gate passed (no drift).
```

## Review Decision

Slice 5 is complete for the approved RFC 048 scope. The API is better documented for integration,
support, and operations, while preserving domain boundaries and not overclaiming unsupported
attribution capabilities.
