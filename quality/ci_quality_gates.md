# Lotus Performance Progressive CI Quality Gates

Report date: 2026-06-13
Branch: `lp-cr-1400-source-quality-findings`
Baseline sources: `quality/baseline_report.md`, `quality/refactor_health_report.md`, `quality/quality_scorecard.md`
Mode: progressive gate map; remediated complexity, architecture-boundary, router-thinness, duplicate-code, and Python security posture is now enforced in CI.

## Purpose

This document maps the performance hardening quality program to the repository's actual CI lanes.
It is intentionally progressive: new enterprise-grade gates should first produce repeatable
measurements, then block regressions against an agreed baseline, and only then enforce strict
thresholds. The goal is real quality convergence, not a cosmetic checklist that cannot be run by
developers or GitHub Actions.

## Current Blocking CI Lanes

| Lane | Trigger | Current blocking checks |
| --- | --- | --- |
| Remote Feature Lane | Pushes to non-`main` branches and manual dispatch | workflow lint, static quality gates, contract/security gates, unit tests |
| Pull Request Merge Gate | Pull requests targeting `main` and manual dispatch | workflow lint, static quality gates, contract/security gates, compatibility `Lint Typecheck Security` aggregate, migration smoke, unit, integration, and e2e tests, combined coverage floor at 99 percent, Docker build |
| Main Releasability Gate | Pushes to `main` and manual dispatch | workflow lint, static quality gates, contract/security gates, migration smoke, unit, integration, and e2e tests, combined coverage floor at 99 percent, coverage artifact publication, Docker build |
| PR Auto Merge | Pull request lifecycle events | queues merge-commit auto-merge and branch deletion after required checks pass; this is release automation, not an independent quality gate |

`Static Quality Gates` verifies installed dependencies, Ruff lint/format, monetary-float safety,
complexity regression, architecture-boundary regression, router/middleware thinness, duplicate-code regression, no-alias governance,
and mypy type safety. `Contract Security Gates` verifies
OpenAPI quality, API vocabulary governance, migration smoke where the lane requires it, and
dependency security plus first-party Python static security. These jobs run in parallel before test execution to reduce CI wall-clock time
without dropping any gate.

The PR lane also publishes `PR Merge Gate / Lint Typecheck Security` as a lightweight aggregate over
the split static-quality and contract-security jobs. It exists to satisfy the current GitHub
required-check contract while preserving the faster parallel lane structure.

GitHub Actions jobs use `make install-ci` so CI installs runtime and development dependencies without
performing developer-workstation pre-commit hook setup. Local contributors should continue using
`make install` when they need the hook installation side effect.

## Gate Promotion Model

| Phase | CI posture | Promotion standard |
| --- | --- | --- |
| Phase 0 - Inventory | Report-only artifacts track current facts and gaps | Measurement source is documented and reproducible locally. |
| Phase 1 - Report-only tooling | CI may generate artifacts without failing the lane | Tool output is stable enough to review and false positives are understood. |
| Phase 2 - Regression blocking | CI fails only when the branch worsens against the accepted baseline | Baseline file, local command, ownership, and remediation guidance exist. |
| Phase 3 - Strict enterprise gate | CI fails when the repository misses the agreed target | Threshold is justified by repeated green runs and aligned with PR Merge Gate expectations. |

No gate should move from one phase to the next until it has:

1. a repository-native command or script,
2. a documented local developer command,
3. an explicit CI lane placement,
4. a baseline artifact or threshold,
5. a false-positive and exception policy,
6. remediation guidance,
7. evidence that the gate is not duplicating another stronger check.

## Current Gate Family Status

| Gate family | Current status | Next target |
| --- | --- | --- |
| Ruff lint and format | Blocking in all quality lanes through `make lint` | Keep blocking; use as the style and simple-correctness baseline. |
| Monetary float guard | Blocking through `make lint` | Keep blocking for finance-domain numeric safety. |
| mypy typecheck | Blocking in feature, PR, and main lanes | Keep blocking; expand typed boundary cleanup through normal refactor slices. |
| Unit tests | Blocking in feature, PR, and main lanes | Keep blocking; add focused tests when refactoring hotspots. |
| Integration and e2e tests | Blocking in PR and main lanes | Keep blocking at merge/release lanes; use targeted local subsets during slices. |
| Test taxonomy | Measured in `quality/test_taxonomy_inventory.md` through `scripts/python_test_taxonomy_inventory.py`; current AST inventory shows 453 integration/API/runtime test functions and 107 contract/governance test functions | Keep report-only until taxonomy labels and uncategorized-test policy are stable. |
| Combined line coverage | Blocking at 99 percent in PR and main lanes; locally measured in `quality/coverage_inventory.md` through `make test-coverage` | Keep blocking and preserve the local coverage inventory as scorecard evidence; capture branch-coverage posture before adding a stricter branch gate. |
| Dependency verification | Blocking through `python -m pip check` and dependency-health scripts | Keep blocking; preserve project-scoped dependency-health evidence. |
| Dependency vulnerabilities | `pip-audit` is available, security audit is already blocking through repo script, and report-only output is captured in `quality/dependency_security_report.md` | Keep the report current when dependency pins, audit tooling, or exception policy changes. |
| OpenAPI quality | Blocking through `scripts/openapi_quality_gate.py`; measured further through `quality/api_completeness_inventory.md`; clean API completeness inventory is guarded by `tests/unit/scripts/test_openapi_completeness_inventory.py` | Keep the blocking gate and unit-level clean-inventory guard; only add a separate workflow gate if the report remains stable and adds value beyond existing OpenAPI checks. |
| API vocabulary and no-alias governance | Blocking in feature, PR, and main lanes | Keep blocking and preserve RFC-0067 vocabulary discipline. |
| Quality baseline snapshot workflow | Non-blocking report run in `.github/workflows/quality-baseline.yml`; generates and uploads all quality-family inventory artifacts | Keep as a reporting aid while quality targets and thresholds are stabilized. |
| Migration smoke | Blocking in PR and main lanes | Keep blocking outside feature lane unless a migration-heavy slice needs earlier proof. |
| Docker build | Blocking in PR and main lanes | Keep blocking; no new Docker gate is needed for report-only quality artifacts. |
| Domain data product validation | Blocking locally through `make check` and repo-native command | Confirm whether GitHub workflows should include this explicitly before changing CI. |
| Complexity and maintainability | Max cyclomatic complexity and D-F function count are blocking through `make quality-complexity-gate`; maintainability index remains measured in `quality/complexity_inventory.md` through `scripts/python_complexity_inventory.py` and `radon` | Keep max CC at `8` and D-F count at `0`; keep MI report-only until a stable remediation threshold and exception policy exist. |
| Function-size hotspots | Measured in `quality/function_size_inventory.md` through a repo-native standard-library scanner | Use as refactor-planning evidence; do not block CI until stable thresholds and exclusions are agreed. |
| Duplicate code hotspots | Blocking through `make quality-duplicate-code-gate`; current report shows 7 duplicate hotspot groups at `--min-lines 12` with `--max-groups 7` | Keep blocking against the current measured baseline while refactor slices reduce duplicate hotspots; future increases require a documented reason and a better reusable abstraction decision. |
| Dead-code detection | Measured in `quality/dead_code_inventory.md` through `scripts/python_dead_code_inventory.py` and `vulture`; 60% findings are dominated by framework/model false positives, while 80% findings are zero | Add reviewed allowlist before considering any regression-blocking gate. |
| Dependency hygiene | Measured in `quality/dependency_hygiene_report.md` through `scripts/python_dependency_hygiene_inventory.py` and `deptry`; direct imported transitive dependencies are closed, and reviewed runtime-only DEP002 declarations are explicitly allowlisted in the repo scanner | Keep report-only until the allowlist policy and CI placement are stable. |
| Python security scanning | Blocking through `make python-security-gate`; current Bandit scan has zero high, medium, and low findings, with two targeted skipped tests for reviewed environment-name false positives | Keep blocking for first-party runtime paths; future exceptions must be targeted, documented, and test-backed. |
| Documentation readiness | Measured in `quality/documentation_inventory.md` through `scripts/python_documentation_inventory.py`; current report shows 8/8 README markers, 20 wiki pages, 230 markdown files, 20 endpoint certification docs, 4/4 API catalog files, 56 docs regression test functions, and 12.02 percent public definition docstring coverage | Keep report-only until docstring scope, generated/model exclusions, and remediation thresholds are agreed. |
| OpenAPI Spectral linting | Not configured; no `.spectral.yaml` present | Decide whether Spectral adds value beyond the existing OpenAPI gate before adding it. |
| Architecture boundaries | Blocking through `make quality-architecture-gate`; latest report shows 0 import-boundary findings and the script enforces `--max-findings 0` | Keep blocking for the current router/core/domain import rules; add new boundary rules only after report-only inventory proves stability. |
| Public docstring coverage | Not configured; `interrogate` not present | Measure before deciding whether public docstrings are a useful gate for this service. |
| Router and middleware thinness | Blocking through `make quality-router-thinness-gate`; current snapshot shows 0 router findings and 0 middleware findings at `--threshold 80` with `--max-findings 0` | Keep blocking for the current router/middleware function-size threshold; revisit only with documented exceptions and tests. |
| RFC 7807 error consistency | Measured report-only through `scripts/openapi_completeness_inventory.py`; current inventory shows 0 error responses missing named problem/error schemas | Keep the report-only inventory clean while separately planning any runtime migration from legacy string-detail errors to full RFC 7807 payloads. |
| Observability and operational contracts | Measured in `quality/observability_readiness_inventory.md` through `scripts/python_observability_readiness_inventory.py`; current report shows 28/28 expected implementation markers, 0 missing markers, and 287 family-mapped readiness test functions | Keep report-only until marker ownership, overlap-aware test counting, and CI placement are stable. |

## Recommended Lane Placement For New Gates

| Gate class | First report-only lane | First blocking lane | Strict lane |
| --- | --- | --- | --- |
| Fast static checks | Remote Feature Lane | Remote Feature Lane | PR Merge Gate and Main Releasability Gate |
| Medium static analysis | Remote Feature Lane artifact | PR Merge Gate | Main Releasability Gate |
| Heavy test or coverage checks | PR Merge Gate artifact | PR Merge Gate | Main Releasability Gate |
| Docker or runtime parity checks | PR Merge Gate artifact | PR Merge Gate | Main Releasability Gate |
| Platform or cross-repo checks | Manual dispatch or platform automation | PR Merge Gate only when deterministic | Main Releasability Gate after repeated stability |

## Near-Term Quality Slices

The next hardening commits should stay small and add proof in this order:

1. reduce measured API error-contract gaps for error examples, explicit schemas, and problem-detail consistency,
2. reduce measured architecture-boundary findings through bounded router/domain extraction slices,
3. keep reducing measured complexity, function-size, and reviewed dead-code hotspots through bounded slices,
4. review runtime-only dependency declarations before removing or allowlisting them,
5. measure branch-coverage posture before proposing a stricter branch gate.

## Non-Goals For This Slice

This slice does not:

1. change application behavior,
2. change API or Swagger contracts,
3. promote maintainability index, function-size, dead-code, or documentation metrics to blocking gates,
4. claim enterprise-readiness completion.
