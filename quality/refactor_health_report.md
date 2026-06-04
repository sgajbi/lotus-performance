# Lotus Performance Refactor Health Report

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Baseline source: `quality/baseline_report.md`
Report mode: phase-zero scorecard; no blocking gate is introduced by this artifact.

## Purpose

This report turns the report-only baseline into the durable before/current scorecard for the
hardening stream. At phase zero, the baseline and current values are intentionally the same unless a
metric has already been remeasured. Future refactor phases should update the `Current` column and
link the commit, command, or CI artifact that proves the change.

## Scorecard Status Model

| Status | Meaning |
| --- | --- |
| `measured` | The value is backed by a command run on this branch. |
| `not-yet-measured` | The quality dimension is required by the goal but tooling or collection has not been added yet. |
| `planned-gate` | The quality dimension should become a progressive CI gate after report-only measurement exists. |

## Code Health

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Python files | 480 | 480 | measured | `rg --files -g '*.py'` |
| Python package markers | 18 | 18 | measured | recursive `__init__.py` count |
| Python LOC | 104,454 | 104,454 | measured | recursive `.py` line count |
| Largest Python file LOC | 2,399 | 2,399 | measured | largest-file inventory in baseline report |
| Largest production file LOC | 1,156 | 1,156 | measured | `app/services/lineage_metadata_store.py` |
| Duplicate code hotspots | unknown | unknown | not-yet-measured | clone/duplication tooling not configured |
| Dead-code candidates at 60% confidence | unknown | 438 | measured | `quality/dead_code_inventory.md` via `scripts/python_dead_code_inventory.py` |
| Dead-code candidates at 80% confidence | unknown | 0 | measured | `quality/dead_code_inventory.md` via `scripts/python_dead_code_inventory.py` |

## Complexity And Maintainability

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 44 | measured | `quality/complexity_inventory.md` via `scripts/python_complexity_inventory.py` |
| High-complexity functions | unknown | 21 | measured | rank D-F functions in `quality/complexity_inventory.md` |
| Average maintainability index | unknown | 53.87 | measured | `quality/complexity_inventory.md` via `scripts/python_complexity_inventory.py` |
| Largest functions by LOC | unknown | 509 | measured | `quality/function_size_inventory.md` via `scripts/python_function_size_inventory.py` |

## Architecture

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Import boundary violations | unknown | 0 | measured | `quality/architecture_boundary_inventory.md` via `scripts/python_architecture_boundary_inventory.py` |
| Routers importing infrastructure directly | unknown | 0 | measured | `ROUTER_DIRECT_BOUNDARY_IMPORT` in `quality/architecture_boundary_inventory.md` |
| Domain/application importing framework or infra code | unknown | 0 | measured | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` absent from `quality/architecture_boundary_inventory.md` |
| Large production service hotspots | 3 | 3 | measured | `lineage_metadata_store.py`, `compute_job_store.py`, `stateful_input_service.py` exceed 1,000 LOC |

## API Quality

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| OpenAPI lint findings | unknown | unknown | not-yet-measured | Spectral not configured |
| OpenAPI operations | unknown | 36 | measured | `quality/api_completeness_inventory.md` via `scripts/openapi_completeness_inventory.py` |
| API completeness findings | unknown | 0 | measured | `quality/api_completeness_inventory.md` via `scripts/openapi_completeness_inventory.py` |
| Operations missing descriptions | unknown | 0 | measured | `MISSING_DESCRIPTION` absent from `quality/api_completeness_inventory.md` |
| JSON error responses missing examples | unknown | 0 | measured | `ERROR_JSON_MISSING_EXAMPLE` absent from `quality/api_completeness_inventory.md` |
| JSON error responses missing explicit schema | unknown | 0 | measured | `ERROR_JSON_MISSING_SCHEMA` absent from `quality/api_completeness_inventory.md` |
| Error responses not expressed as problem-detail contracts | unknown | 0 | measured | `ERROR_RESPONSE_NOT_PROBLEM_DETAIL` absent from `quality/api_completeness_inventory.md` |

## Testing

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Test modules | 228 | 228 | measured | `rg --files tests -g 'test_*.py'` |
| Collected tests | 2,035 | 2,035 | measured | `python -m pytest --collect-only -q` |
| Line coverage | unknown | unknown | not-yet-measured | coverage run not captured in baseline slice |
| Branch coverage | unknown | unknown | not-yet-measured | branch coverage not configured as a scorecard input |
| Integration/API/runtime test functions | unknown | 453 | measured | `quality/test_taxonomy_inventory.md` via `scripts/python_test_taxonomy_inventory.py` |
| Contract/governance test functions | unknown | 107 | measured | `quality/test_taxonomy_inventory.md` via `scripts/python_test_taxonomy_inventory.py` |

## Security And Dependencies

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Bandit high findings | unknown | 0 | measured | `quality/python_security_inventory.md` via `scripts/python_security_inventory.py` |
| Bandit medium findings | unknown | 0 | measured | `quality/python_security_inventory.md` via `scripts/python_security_inventory.py` |
| Bandit low findings | unknown | 0 | measured | `quality/python_security_inventory.md` via `scripts/python_security_inventory.py` |
| Dependency vulnerabilities | unknown | 0 | measured | `quality/dependency_security_report.md` via repo-native dependency-health audit |
| Dependency hygiene findings | unknown | 0 | measured | `quality/dependency_hygiene_report.md` via `scripts/python_dependency_hygiene_inventory.py` |

## Operational Readiness

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Operational readiness implementation markers | unknown | 28 | measured | `quality/observability_readiness_inventory.md` via `scripts/python_observability_readiness_inventory.py` |
| Missing operational readiness markers | unknown | 0 | measured | `quality/observability_readiness_inventory.md` via `scripts/python_observability_readiness_inventory.py` |
| Correlation propagation markers | unknown | 6 | measured | `correlation_propagation` family in `quality/observability_readiness_inventory.md` |
| Structured logging markers | unknown | 6 | measured | `structured_logging` family in `quality/observability_readiness_inventory.md` |
| Metrics markers | unknown | 6 | measured | `metrics` family in `quality/observability_readiness_inventory.md` |
| Health/readiness markers | unknown | 6 | measured | `health_readiness` family in `quality/observability_readiness_inventory.md` |
| Health/metrics endpoint markers | unknown | 4 | measured | `health_metrics_endpoints` family in `quality/observability_readiness_inventory.md` |
| Mapped observability/readiness test functions | unknown | 287 | measured | family-mapped test-function count in `quality/observability_readiness_inventory.md`; counts can overlap across families |

## Documentation

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| README completeness | unknown | unknown | planned-gate | public docs tests exist, but scorecard not generated |
| Wiki/RFC/runbook coverage | unknown | unknown | planned-gate | docs tests exist, but coverage inventory not generated |
| Public docstring coverage | unknown | unknown | not-yet-measured | `interrogate` not configured |
| API catalog completeness | unknown | unknown | planned-gate | OpenAPI inventory score not generated |

## Phase-Zero Interpretation

The measured baseline proves that the repository already has a substantial test surface and a large
production/runtime footprint. It does not yet prove enterprise-readiness completion. The immediate
quality-program gap is not lack of aspiration; it is that several requested dimensions are not yet
repeatably measured or expressed as progressive gates.

## Next Updates

Future commits should update this report when they:

1. add non-blocking quality tooling,
2. generate a new measured scorecard value,
3. split or reduce a hotspot module,
4. add a new CI quality gate,
5. convert a `not-yet-measured` dimension into `measured`,
6. convert a report-only measurement into a regression-blocking or strict gate.
