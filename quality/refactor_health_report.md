# Lotus Performance Refactor Health Report

Report date: 2026-06-13
Branch: `refactor/lp-cr-950-mwr-fx-component`
Baseline source: `quality/baseline_report.md`
Report mode: phase-zero scorecard; complexity regression posture is enforced separately by CI.

## Purpose

This report turns the report-only baseline into the durable before/current scorecard for the
hardening stream. At phase zero, the baseline and current values are intentionally the same unless a
metric has already been remeasured. Future refactor phases should update the `Current` column and
link the commit, command, or CI artifact that proves the change.

## Scorecard Status Model

| Status | Meaning |
| --- | --- |
| `measured` | The value is backed by a command run on this branch. |
| `enforced` | The value is backed by a command run on this branch and by a blocking CI gate. |
| `not-yet-measured` | The quality dimension is required by the goal but tooling or collection has not been added yet. |
| `planned-gate` | The quality dimension should become a progressive CI gate after report-only measurement exists. |

## Code Health

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Python files | 480 | 543 | measured | `rg --files -g '*.py'` |
| Python package markers | 18 | 18 | measured | recursive `__init__.py` count |
| Python LOC | 104,454 | 143,558 | measured | recursive tracked `.py` line count |
| Largest Python file LOC | 2,399 | 2,399 | measured | largest-file inventory in baseline report |
| Largest production file LOC | 1,156 | 1,156 | measured | `app/services/lineage_metadata_store.py` |
| Duplicate code hotspots | 0 | 0 | measured | `quality/duplicate_code_inventory.md` via `scripts/python_duplicate_code_inventory.py` with `--min-lines 12` |
| Dead-code candidates at 60% confidence | unknown | 438 | measured | `quality/dead_code_inventory.md` via `scripts/python_dead_code_inventory.py` |
| Dead-code candidates at 80% confidence | unknown | 0 | measured | `quality/dead_code_inventory.md` via `scripts/python_dead_code_inventory.py` |

## Complexity And Maintainability

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Max cyclomatic complexity | unknown | 7 | enforced | `quality/complexity_inventory.md` via `scripts/python_complexity_inventory.py`; `make quality-complexity-gate` |
| High-complexity functions | unknown | 0 | enforced | rank D-F functions in `quality/complexity_inventory.md`; `make quality-complexity-gate` |
| Average maintainability index | unknown | 55.15 | measured | `quality/complexity_inventory.md` via `scripts/python_complexity_inventory.py` |
| Largest functions by LOC | unknown | 159 | measured | `quality/function_size_inventory.md` via `scripts/python_function_size_inventory.py` |

## Architecture

| Metric | Baseline | Current | Status | Evidence |
| --- | ---: | ---: | --- | --- |
| Import boundary violations | unknown | 0 | measured | `quality/architecture_boundary_inventory.md` via `scripts/python_architecture_boundary_inventory.py` |
| Routers importing infrastructure directly | unknown | 0 | measured | `ROUTER_DIRECT_BOUNDARY_IMPORT` in `quality/architecture_boundary_inventory.md` |
| Domain/application importing framework or infra code | unknown | 0 | measured | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` absent from `quality/architecture_boundary_inventory.md` |
| Large production service hotspots | 3 | 3 | measured | `lineage_metadata_store.py`, `compute_job_store.py`, `stateful_input_service.py` exceed 1,000 LOC |
| Router/middleware oversized function findings (`--threshold 80`) | unknown | 0 | measured | `quality/router_middleware_thinness_inventory.md` via `scripts/python_router_middleware_thinness_inventory.py` |

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
| Test modules | 228 | 259 | measured | `rg --files tests -g 'test_*.py'` |
| Collected tests | 2,035 | 2,563 | measured | `python -m pytest --collect-only -q` |
| Line coverage | unknown | 99% | measured | `quality/coverage_inventory.md` via `make test-coverage` |
| Branch coverage | unknown | not configured | not-yet-measured | `quality/coverage_inventory.md`; branch coverage is not configured in pytest-cov or coverage.py |
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
| README required markers | unknown | 8 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Missing README required markers | unknown | 0 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Wiki source pages | unknown | 20 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Markdown documentation files | unknown | 230 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Endpoint certification docs | unknown | 20 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| API catalog files | unknown | 4 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Docs regression test functions | unknown | 56 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Public definitions missing docstrings | unknown | 988 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |
| Public definition docstring coverage percent | unknown | 12.02 | measured | `quality/documentation_inventory.md` via `scripts/python_documentation_inventory.py` |

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
