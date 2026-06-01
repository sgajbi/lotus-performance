# Lotus Performance Refactor Quality Baseline

Baseline date: 2026-06-02
Branch: `feat/performance-hardening-wave-8`
Baseline commit: `1bb6f26`
Mode: report-only baseline; no new blocking quality gate is introduced by this artifact.

## Purpose

This report establishes the first measured quality baseline for the performance hardening stream.
It is intentionally conservative: values below are recorded only when gathered from the current
worktree during this slice. Missing measurements are listed as setup gaps so future commits can add
tooling without pretending coverage already exists.

## Measured Baseline

| Area | Current value | Evidence |
| --- | ---: | --- |
| Python files | 480 | `rg --files -g '*.py'` |
| Python package markers | 18 | recursive `__init__.py` count |
| Python LOC | 104,454 | recursive `.py` line count |
| Test modules | 228 | `rg --files tests -g 'test_*.py'` |
| Collected tests | 2,035 | `python -m pytest --collect-only -q` |
| Configured CI workflows | 4 | `.github/workflows/{feature-lane,pr-merge-gate,main-releasability,pr-auto-merge}.yml` |
| Existing configured local tools | Ruff, mypy, pytest, pytest-cov, pytest-benchmark | `pyproject.toml` |
| Available dependency audit tool | `pip-audit 2.10.0` | `python -m pip_audit --version` |

## Largest Python Files By LOC

| Rank | File | Lines |
| ---: | --- | ---: |
| 1 | `tests/unit/services/test_runtime_status_service.py` | 2,399 |
| 2 | `tests/unit/app/test_request_path_runtime_settings.py` | 2,128 |
| 3 | `tests/integration/test_performance_api.py` | 1,793 |
| 4 | `tests/integration/test_contribution_api.py` | 1,691 |
| 5 | `tests/integration/test_attribution_api.py` | 1,617 |
| 6 | `tests/e2e/test_workflow_journeys.py` | 1,341 |
| 7 | `tests/unit/services/test_twr_inspection_source_economics.py` | 1,196 |
| 8 | `tests/unit/docs/test_public_docs_contract.py` | 1,169 |
| 9 | `app/services/lineage_metadata_store.py` | 1,156 |
| 10 | `app/services/compute_job_store.py` | 1,129 |
| 11 | `tests/unit/services/test_compute_executor_worker.py` | 1,124 |
| 12 | `tests/integration/test_returns_series_api.py` | 1,112 |
| 13 | `app/services/stateful_input_service.py` | 1,092 |
| 14 | `tests/integration/test_runtime_status_api.py` | 1,026 |
| 15 | `tests/unit/services/test_stateful_attribution_input_service.py` | 1,024 |

## Tooling Gaps

The following requested quality dimensions are not yet measured by repo-native tooling on this
branch:

| Dimension | Current status |
| --- | --- |
| Cyclomatic complexity and maintainability index | `radon` not installed |
| Dead-code detection | `vulture` not installed |
| Dependency hygiene | `deptry` not installed |
| Python security scanning | `bandit` not installed |
| OpenAPI linting through Spectral | no `.spectral.yaml` found |
| Architecture boundary enforcement | no `.importlinter` contract found |
| Public docstring coverage | `interrogate` not configured |
| Before/after quality scorecard | not yet generated |
| Branch coverage | not yet captured in this baseline slice |
| Router thinness and middleware thinness checks | not yet implemented |
| RFC 7807 error consistency checks | not yet implemented |

## Initial Refactor Hotspots

The measured file-size baseline points to these first review targets:

1. Runtime status and request-path runtime setting tests are very large and should be reviewed for
   shared fixtures, scenario tables, and lower-level service characterization helpers.
2. Integration API suites for performance, contribution, and attribution are large enough to justify
   a contract-test indexing pass before adding more API coverage.
3. `app/services/lineage_metadata_store.py`, `app/services/compute_job_store.py`, and
   `app/services/stateful_input_service.py` are the largest production modules and should remain
   priority candidates for service-boundary and query-shape review.

## Next Report-Only Gates

The next quality-reporting slices should add:

1. `quality/refactor_health_report.md` with before/current placeholders and the same measured
   inventory columns used here.
2. `quality/ci_quality_gates.md` describing progressive report-only, regression-blocking, and
   strict enterprise-readiness phases.
3. Tool configuration for complexity, dead-code, dependency hygiene, security, OpenAPI linting, and
   import-boundary checks in non-blocking mode before any threshold is enforced.

