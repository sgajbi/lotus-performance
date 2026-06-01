# Lotus Performance Dependency Hygiene Report

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Mode: report-only dependency hygiene inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures declared-versus-imported dependency hygiene using `deptry` with Lotus
first-party modules configured explicitly. It complements the vulnerability audit by identifying
direct imports that are only transitive today and runtime dependency declarations that are not
imported directly by the production Python paths scanned here.

## Command

```powershell
python scripts/python_dependency_hygiene_inventory.py --limit 30
```

## Summary

| Metric | Value |
| --- | ---: |
| Total dependency hygiene findings | 16 |
| Distinct issue codes | 2 |
| Distinct modules | 7 |

## Findings By Code

| Code | Count |
| --- | ---: |
| DEP002 | 4 |
| DEP003 | 12 |

## Findings By Module

| Module | Count |
| --- | ---: |
| `httpx` | 1 |
| `numpy` | 8 |
| `orjson` | 1 |
| `prometheus_client` | 3 |
| `psycopg` | 1 |
| `scipy` | 1 |
| `uvicorn` | 1 |

## Findings By Area

| Area | Count |
| --- | ---: |
| Application | 1 |
| Dependency declarations | 4 |
| Engine | 8 |
| Services | 3 |

## Findings

| Rank | Code | Module | Location | Message |
| ---: | --- | --- | --- | --- |
| 1 | DEP002 | `orjson` | `pyproject.toml` | 'orjson' defined as a dependency but not used in the codebase |
| 2 | DEP002 | `psycopg` | `pyproject.toml` | 'psycopg' defined as a dependency but not used in the codebase |
| 3 | DEP002 | `scipy` | `pyproject.toml` | 'scipy' defined as a dependency but not used in the codebase |
| 4 | DEP002 | `uvicorn` | `pyproject.toml` | 'uvicorn' defined as a dependency but not used in the codebase |
| 5 | DEP003 | `httpx` | `app/services/http_resilience.py:5` | 'httpx' imported but it is a transitive dependency |
| 6 | DEP003 | `numpy` | `engine/attribution.py:4` | 'numpy' imported but it is a transitive dependency |
| 7 | DEP003 | `numpy` | `engine/compute.py:6` | 'numpy' imported but it is a transitive dependency |
| 8 | DEP003 | `numpy` | `engine/contribution.py:4` | 'numpy' imported but it is a transitive dependency |
| 9 | DEP003 | `numpy` | `engine/contribution_smoothing.py:1` | 'numpy' imported but it is a transitive dependency |
| 10 | DEP003 | `numpy` | `engine/mwr.py:6` | 'numpy' imported but it is a transitive dependency |
| 11 | DEP003 | `numpy` | `engine/policies.py:7` | 'numpy' imported but it is a transitive dependency |
| 12 | DEP003 | `numpy` | `engine/ror.py:5` | 'numpy' imported but it is a transitive dependency |
| 13 | DEP003 | `numpy` | `engine/rules.py:5` | 'numpy' imported but it is a transitive dependency |
| 14 | DEP003 | `prometheus_client` | `app/observability.py:10` | 'prometheus_client' imported but it is a transitive dependency |
| 15 | DEP003 | `prometheus_client` | `app/services/queue_metric_builders.py:6` | 'prometheus_client' imported but it is a transitive dependency |
| 16 | DEP003 | `prometheus_client` | `app/services/queue_metrics_service.py:8` | 'prometheus_client' imported but it is a transitive dependency |

## Interpretation

The `DEP003` findings are actionable dependency-contract drift: production code imports `numpy`,
`httpx`, and `prometheus_client` directly, but those packages are not declared directly in
`pyproject.toml`. The `DEP002` findings need separate review because `uvicorn` can be a runtime
entrypoint dependency, `orjson` may be framework configuration support, `psycopg` can be an optional
database runtime dependency, and `scipy` may be retained for analytics methods not exercised by the
current import scan.

Future slices should first align direct runtime imports with direct dependency declarations, then
review `DEP002` entries against runtime, Docker, migration, and optional analytics behavior before
removing anything.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until dependency declaration
policy and intentional runtime-only dependencies are documented.
