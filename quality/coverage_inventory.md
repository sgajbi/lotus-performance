# Lotus Performance Coverage Inventory

Report date: 2026-06-28
Branch: `feature/attribution-branch-coverage-hardening`
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
| Combined line coverage under branch run | 99.38% | `covered_lines / num_statements` from `output/branch-coverage/coverage.json` |
| Covered lines | 21112 | coverage.py `7.10.6` JSON totals |
| Missing lines | 132 | coverage.py `7.10.6` JSON totals |
| Statements | 21244 | coverage.py `7.10.6` JSON totals |
| Combined branch coverage | 96.76% | 4265 covered branches of 4408 total branches |
| Missing branches | 143 | coverage.py `7.10.6` JSON totals |
| Partial branches | 141 | coverage.py `7.10.6` JSON totals |
| Branch-coverage gate | not configured | Report-only baseline; no fail-under threshold is applied. |
| Existing line-coverage gate | unchanged | `make test-coverage` still enforces `coverage report --fail-under=99`. |

## Top Branch Coverage Gaps

| File | Covered branches | Missing branches | Partial branches | Total branches |
| --- | ---: | ---: | ---: | ---: |
| `engine/ror.py` | 43 | 7 | 7 | 50 |
| `app/services/compute_job_store.py` | 67 | 7 | 5 | 74 |
| `app/services/returns_series_service.py` | 162 | 6 | 6 | 168 |
| `engine/policies.py` | 40 | 6 | 6 | 46 |
| `engine/contribution.py` | 28 | 6 | 6 | 34 |
| `app/services/workspace_summary_service.py` | 69 | 5 | 5 | 74 |
| `engine/mwr.py` | 63 | 5 | 5 | 68 |
| `app/services/twr_mode_service.py` | 55 | 5 | 5 | 60 |
| `app/openapi_enrichment.py` | 216 | 4 | 4 | 220 |
| `app/services/stateful_attribution_input_service.py` | 170 | 4 | 4 | 174 |

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
