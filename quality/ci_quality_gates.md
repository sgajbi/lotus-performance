# Lotus Performance Progressive CI Quality Gates

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Baseline sources: `quality/baseline_report.md`, `quality/refactor_health_report.md`
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
| Combined line coverage | Blocking at 99 percent in PR and main lanes | Capture branch-coverage posture before adding a stricter branch gate. |
| Dependency verification | Blocking through `python -m pip check` and dependency-health scripts | Keep blocking; preserve project-scoped dependency-health evidence. |
| Dependency vulnerabilities | `pip-audit` is available, security audit is already blocking through repo script, and report-only output is captured in `quality/dependency_security_report.md` | Keep the report current when dependency pins, audit tooling, or exception policy changes. |
| OpenAPI quality | Blocking through `scripts/openapi_quality_gate.py`; measured further through `quality/api_completeness_inventory.md`; validation-error examples and default problem-detail schemas are covered | Keep the blocking gate and use the report-only inventory to reduce explicit domain error-schema and problem-detail gaps before adding stricter gates. |
| API vocabulary and no-alias governance | Blocking in feature, PR, and main lanes | Keep blocking and preserve RFC-0067 vocabulary discipline. |
| Migration smoke | Blocking in PR and main lanes | Keep blocking outside feature lane unless a migration-heavy slice needs earlier proof. |
| Docker build | Blocking in PR and main lanes | Keep blocking; no new Docker gate is needed for report-only quality artifacts. |
| Domain data product validation | Blocking locally through `make check` and repo-native command | Confirm whether GitHub workflows should include this explicitly before changing CI. |
| Complexity and maintainability | Measured in `quality/complexity_inventory.md` through `scripts/python_complexity_inventory.py` and `radon` | Keep report-only until a stable baseline, false-positive policy, and remediation guidance exist. |
| Function-size hotspots | Measured in `quality/function_size_inventory.md` through a repo-native standard-library scanner | Use as refactor-planning evidence; do not block CI until stable thresholds and exclusions are agreed. |
| Dead-code detection | Measured in `quality/dead_code_inventory.md` through `scripts/python_dead_code_inventory.py` and `vulture`; 60% findings are dominated by framework/model false positives, while 80% findings are zero | Add reviewed allowlist before considering any regression-blocking gate. |
| Dependency hygiene | Measured in `quality/dependency_hygiene_report.md` through `scripts/python_dependency_hygiene_inventory.py` and `deptry`; direct imported transitive dependencies are closed, leaving four runtime-review DEP002 findings | Review runtime-only declarations before blocking. |
| Python security scanning | Not yet measured through `bandit` | Add report-only Bandit run and compare with existing dependency-health security audit. |
| OpenAPI Spectral linting | Not configured; no `.spectral.yaml` present | Decide whether Spectral adds value beyond the existing OpenAPI gate before adding it. |
| Architecture boundaries | Measured in `quality/architecture_boundary_inventory.md` through `scripts/python_architecture_boundary_inventory.py`; first report shows 25 import-boundary findings | Classify current findings and reduce router/domain boundary drift before adding import-linter or regression-blocking gates. |
| Public docstring coverage | Not configured; `interrogate` not present | Measure before deciding whether public docstrings are a useful gate for this service. |
| Router and middleware thinness | Custom checks not implemented | Add repo-native report-only scripts for direct-infra imports and oversized boundary modules. |
| RFC 7807 error consistency | Measured report-only through `scripts/openapi_completeness_inventory.py`; current inventory shows 17 domain error responses not expressed as problem-detail contracts | Continue moving domain error responses to shared problem-detail schemas/examples before considering regression blocking. |
| Observability and operational contracts | Tests exist but no scorecard metric exists | Generate endpoint/service coverage score for correlation IDs, logs, metrics, and readiness. |

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
3. change workflow files,
4. introduce new CI failures,
5. promote complexity measurement to a blocking CI threshold,
6. claim enterprise-readiness completion.
