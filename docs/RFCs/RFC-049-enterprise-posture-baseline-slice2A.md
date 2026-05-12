# RFC 049 Slice 2A - Enterprise Posture Baseline and Repository Hardening Plan

Date: 2026-05-12
Branch: `draft/rfc-049-composite-performance-alignment`
PR: `sgajbi/lotus-performance#162`
Status: Implemented and locally validated

## Purpose

Slice 2A establishes the implementation-backed enterprise posture baseline for RFC 049 before the
composite implementation expands from persisted member-return facts into operator workflows,
inspector evidence, exports, downstream consumers, and supported-feature promotion.

This slice is corrective as well as forward-looking: Slice 3 through Slice 5 already introduced the
composite source-authority model, persisted member-return facts, internal calculation engine, and
initial public composite TWR API. The review below records the baseline that those slices must obey
and gives the remaining RFC 049 slices explicit hardening closure rules.

## Baseline Reviewed

Reviewed repository areas:

1. repository context and role: `REPOSITORY-ENGINEERING-CONTEXT.md`;
2. runtime topology and enterprise posture: `docs/technical/runtime_topology.md`,
   `docs/standards/enterprise-readiness.md`, `docs/standards/scalability-availability.md`;
3. CI and validation lanes: `Makefile`, `.github/workflows/feature-lane.yml`,
   `.github/workflows/pr-merge-gate.yml`;
4. OpenAPI and vocabulary governance: `scripts/openapi_quality_gate.py`,
   `scripts/api_vocabulary_inventory.py`,
   `docs/standards/api-vocabulary/lotus-performance-api-vocabulary.v1.json`;
5. domain data-product declarations: `contracts/domain-data-products/`;
6. trust telemetry declarations: `contracts/trust-telemetry/`;
7. runtime health and support services: `app/services/runtime_status_service.py`,
   `app/services/durability_health_service.py`, `app/observability.py`;
8. current composite implementation: `app/models/composites.py`, `app/services/composite_metadata_store.py`,
   `app/services/composite_calculation_service.py`, `engine/composites.py`,
   `app/api/endpoints/composites.py`;
9. current composite tests:
   `tests/unit/models/test_composite_models.py`,
   `tests/unit/services/test_composite_metadata_store.py`,
   `tests/unit/engine/test_composites.py`,
   `tests/unit/services/test_composite_calculation_service.py`,
   `tests/integration/test_composites_api.py`,
   `tests/unit/app/test_composites_openapi_contract.py`.

## Findings and Closure Rules

| Area | Classification | Finding | RFC 049 owner | Closure rule |
| --- | --- | --- | --- | --- |
| Repository structure | `already-strong` | The repo already separates API, service, engine, contracts, docs, wiki, tests, and platform-facing scripts. RFC 049 added composite models, metadata store, service, and engine without a monolithic file. | Slice 3-5 implementation | Continue bounded module ownership for worker, operational APIs, inspector, artifacts, and downstream integration. |
| Composite source authority | `fix-in-rfc-049` | Composite definitions, memberships, and member-return facts now have durable models and exact-decimal persisted fact storage, but no batch run/result version store exists yet. | Slice 6/7 | Add batch-capable run/result/versioning model before promoting composite as supported. |
| Public API contract | `fix-in-rfc-049` | `POST /performance/composites/twr` now calculates from persisted member-return facts only. Slice 5 also fixed a vocabulary collision by exposing `beginning_asset_weight` instead of overloading benchmark `weight`. | Slice 5 complete; Slice 13 final certification | Keep OpenAPI/API vocabulary/no-alias gates green after every API expansion. |
| API certification posture | `already-strong` | CI runs OpenAPI quality and API vocabulary gates. The composite endpoint has response schemas, endpoint guidance, examples, and error responses. | Slice 5 and Slice 13 | Every later endpoint must add Swagger descriptions, examples, error handling, and vocabulary inventory updates in the same slice. |
| Data mesh posture | `fix-in-rfc-049` | Existing product contracts cover current performance products. `CompositePerformanceAnalytics:v1` is intentionally not yet declared as supported because batch/recalc/result lineage/export posture is incomplete. | Slice 6 | Add truthful domain data-product and trust telemetry declarations only after the implementation supports them. |
| Observability | `fix-in-rfc-049` | Existing runtime health, readiness, metrics, correlation, and bounded supportability metric patterns are strong. Composite-specific bounded metrics and support labels do not exist yet. | Slice 6/7A | Add composite calculation, batch, inspection, export, and reason-code metrics without sensitive labels. |
| Distributed tracing and correlation | `fix-in-rfc-049` | Request correlation utilities exist. Composite API currently delegates synchronously to persisted facts and does not yet carry a batch or downstream correlation story. | Slice 6/9/12 | Preserve correlation across API, worker, Gateway, Workbench, inspector, and artifacts before live proof. |
| Security and dependency posture | `already-strong` | `make security-audit` is part of feature and merge-gate CI. Operator action guard services and privileged-read audit standards already exist. | Slice 6/13 | Re-run dependency/security gates after each code slice and formally track any unfixed vulnerability. |
| Authorization and privileged operator access | `fix-in-rfc-049` | The initial composite TWR API is not a privileged mutation. Future recalc, publish, restatement, export, and inspection artifact access are privileged operational surfaces. | Slice 6/7A | Add capability/audit treatment for privileged composite operator actions before exposing operational APIs. |
| Audit events | `fix-in-rfc-049` | Composite calculation is currently deterministic and testable, but does not yet emit calculation/recalc/publish/export/inspection audit events. | Slice 6/7A | Add support-safe audit events for operational surfaces with tenant, operator, correlation, and redaction posture where applicable. |
| Health/readiness/runtime status | `fix-in-rfc-049` | Existing `/health`, `/health/live`, `/health/ready`, and runtime status patterns are proven. No composite worker/container readiness exists yet. | Slice 6 | If a separate `lotus-performance-composite-worker` container is introduced, add liveness, readiness, queue, retry, and stuck-run visibility. |
| Query/index and batch scalability | `fix-in-rfc-049` | Member-return facts are persisted, but current slice only supports a synchronous read/calculate path over SQLite-backed metadata. Heavy composite use needs run scoping, indexing, pagination, retention, and worker isolation. | Slice 6/7 | Add storage/index posture and batch performance characterization before bank-buyable support claims. |
| Artifact storage and evidence classification | `fix-in-rfc-049` | Current composite API returns member contribution evidence but no governed CSV/XLSX/Markdown evidence artifacts or lineage manifest. | Slice 7A/11/12 | Generate classified export artifacts and document access boundaries before client-demo support. |
| Docs and wiki posture | `fix-in-rfc-049` | Docs still correctly keep composite unsupported until proof. RFC 049 slice notes are implementation-backed, but Slice 2A was missing and is now added. | Slice 11/14 | Promote wiki/supported-features only after live proof, downstream integration, and final hardening review. |
| CI posture | `already-strong` | Feature and merge gates cover lint, format, typecheck, security, OpenAPI, vocabulary, domain products, tests, coverage, and Docker build. Slice 5 PR checks are green on commit `e664f15`. | Every slice | Do not move slices forward while PR checks are red for the current slice. |

## Immediate Cleanup Completed in This Slice

1. Added this missing Slice 2A evidence note so enterprise posture findings are not stranded in the
   RFC prose.
2. Recorded the Slice 5 API vocabulary correction as an explicit contract-hardening finding:
   composite member weighting uses `beginning_asset_weight`, preserving existing benchmark
   `weight` vocabulary semantics.
3. No code cleanup was performed in this slice because the material weakness was a missing
   governance artifact, not dead runtime code.

## Validation Evidence

Validation already green on the same branch after the Slice 5 correction:

1. `make api-vocabulary-gate`;
2. `python scripts/openapi_quality_gate.py`;
3. `python -m ruff check app\api\endpoints\composites.py app\models\composites.py tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py`;
4. `python -m ruff format --check app\api\endpoints\composites.py app\models\composites.py tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py`;
5. `python -m mypy --config-file mypy.ini`;
6. `python -m pytest tests\integration\test_composites_api.py tests\unit\app\test_composites_openapi_contract.py tests\unit\engine\test_composites.py tests\unit\services\test_composite_calculation_service.py -q`;
7. `python -m pytest tests\unit\docs\test_public_docs_contract.py -q`;
8. `git diff --check`.

GitHub PR #162 checks were green after commit `e664f15`:

1. Feature Lane / Lint Typecheck Security;
2. Feature Lane / Tests (unit);
3. Feature Lane / Workflow Lint;
4. PR Merge Gate / Coverage Gate (Combined);
5. PR Merge Gate / Lint Typecheck Security;
6. PR Merge Gate / Tests (e2e);
7. PR Merge Gate / Tests (integration);
8. PR Merge Gate / Tests (unit);
9. PR Merge Gate / Validate Docker Build;
10. PR Merge Gate / Workflow Lint.

## Next Slice Guardrails

Slice 6 must not simply add a data-product contract. It must close the hardening items above where
they become real implementation surfaces:

1. composite domain-product declaration and trust telemetry only after supported runtime behavior is real;
2. bounded composite metrics and audit events;
3. correlation propagation through API, worker, Gateway, Workbench, inspector, and artifacts;
4. explicit worker/container posture if workload isolation is introduced;
5. retention policy for member-return facts, result versions, lineage, exports, and operator artifacts;
6. security/dependency and CI evidence with no unresolved drift.

## Slice 2A Conclusion

Slice 2A is complete. It did not promote any new supported-feature claim. It converted the
enterprise-hardening expectations in RFC 049 into concrete implementation findings and closure
rules that the remaining slices must satisfy before composite performance can be called
enterprise-grade, production-ready, or bank-buyable.
