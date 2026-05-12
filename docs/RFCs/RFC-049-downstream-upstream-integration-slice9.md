# RFC-049 Slice 9 - Downstream and Upstream Integration Realization

Status: implemented and locally validated

Date: 2026-05-12

## Scope

Slice 9 realized the approved composite performance API through the known product-facing
downstream path without moving source authority out of `lotus-performance`.

The slice deliberately kept `lotus-performance` as the composite calculation, inspection,
lineage, restatement, and evidence authority. Gateway and Workbench changes are consumer
alignment only.

## Repository Outcomes

### lotus-performance

No new source API change was required in this slice. Existing RFC-049 surfaces remain:

1. `POST /performance/composites/twr`
2. `POST /performance/composites/inspect`

These endpoints are the authoritative producer contracts for persisted composite TWR and
composite inspection evidence.

### lotus-gateway

Branch: `draft/rfc-049-composite-performance-alignment`

Commit: `4047c24 feat: expose composite performance gateway routes`

Changes:

1. added `POST /api/v1/performance/composites/twr`;
2. added `POST /api/v1/performance/composites/inspect`;
3. added typed Gateway request and response contracts;
4. propagated correlation and governed caller context;
5. preserved `lotus-performance` payloads without recalculating composite returns, member
   weights, dispersion, findings, lineage, restatement evidence, or classified artifacts;
6. added OpenAPI documentation and integration tests for the new route family;
7. added analytics-client methods for the `lotus-performance` composite endpoints.

Validation:

1. `python -m ruff check src\app\contracts\composite_performance.py src\app\routers\composite_performance.py src\app\clients\lotus_analytics_client.py tests\unit\test_upstream_clients.py tests\integration\test_composite_performance_router.py`
2. `python -m ruff format --check src\app\contracts\composite_performance.py src\app\routers\composite_performance.py src\app\clients\lotus_analytics_client.py tests\unit\test_upstream_clients.py tests\integration\test_composite_performance_router.py`
3. `python -m pytest tests\unit\test_upstream_clients.py -q` - `115 passed`
4. `python -m pytest tests\integration\test_composite_performance_router.py -q` - `4 passed`
5. `python -m mypy --config-file pyproject.toml src` - no issues
6. `git diff --check`

### lotus-workbench

Branch: `draft/rfc-049-composite-performance-alignment`

Commit: `c5333fe feat: add composite performance workbench clients`

Changes:

1. added typed Workbench API helpers for composite TWR and composite inspection;
2. routed both helpers through the existing Workbench BFF/Gateway boundary;
3. added bounded analytics UI observability entries for composite TWR and inspection;
4. added tests proving Workbench uses Gateway/BFF paths and does not call `lotus-performance`
   directly;
5. avoided a premature UI panel because RFC-049 has not yet completed live proof,
   documentation productization, and final supported-feature promotion.

Validation:

1. `npm test -- --run tests/unit/workbench-api.test.ts tests/unit/analytics-observability-metrics.test.ts` - `64 passed`
2. `npm run typecheck`
3. `git diff --check`

## Upstream Classification

No upstream source-authority repo change was required for this slice.

Classification:

1. `lotus-core` - no change. Current RFC-049 persisted member-return facts already carry the
   required asset/currency fields for the approved composite TWR scope.
2. `lotus-manage` - no change. Composite definition and membership source-authority modeling is
   represented in `lotus-performance` RFC-049 metadata foundations; no active manage API contract
   is consumed yet.
3. `lotus-report` - no change. Composite outputs are not yet report-job or proof-pack inputs.
4. `lotus-risk`, `lotus-advise`, `lotus-ai` - no direct contract dependency found for the
   approved Slice 9 realization.

## Review Notes

1. Gateway and Workbench do not recompute composite figures.
2. Gateway preserves source-owned statuses, reason codes, findings, lineage, restatement evidence,
   and classified artifact payloads.
3. Workbench now has a typed consumer seam for future product UI work, but RFC-049 supported
   features remain branch-level until live proof and final documentation closure are complete.
4. The implementation keeps the product path Gateway-first and avoids direct browser access to
   `lotus-performance`.

## Remaining RFC-049 Work

Slice 9 is complete enough to proceed after PR checks are green. Later slices must still complete:

1. QA regression pack;
2. implementation proof on the canonical stack;
3. methodology and product documentation;
4. hardening review;
5. final closure, wiki publication, and supported-features promotion or explicit no-promotion
   decision.

