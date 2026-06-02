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
| Total dependency hygiene findings | 4 |
| Distinct issue codes | 1 |
| Distinct modules | 4 |

## Findings By Code

| Code | Count |
| --- | ---: |
| DEP002 | 4 |

## Findings By Module

| Module | Count |
| --- | ---: |
| `orjson` | 1 |
| `psycopg` | 1 |
| `scipy` | 1 |
| `uvicorn` | 1 |

## Findings By Area

| Area | Count |
| --- | ---: |
| Dependency declarations | 4 |

## Findings

| Rank | Code | Module | Location | Message |
| ---: | --- | --- | --- | --- |
| 1 | DEP002 | `orjson` | `pyproject.toml` | 'orjson' defined as a dependency but not used in the codebase |
| 2 | DEP002 | `psycopg` | `pyproject.toml` | 'psycopg' defined as a dependency but not used in the codebase |
| 3 | DEP002 | `scipy` | `pyproject.toml` | 'scipy' defined as a dependency but not used in the codebase |
| 4 | DEP002 | `uvicorn` | `pyproject.toml` | 'uvicorn' defined as a dependency but not used in the codebase |

## Interpretation

The earlier `DEP003` findings are closed: production imports of `numpy`, `httpx`, and
`prometheus_client` now have direct runtime declarations. The remaining `DEP002` findings need
separate review because `uvicorn` can be a runtime entrypoint dependency, `orjson` may be framework
configuration support, `psycopg` can be an optional database runtime dependency, and `scipy` may be
retained for analytics methods not exercised by the current import scan.

Future slices should review `DEP002` entries against runtime, Docker, migration, and optional
analytics behavior before removing anything.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until dependency declaration
policy and intentional runtime-only dependencies are documented.
