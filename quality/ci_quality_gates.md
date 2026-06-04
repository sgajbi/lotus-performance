# Lotus Performance Progressive CI Quality Gates

Report date: 2026-06-04
Branch: `feat/performance-hardening-wave-11`
Baseline sources: `quality/baseline_report.md`, `quality/refactor_health_report.md`, `quality/quality_scorecard.md`
Mode: report-only gate map; this artifact introduces no new blocking CI gate.

## Purpose

This document maps the performance hardening quality program to the repository's actual CI lanes.
It is intentionally progressive: new enterprise-grade gates should first produce repeatable
measurements, then block regressions against an agreed baseline, and only then enforce strict
thresholds. The goal is real quality convergence, not a cosmetic checklist that cannot be run by
developers or GitHub Actions.

## Current Blocking CI Lanes

| Lane | Trigger | Current blocking checks |
| --- | --- | --- |
| Remote Feature Lane | Pushes to non-`main` branches and manual dispatch | workflow lint, dependency verification, Ruff lint and format, monetary float guard, no-alias guard, mypy, OpenAPI gate, API vocabulary gate, security audit, unit tests |
| Pull Request Merge Gate | Pull requests targeting `main` and manual dispatch | workflow lint, dependency verification, Ruff lint and format, monetary float guard, no-alias guard, mypy, OpenAPI gate, API vocabulary gate, migration smoke, security audit, unit, integration, and e2e tests, combined coverage floor at 99 percent, Docker build |
| Main Releasability Gate | Pushes to `main` and manual dispatch | PR-grade checks rerun on `main`, combined coverage floor at 99 percent, coverage artifact publication, Docker build |
| PR Auto Merge | Pull request lifecycle events | queues merge-commit auto-merge and branch deletion after required checks pass; this is release automation, not an independent quality gate |

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
| Combined line coverage | Blocking at 99 percent in PR and main lanes | Capture branch-coverage posture before adding a stricter branch gate. |
| Dependency verification | Blocking through `python -m pip check` and dependency-health scripts | Keep blocking; preserve project-scoped dependency-health evidence. |
| Dependency vulnerabilities | `pip-audit` is available, security audit is already blocking through repo script, and report-only output is captured in `quality/dependency_security_report.md` | Keep the report current when dependency pins, audit tooling, or exception policy changes. |
| OpenAPI quality | Blocking through `scripts/openapi_quality_gate.py`; measured further through `quality/api_completeness_inventory.md`; clean API completeness inventory is guarded by `tests/unit/scripts/test_openapi_completeness_inventory.py` | Keep the blocking gate and unit-level clean-inventory guard; only add a separate workflow gate if the report remains stable and adds value beyond existing OpenAPI checks. |
| API vocabulary and no-alias governance | Blocking in feature, PR, and main lanes | Keep blocking and preserve RFC-0067 vocabulary discipline. |
| Quality baseline snapshot workflow | Non-blocking report run in `.github/workflows/quality-baseline.yml`; generates and uploads all quality-family inventory artifacts | Keep as a reporting aid while quality targets and thresholds are stabilized. |
| Migration smoke | Blocking in PR and main lanes | Keep blocking outside feature lane unless a migration-heavy slice needs earlier proof. |
| Docker build | Blocking in PR and main lanes | Keep blocking; no new Docker gate is needed for report-only quality artifacts. |
| Domain data product validation | Blocking locally through `make check` and repo-native command | Confirm whether GitHub workflows should include this explicitly before changing CI. |
| Complexity and maintainability | Measured in `quality/complexity_inventory.md` through `scripts/python_complexity_inventory.py` and `radon` | Keep report-only until a stable baseline, false-positive policy, and remediation guidance exist. |
| Function-size hotspots | Measured in `quality/function_size_inventory.md` through a repo-native standard-library scanner | Use as refactor-planning evidence; do not block CI until stable thresholds and exclusions are agreed. |
| Duplicate code hotspots | Measured in `quality/duplicate_code_inventory.md` through `scripts/python_duplicate_code_inventory.py`; current report shows 0 duplicate hotspot groups at `--min-lines 12` | Keep report-only until duplicate-family policy and remediation thresholds are aligned with the enterprise refactor roadmap. |
| Dead-code detection | Measured in `quality/dead_code_inventory.md` through `scripts/python_dead_code_inventory.py` and `vulture`; 60% findings are dominated by framework/model false positives, while 80% findings are zero | Add reviewed allowlist before considering any regression-blocking gate. |
| Dependency hygiene | Measured in `quality/dependency_hygiene_report.md` through `scripts/python_dependency_hygiene_inventory.py` and `deptry`; direct imported transitive dependencies are closed, and reviewed runtime-only DEP002 declarations are explicitly allowlisted in the repo scanner | Keep report-only until the allowlist policy and CI placement are stable. |
| Python security scanning | Measured in `quality/python_security_inventory.md` through `scripts/python_security_inventory.py` and `bandit`; current scan has zero high, medium, and low findings, with two targeted skipped tests for reviewed environment-name false positives | Keep report-only until the targeted environment-name exception policy and CI placement are stable. |
| Documentation readiness | Measured in `quality/documentation_inventory.md` through `scripts/python_documentation_inventory.py`; current report shows 8/8 README markers, 20 wiki pages, 230 markdown files, 20 endpoint certification docs, 4/4 API catalog files, 56 docs regression test functions, and 12.02 percent public definition docstring coverage | Keep report-only until docstring scope, generated/model exclusions, and remediation thresholds are agreed. |
| OpenAPI Spectral linting | Not configured; no `.spectral.yaml` present | Decide whether Spectral adds value beyond the existing OpenAPI gate before adding it. |
| Architecture boundaries | Measured in `quality/architecture_boundary_inventory.md` through `scripts/python_architecture_boundary_inventory.py`; latest report shows 0 import-boundary findings | Keep report-only while router/core and domain/application boundary policy is operationalized into reusable boundary contracts. |
| Public docstring coverage | Not configured; `interrogate` not present | Measure before deciding whether public docstrings are a useful gate for this service. |
| Router and middleware thinness | Measured report-only in `quality/router_middleware_thinness_inventory.md` through `scripts/python_router_middleware_thinness_inventory.py`; current snapshot shows 4 router findings and 0 middleware findings at `--threshold 80` | Keep report-only until false-positive policy and refactoring-remediation workflow are established, then move this family toward regression gating. |
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
3. reduce measured complexity, function-size, and reviewed dead-code hotspots through bounded slices,
4. review runtime-only dependency declarations before removing or allowlisting them,
5. update `quality/refactor_health_report.md` as each dimension moves from `not-yet-measured` to `measured`.

## Non-Goals For This Slice

This slice does not:

1. change application behavior,
2. change API or Swagger contracts,
3. introduce new CI failures,
4. promote complexity measurement to a blocking CI threshold,
5. claim enterprise-readiness completion.
