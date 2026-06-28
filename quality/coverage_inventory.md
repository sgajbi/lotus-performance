# Lotus Performance Coverage Inventory

Report date: 2026-06-28
Branch: `feature/stateful-attribution-branch-hardening`
Mode: report-only local coverage evidence; the blocking line-coverage gate remains unchanged.

## Purpose

This report captures the current repository-native coverage posture for the performance hardening
stream. Line coverage remains enforced separately through `make test-coverage` and the PR/main
coverage gates. Branch coverage is now measured as report-only evidence so the repository can
establish a baseline, review false positives, and decide future lane placement without creating a
noisy blocker.

## Command

```powershell
make branch-coverage-baseline
```

## Coverage Gate Posture

| Metric | Value | Evidence |
| --- | ---: | --- |
| Branch coverage collection | enabled | `pytest --cov-branch` in `make branch-coverage-baseline` |
| Combined line coverage under branch run | 99.58% | `covered_lines / num_statements` from `output/branch-coverage/coverage.json` |
| Covered lines | 21154 | coverage.py `7.14.3` JSON totals |
| Missing lines | 90 | coverage.py `7.14.3` JSON totals |
| Statements | 21244 | coverage.py `7.14.3` JSON totals |
| Combined branch coverage | 98.00% | 4318 covered branches of 4406 total branches |
| Missing branches | 88 | coverage.py `7.14.3` JSON totals |
| Partial branches | 88 | coverage.py `7.14.3` JSON totals |
| Branch-coverage gate | not configured | Report-only baseline; no fail-under threshold is applied. |
| Existing line-coverage gate | unchanged | `make test-coverage` still enforces `coverage report --fail-under=99`. |

## Top Branch Coverage Gaps

| File | Covered branches | Missing branches | Partial branches | Total branches |
| --- | ---: | ---: | ---: | ---: |
| `app/services/stateful_input_service.py` | 128 | 4 | 4 | 132 |
| `app/services/twr_service.py` | 114 | 4 | 4 | 118 |
| `app/services/inspection/reconciliation.py` | 96 | 4 | 4 | 100 |
| `app/services/inspection/source_economics.py` | 58 | 4 | 4 | 62 |
| `app/workers/compute_executor_worker.py` | 40 | 4 | 4 | 44 |
| `app/models/twr_requests.py` | 61 | 3 | 3 | 64 |
| `app/services/inspection/twr_inspection_service.py` | 43 | 3 | 3 | 46 |
| `app/services/stateful_mwr_input_service.py` | 41 | 3 | 3 | 44 |
| `app/services/stateful_contribution_input_service.py` | 39 | 3 | 3 | 42 |
| `app/services/execution_registry.py` | 29 | 3 | 3 | 32 |

## CI Alignment

The PR Merge Gate and Main Releasability workflows continue to enforce the combined 99% line
coverage floor. This report does not introduce a new blocking gate. It creates the accepted
measurement surface needed before any branch-coverage threshold, diff-coverage policy, exception
policy, or GitHub lane placement can be proposed.

## Follow-Up

Branch coverage should remain report-only until the repo has:

1. repeated baseline runs across local and GitHub evidence,
2. reviewed exclusions for framework, generated-model, and defensive branch gaps,
3. an exception policy for low-value glue-code branches,
4. remediation guidance for branch gaps that hide business or operator behavior,
5. CI lane placement that does not duplicate the existing 99% line-coverage gate.
