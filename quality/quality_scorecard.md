# Lotus Performance Refactor Quality Scorecard

Report date: 2026-06-12
Branch: `refactor/lp-cr-845-benchmark-request-resolution`
Baseline source: `quality/baseline_report.md`
Current source: `quality/refactor_health_report.md`
Mode: phase-zero scorecard; no blocking gate is introduced by this artifact.

## Purpose

This document is the first before/after quality scorecard for the performance hardening stream.
It is intended to track measurable quality posture change over refactor phases, where the same
metrics in each section are updated with each meaningful slice.

## Scorecard

### Code Health

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Python files | 480 | 540 | 60 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python package markers | 18 | 18 | 0 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Python LOC | 104,454 | 121,272 | 16,818 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest Python file LOC | 2,399 | 2,399 | 0 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Largest production file LOC | 1,156 | 1,156 | 0 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Python test modules | 228 | 256 | 28 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |
| Collected tests | 2,035 | 2,407 | 372 | measured | `quality/baseline_report.md`; `quality/refactor_health_report.md` |

### Complexity And Maintainability

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 9 | n/a | measured | `quality/complexity_inventory.md`; `quality/refactor_health_report.md` |
| High-complexity functions (D-F) | unknown | 0 | n/a | measured | `quality/complexity_inventory.md`; `quality/refactor_health_report.md` |
| Average maintainability index | unknown | 55.26 | n/a | measured | `quality/complexity_inventory.md`; `quality/refactor_health_report.md` |
| Largest functions by LOC | unknown | 159 | n/a | measured | `quality/function_size_inventory.md`; `quality/refactor_health_report.md` |

### Architecture

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Import-boundary findings | unknown | 0 | n/a | measured | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md` |
| Routers with infrastructure imports | unknown | 0 | n/a | measured | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md` |
| Domain/application with infra/framework imports | unknown | 0 | n/a | measured | `quality/architecture_boundary_inventory.md`; `quality/refactor_health_report.md` |
| Large production service hotspots (LOC > 1000) | 3 | 3 | 0 | measured | `quality/refactor_health_report.md`; `quality/architecture_boundary_inventory.md` |
| Router/middleware oversized function findings (`--threshold 80`) | unknown | 0 | n/a | measured | `quality/router_middleware_thinness_inventory.md`; `quality/refactor_health_report.md` |

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
| Line coverage | unknown | 99% | n/a | measured | `quality/coverage_inventory.md`; `quality/refactor_health_report.md` |
| Branch coverage | unknown | not configured | n/a | not-yet-measured | `quality/coverage_inventory.md`; `quality/refactor_health_report.md` |
| Integration/API/runtime test functions | unknown | 453 | n/a | measured | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md` |
| Contract/governance test functions | unknown | 107 | n/a | measured | `quality/test_taxonomy_inventory.md`; `quality/refactor_health_report.md` |

### Security and Dependencies

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Bandit high findings | unknown | 0 | n/a | measured | `quality/python_security_inventory.md`; `quality/refactor_health_report.md` |
| Bandit medium findings | unknown | 0 | n/a | measured | `quality/python_security_inventory.md`; `quality/refactor_health_report.md` |
| Dependency vulnerability findings | unknown | 0 | n/a | measured | `quality/dependency_security_report.md`; `quality/refactor_health_report.md` |
| Dependency hygiene findings | unknown | 0 | n/a | measured | `quality/dependency_hygiene_report.md`; `quality/refactor_health_report.md` |

### Operational Readiness

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| Operational readiness markers | unknown | 28 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Missing readiness markers | unknown | 0 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Correlation propagation markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Structured logging markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Metrics markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |
| Health/readiness markers | unknown | 6 | n/a | measured | `quality/observability_readiness_inventory.md`; `quality/refactor_health_report.md` |

### Documentation

| Metric | Baseline | Current | Delta | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- |
| README markers required | unknown | 8 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Missing README markers | unknown | 0 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Wiki pages | unknown | 20 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |
| Public definition docstring coverage | unknown | 12.02 | n/a | measured | `quality/documentation_inventory.md`; `quality/refactor_health_report.md` |

## Current Improvement Signal

| Signal | Value | Note |
| --- | ---: | --- |
| Total metrics tracked | 39 | All metrics in this file are measured or explicitly called out as not-yet-measured. |
| Measured metrics | 38 | Remaining gaps are primarily branch coverage and a few baseline historical values remain for future slices. |
| Not-yet-measured metrics | 1 | Branch coverage remains unconfigured and untracked on this stream. |

## Method Note

- This phase is report-only. Values are intentionally conservative and map to artifacts already
  generated from repository-native scripts.
- `n/a` indicates that a comparable historical pre-baseline value is not yet available in-repo.
- The next slice should replace `not-yet-measured` entries first and add explicit trend deltas.
