# RFC 049 Slice 5 - Public Composite API Contract

Status: completed

Branch: `draft/rfc-049-composite-performance-alignment`

PR: `sgajbi/lotus-performance#162`

Completed: 2026-05-12

## Purpose

Slice 5 exposes the first public composite API while preserving the RFC 049 architecture boundary:
composite TWR is calculated from persisted member-return facts only. The endpoint does not accept
ad hoc member returns and does not fan out to portfolio TWR at request time.

## Implementation

| Area | Files | Outcome |
| --- | --- | --- |
| API models | `app/models/composites.py` | Added `CompositeTWRRequest`, `CompositeTWRResponse`, period evidence, and member contribution response models with descriptions and examples. |
| Endpoint | `app/api/endpoints/composites.py` | Added `POST /performance/composites/twr` over the persisted-fact calculation service. |
| App wiring | `main.py` | Registered the composite endpoint router under `/performance`. |
| Integration tests | `tests/integration/test_composites_api.py` | Proves definition/fact seeding, successful persisted-fact composite TWR, member contribution weights, methodology id, and unknown-composite 404 behavior. |
| OpenAPI tests | `tests/unit/app/test_composites_openapi_contract.py` | Proves the API contract documents persisted facts, no ad hoc returns, no hidden request-time fan-out, response evidence, dispersion, and member weights. |

## API Contract

Route:

```text
POST /performance/composites/twr
```

Request:

1. `calculation_id` for idempotency, lineage, and support;
2. `composite_id`;
3. `period_start`;
4. `period_end`.

Response:

1. calculation status: `READY`, `DEGRADED`, or `BLOCKED`;
2. cumulative linked composite TWR as a decimal ratio;
3. period-level asset-weighted return evidence;
4. ready/excluded member counts;
5. equal-weight dispersion when at least two ready members exist;
6. member-level beginning-asset weights and contribution evidence;
7. bounded reason codes for degraded and blocked states;
8. methodology id `persisted_member_return_asset_weighted_twr_v1`.

## Current Capability Boundary

This slice exposes a public API, but it still does not promote composite support as a product claim
until later RFC 049 slices complete endpoint certification, data-product declaration, inspector/export
evidence, docs/wiki productization, downstream integration, live proof, and final closure.

## Validation

```powershell
python -m ruff check app\api\endpoints\composites.py app\models\composites.py main.py tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py
python -m ruff format --check app\api\endpoints\composites.py app\models\composites.py main.py tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py
python -m mypy --config-file mypy.ini
python -m pytest tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py -q
python -m pytest tests\unit\docs\test_public_docs_contract.py -q
git diff --check
```

Result:

- Ruff targeted check -> passed.
- Ruff format targeted check -> passed.
- Mypy -> passed, 167 source files.
- Composite API/OpenAPI/engine/service tests -> 9 passed.
- Docs contract tests -> 42 passed.
- `git diff --check` -> passed.
