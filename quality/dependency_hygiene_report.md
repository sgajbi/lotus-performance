# Lotus Performance Dependency Hygiene Report

Report date: 2026-10-09
Branch: `feature/composite-result-authority-610`
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
| Total dependency hygiene findings | 21 |
| Distinct issue codes | 1 |
| Distinct modules | 21 |

## Findings By Code

| Code | Count |
| --- | ---: |
| DEP002: no direct production import | 21 |

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

The current inventory reports 21 `DEP002` findings for exact runtime declarations without
direct production imports: `annotated-types`, `anyio`, `certifi`, `cffi`, `click`, `colorama`,
`h11`, `httpcore`, `idna`, `korean-lunar-calendar`, `packaging`, `pycparser`, `pyluach`,
`python-dateutil`, `python-dotenv`, `pytz`, `six`, `sniffio`, `toolz`, `typing-inspection`
and `tzdata`. These are dependency declaration findings, not vulnerability findings.

The result-candidate increment adds `cryptography`, which is directly imported for Ed25519
verification, and its exact pinned transitives `cffi` and `pycparser`. The latter two account
for two findings. The other 19 declarations predate this increment; all 95 prior locked
package records remain unchanged. Removing declared transitives requires a separate reviewed
manifest policy change, rather than deleting runtime dependencies because the application
does not import them directly. No dependency-hygiene allowlist or gate threshold changed.

The owning complete dependency audit reports zero known vulnerabilities, and the license
inventory accepts the three added packages under the existing license policy. Those checks
are separate from this report-only inventory; zero vulnerabilities does not mean zero hygiene
findings. The raw generated inventory is reproduced by the command above.

Future slices should revisit these allowlisted declarations if the Docker entrypoint, PostgreSQL
runtime posture, or benchmark proof changes.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until dependency declaration
policy and intentional runtime-only dependencies are documented.
