# Lotus Performance Refactor Quality Scorecard

Report date: 2026-06-28
Branch: `feature/attribution-branch-coverage-hardening`
Baseline source: `quality/baseline_report.md`
Current source: `quality/refactor_health_report.md`
Mode: phase-zero scorecard; static-quality enforcement includes complexity, architecture,
router-thinness, duplicate-code, repository hygiene, and observability-readiness gates.

## Purpose

This document is the first before/after quality scorecard for the performance hardening stream.
It is intended to track measurable quality posture change over refactor phases, where the same
metrics in each section are updated with each meaningful slice.

## Scorecard

### Code Health

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Python files | 480 | 567 | 87 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python package markers | 18 | 18 | 0 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python LOC | 104,454 | 143,274 | 38,820 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest Python file LOC | 2,399 | 2,503 | 104 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest production file LOC | 1,156 | 1,503 | 347 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Python test modules | 228 | 275 | 47 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Collected tests | 2,035 | 3,302 | 1,267 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Duplicate code hotspots | 0 | 0 | 0 | enforced | `quality/duplicate_code_inventory.md`; `quality/refactor_health_report.md`; `make quality-duplicate-code-gate` |
| Tracked local byproduct findings | unknown | 0 | n/a | enforced | `scripts/repository_hygiene_gate.py`; `make repository-hygiene-gate`; `quality/refactor_health_report.md` |

### Complexity And Maintainability

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 5 | n/a | enforced | `quality/complexity_inventory.md`; `quality/refactor_health_report.md`; `make quality-complexity-gate` |
| High-complexity functions (D-F) | unknown | 0 | n/a | enforced | `quality/complexity_inventory.md`; `quality/refactor_health_report.md`; `make quality-complexity-gate` |
| Average maintainability index | unknown | 54.91 | n/a | measured | `quality/complexity_inventory.md`; `quality/refactor_health_report.md` |
| Largest functions by LOC | unknown | 59 | n/a | measured | `quality/function_size_inventory.md`; `quality/refactor_health_report.md`; LP-CR-1502 moved `_build_workspace_summary_response(...)` out of the top-25 table, and the largest production functions now measure `59` lines |

### Architecture

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Import-boundary findings | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Routers with infrastructure imports | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Domain/application with infra/framework imports | unknown | 0 | n/a | enforced | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md`; `make quality-architecture-gate` |
| Large production service hotspots (LOC > 1000) | 3 | 8 | 5 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Router/middleware oversized function findings (`--threshold 80`) | unknown | 0 | n/a | enforced | `quality/router_middleware_thinness_inventory.md`; `quality/refactor_health_report.md`; `make quality-router-thinness-gate` |

### API Quality

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| OpenAPI operations | unknown | 36 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| OpenAPI findings | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| JSON error examples present | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| Error responses with schema | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |
| Error responses missing RFC 7807 pattern | unknown | 0 | n/a | measured | `quality/api_completeness_inventory.md`; `quality/refactor_health_report.md` |

### Testing

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Line coverage | unknown | 99.38% | n/a | measured | `quality/coverage_inventory.md`; `quality/refactor_health_report.md` |
| Branch coverage | unknown | 96.76% | n/a | measured | `quality/coverage_inventory.md`; `quality/refactor_health_report.md`; `make branch-coverage-baseline` |
| Integration/API/runtime test functions | unknown | 600 | n/a | measured | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md` |
| Contract/governance test functions | unknown | 108 | n/a | measured | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md` |

### Security and Dependencies

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Bandit high findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Bandit medium findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Bandit low findings | unknown | 0 | n/a | enforced | `quality/python_security_inventory.md`; `quality/refactor_health_report.md`; `make python-security-gate` |
| Dependency vulnerability findings | unknown | 0 | n/a | measured | `quality/dependency_security_report.md`; `quality/refactor_health_report.md` |
| Dependency hygiene findings | unknown | 0 | n/a | measured | `quality/dependency_hygiene_report.md`; `quality/refactor_health_report.md` |

### Operational Readiness

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Operational readiness markers | unknown | 28 | n/a | enforced | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md`; `make quality-observability-readiness-gate` |
| Missing readiness markers | unknown | 0 | n/a | enforced | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md`; `make quality-observability-readiness-gate` |
| Correlation propagation markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Structured logging markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Metrics markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Health/readiness markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Demo API certification command | unknown | 1 | n/a | measured | `make demo-api-certification`; `quality/refactor_health_report.md` |

### Documentation

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| README markers required | unknown | 8 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Missing README markers | unknown | 0 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Wiki pages | unknown | 20 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Public definition docstring coverage | unknown | 11.85 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |

## Current Improvement Signal

| Signal | Value | Note |
| --- | ---: | --- |
| Total metrics tracked | 43 | All metrics in this file are now measured, with selected zero-finding signals enforced separately. |
| Measured metrics | 43 | Eleven measured metrics are now also enforced through blocking static-quality or security gates. Branch coverage is measured report-only and is not promoted to a gate. |
| Not-yet-measured metrics | 0 | The scorecard no longer carries an unmeasured branch-coverage entry. OpenAPI Spectral and public-docstring gate decisions remain outside this scorecard until scoped separately. |

## Method Note

- Values are intentionally conservative and map to artifacts already generated from
  repository-native scripts; selected zero-finding signals are now blocking gates.
- `n/a` indicates that a comparable historical pre-baseline value is not yet available in-repo.
- The next slice should review the branch-coverage gap profile before proposing any threshold,
  exception policy, or CI lane placement.
