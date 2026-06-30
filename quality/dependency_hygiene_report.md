# Lotus Performance Dependency Hygiene Report

Report date: 2026-06-30
Branch: `batch/defect-backlog-post-pr383`
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
| Total dependency hygiene findings | 0 |
| Distinct issue codes | 0 |
| Distinct modules | 0 |

## Findings By Code

| Code | Count |
| --- | ---: |

## Findings By Module

| Module | Count |
| --- | ---: |

## Findings By Area

| Area | Count |
| --- | ---: |

## Findings

| Rank | Code | Module | Location | Message |
| ---: | --- | --- | --- | --- |

## Interpretation

The earlier `DEP003` findings are closed: production imports of `numpy`, `httpx`, and
`prometheus_client` now have direct runtime declarations. The reviewed runtime-only
`DEP002` declarations are explicitly allowlisted in `scripts/python_dependency_hygiene_inventory.py`:
`uvicorn` is the service process entrypoint, and `psycopg` supports optional PostgreSQL
runtime/benchmark proof.

The obsolete `orjson` runtime declaration was removed when the global null-stripping response
renderer was removed; dependency hygiene remains at zero findings.

Future slices should revisit these allowlisted declarations if the Docker entrypoint, PostgreSQL
runtime posture, or benchmark proof changes.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until dependency declaration
policy and intentional runtime-only dependencies are documented.
