# Lotus Performance Coverage Inventory

Report date: 2026-06-28
Branch: `feature/enterprise-backend-refactor-baseline`
Mode: report-only local coverage evidence; the blocking coverage gate already exists in PR and main lanes.

## Purpose

This report captures the current repository-native coverage posture for the performance hardening
stream. It closes the previous scorecard gap where line coverage was listed as unknown, while
keeping branch coverage explicitly unconfigured rather than implying a measurement that does not
exist.

## Command

```powershell
make ci
```

## Coverage Gate Posture

| Metric | Value | Evidence |
| --- | ---: | --- |
| Unit tests under coverage | 2,912 passed | `COVERAGE_FILE=.coverage.unit python -m pytest tests/unit --cov=app --cov=engine --cov=core --cov=adapters --cov-report=` |
| Integration tests under coverage | 308 passed | `COVERAGE_FILE=.coverage.integration python -m pytest tests/integration --cov=app --cov=engine --cov=core --cov=adapters --cov-report=` |
| E2E tests under coverage | 21 passed | `COVERAGE_FILE=.coverage.e2e python -m pytest tests/e2e --cov=app --cov=engine --cov=core --cov=adapters --cov-report=` |
| Combined line coverage | 99% | `python -m coverage combine .coverage.unit .coverage.integration .coverage.e2e`; `python -m coverage report --fail-under=99` (`TOTAL 21244 statements, 173 missed`) |
| Combined line-coverage gate | passed | `coverage report --fail-under=99` completed successfully |
| Branch coverage | not configured | No `[tool.coverage]` branch setting is present and CI invokes `pytest --cov` without branch coverage. |

## CI Alignment

The PR Merge Gate and Main Releasability workflows already run unit, integration, and e2e suites
with coverage artifacts and enforce the same combined 99% line-coverage floor. This local report
does not introduce a new gate; it records the current branch evidence for the before/after quality
scorecard.

## Follow-Up

Branch coverage should remain a governed follow-up until the repo has:

1. a configured branch-coverage collection setting,
2. an accepted baseline,
3. a false-positive and exception policy,
4. remediation guidance for low-value branch gaps in Pydantic/FastAPI/model glue,
5. CI lane placement that does not duplicate the existing 99% line-coverage gate.
