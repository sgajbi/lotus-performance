# Lotus Performance Architecture Rules

Report date: 2026-06-02
Branch: `feat/performance-hardening-wave-9`
Mode: report-only architecture-rule definition; no blocking CI gate is introduced by this artifact.

## Purpose

This document defines the first measured architecture boundary rules for the performance hardening
stream. The rules intentionally start as report-only so current violations can be reviewed and
reduced through bounded refactor slices before any regression-blocking gate is introduced.

## Rule Set

| Rule | Boundary | Current posture |
| --- | --- | --- |
| `ROUTER_DIRECT_BOUNDARY_IMPORT` | API routers should route through app services/use cases instead of direct domain, engine, or infrastructure imports. | Measured in `quality/architecture_boundary_inventory.md`; not yet blocking. |
| `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. | Measured in `quality/architecture_boundary_inventory.md`; not yet blocking. |

## Developer Command

```powershell
python scripts/python_architecture_boundary_inventory.py --limit 40
```

## Promotion Standard

Before either rule becomes a blocking gate:

1. every current finding must be classified as actionable, intentionally tolerated, or superseded,
2. tolerated findings need a documented exception reason and owner,
3. at least one bounded refactor slice should prove the remediation path,
4. CI should first block only new findings against a checked-in baseline,
5. strict thresholds should wait until false positives and framework conventions are understood.

## Non-Goals

This rule set does not yet cover import-linter contracts, DTO persistence leakage, dependency
injection shape, middleware thinness, downstream error mapping, or full domain purity. Those should
be added as separate measured rules once the first import-boundary report is stable.
