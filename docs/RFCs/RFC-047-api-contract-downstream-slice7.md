# RFC 047 Slice 7 - API Contract And Downstream Consumer Alignment

## Scope Completed

Slice 7 aligned the contribution evidence contract across the governed downstream front-office path.

1. `lotus-gateway` now preserves `lotus-performance` contribution-owned portfolio return instead of overwriting it with TWR return.
2. `lotus-gateway` carries contribution `smoothing_evidence` and `source_economics_evidence` into the Workbench performance workspace contract.
3. `lotus-workbench` has typed contribution smoothing and source-economics evidence fields.
4. `lotus-workbench` renders exact source-owned contribution evidence statuses and source reason codes in the Performance Drivers module.
5. Tests prove Gateway does not synthesize contribution totals and Workbench does not invent contribution quality state.

## Cross-Repository Changes

| Repository | Branch | PR | Evidence |
| --- | --- | --- | --- |
| `lotus-gateway` | `feat/rfc047-contribution-contract-alignment` | `sgajbi/lotus-gateway#206` | Commit `77677c6` preserves contribution evidence in the workspace contract. |
| `lotus-workbench` | `feat/rfc047-contribution-contract-alignment` | `sgajbi/lotus-workbench#177` | Commit `2c00efa` surfaces contribution evidence in the Workbench UI. |

## Gateway Evidence

Local validation:

1. `python -m pytest tests/unit/test_performance_workspace_service.py tests/unit/test_upstream_clients.py -q`
   - Result: `153 passed`.
2. `python -m ruff check src/app/contracts/performance_workspace.py src/app/services/performance_workspace_service.py tests/unit/test_performance_workspace_service.py`
   - Result: passed.
3. `make check`
   - Result: passed.
   - Coverage included ruff, format check, monetary-float guard, mypy, Workbench contract gate, and `491` unit/contract tests.

GitHub CI:

1. `Feature Lane / Lint Typecheck Unit` passed.
2. `Feature Lane / Workflow Lint` passed.
3. `PR Merge Gate / CI Local Docker Parity` passed.
4. `PR Merge Gate / Coverage Gate` passed.
5. `PR Merge Gate / Integration Tests` passed.
6. `PR Merge Gate / Lint Typecheck Unit` passed.
7. `PR Merge Gate / Validate Docker Build` passed.
8. `PR Merge Gate / Workflow Lint` passed.

## Workbench Evidence

Local validation:

1. `npm run typecheck`
   - Result: passed.
2. `npm run lint`
   - Result: passed with no ESLint warnings or errors.
3. `npm test -- tests/unit/performance-summary-contributors-section.test.tsx tests/integration/performance-analytics-page.test.tsx`
   - Result: `48 passed`.
4. `npm test`
   - Result: `164` test files passed, `746` tests passed.

GitHub CI:

1. `Feature Lane / Workflow Lint` passed at the time this slice evidence was recorded.
2. `Feature Lane / Lint Typecheck Test` passed.
3. `PR Merge Gate / Workflow Lint` passed.
4. `PR Merge Gate / Lint Typecheck Coverage Build` passed.
5. `PR Merge Gate / Playwright Smoke` passed.
6. `PR Merge Gate / Validate Docker Build` passed.
7. `PR Merge Gate / CI Local Docker Parity` passed.

## Critical Review

What was strengthened:

1. Gateway no longer treats contribution return as a derivative of the selected TWR basis.
2. Source-economics and smoothing evidence now travel from `lotus-performance` through Gateway to the front-office UI.
3. Workbench displays exact upstream statuses and reason codes, avoiding local inference or aspirational quality labels.
4. Fixture-backed tests now include contribution source-economics and smoothing evidence.

Closure assessment:

1. Gateway and Workbench CI finished green.
2. No additional `lotus-core` changes were required for this slice.
3. Slice 7 is complete and ready for Slice 8 sequencing.
