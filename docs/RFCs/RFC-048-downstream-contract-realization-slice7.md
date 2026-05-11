# RFC 048 Slice 7 - Downstream Contract Realization

Date: 2026-05-11

Branch: `feat/rfc-048-attribution-industry-alignment`

Gateway PR: `sgajbi/lotus-gateway#207`

Workbench PR: `sgajbi/lotus-workbench#179`

## Scope

Slice 7 made the RFC 048 attribution contract usable by downstream front-office consumers after
Slice 3, Slice 4, Slice 5, and Slice 6 promoted source-owned attribution status, reason codes,
residual materiality, supportability evidence, and data-product posture.

The implementation preserves the ownership boundary:

1. `lotus-performance` owns attribution methodology, period status, reason codes, residual
   materiality, supportability evidence, and lineage semantics.
2. `lotus-gateway` owns the Performance Workspace experience contract and preserves
   `lotus-performance` fields without recomputing attribution totals, statuses, or residuals.
3. `lotus-workbench` consumes the Gateway contract and displays the posture as advisor-facing
   supportability evidence without direct `lotus-performance` coupling.

## Gateway Realization

`lotus-gateway#207` was merged to `main` on 2026-05-11 as
`1dd29ec11703ab384469f13a29020525c7c483b9`.

The Gateway change:

1. added `AttributionReasonView`, `AttributionResidualMaterialityView`, and
   `AttributionSupportabilityEvidenceView` to the Performance Workspace contract;
2. added `status`, `reason_codes`, `reasons`, `residual_materiality`, and
   `supportability_evidence` to `AttributionSummaryView`;
3. added `status`, `reason_codes`, `residual_materiality`, and `supportability_evidence` to
   `PerformanceAttributionTrendRow`;
4. preserved these fields from both workspace summary attribution payloads and direct attribution
   result payloads;
5. strengthened workspace service tests so the new fields are proven on summaries and trend rows;
6. strengthened OpenAPI integration assertions so the added schema properties remain described.

Gateway validation:

```powershell
python -m ruff check src/app/contracts/performance_workspace.py src/app/services/performance_workspace_service.py tests/unit/test_performance_workspace_service.py tests/integration/test_workbench_router.py
# Passed.

python -m pytest tests\unit\test_performance_workspace_service.py tests\integration\test_workbench_router.py -q
# 77 passed.

make lint
# Passed.

make typecheck
# Passed.

make check
# ruff, format check, monetary-float guard, mypy, contract tests, and 491 tests passed.
```

GitHub validation:

1. Feature Lane / Workflow Lint: pass.
2. Feature Lane / Lint Typecheck Unit: pass.
3. PR Merge Gate / Workflow Lint: pass.
4. PR Merge Gate / Lint Typecheck Unit: pass.
5. PR Merge Gate / Integration Tests: pass.
6. PR Merge Gate / Coverage Gate: pass.
7. PR Merge Gate / CI Local Docker Parity: pass.
8. PR Merge Gate / Validate Docker Build: pass.

## Workbench Realization

`lotus-workbench#179` was merged to `main` on 2026-05-11 as
`b2da9ab592301e0021c7c030fb8ccbda0f293cc7`.

The Workbench change:

1. added TypeScript types for attribution reasons, residual materiality, and supportability
   evidence;
2. extended attribution summary and trend-row types with Gateway-owned supportability fields;
3. updated attribution presentation helpers to derive advisor-facing copy from source-owned
   residual materiality and supportability evidence;
4. updated the Performance attribution analysis section so partial or unavailable attribution
   posture is surfaced from source status and reason codes;
5. updated the attribution breakdown to display supportability evidence without reconstructing
   attribution math locally;
6. updated the decision summary so residual and attribution-posture cards reflect the
   `lotus-performance` contract through Gateway;
7. strengthened fixtures and unit/integration tests for the new supportability posture.

Workbench validation:

```powershell
npm run lint
# Passed.

npm run typecheck
# Passed.

npm run test -- tests/unit/performance-attribution-presentations.test.ts tests/unit/performance-analysis-attribution-section.test.tsx tests/integration/performance-analytics-page.test.tsx
# 57 passed.

npm run test
# 164 files and 747 tests passed.

npm run build
# Next.js build passed.
```

GitHub validation:

1. Feature Lane / Workflow Lint: pass.
2. Feature Lane / Lint Typecheck Test: pass.
3. PR Merge Gate / Workflow Lint: pass.
4. PR Merge Gate / Lint Typecheck Coverage Build: pass.
5. PR Merge Gate / Playwright Smoke: pass.
6. PR Merge Gate / CI Local Docker Parity: pass.
7. PR Merge Gate / Validate Docker Build: pass.

## Consumer Classification

| Consumer | Classification | Decision |
| --- | --- | --- |
| `lotus-gateway` | Updated and merged | Required because Gateway owns the Performance Workspace contract consumed by Workbench. |
| `lotus-workbench` | Updated and merged | Required because Workbench displays the attribution posture and must remain Gateway-first. |
| `lotus-report` | No code change required | Search found `/performance/contribution` consumption only; no direct `/performance/attribution` contract usage. |
| `lotus-core` | No code change required | Slice 4 recorded `lotus-core` as source-data authority with no approved RFC 048 upstream contract change. |
| `lotus-platform` | Already aligned in Slice 6 | Platform catalog update was merged through `sgajbi/lotus-platform#324`. |

## Review Decision

Slice 7 is complete. The changed attribution contract is preserved by Gateway, consumed by
Workbench, covered by downstream tests, merged to downstream `main` branches, and no known
downstream consumer reconstructs attribution totals, residual materiality, statuses, or reason codes
locally. Live canonical front-office proof remains scheduled for Slice 10 because that slice owns
runtime evidence across API, Gateway, and Workbench.
