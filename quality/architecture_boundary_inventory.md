# Lotus Performance Architecture Boundary Inventory

Report date: 2026-06-04
Branch: `feat/performance-hardening-wave-9`
Mode: report-only architecture-boundary inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures the first measured architecture-boundary findings for API router and
engine/core import direction. It is intended to guide bounded refactor slices and prevent the
hardening stream from relying on subjective architecture claims.

## Command

```powershell
python scripts/python_architecture_boundary_inventory.py --limit 40
```

## Summary

| Metric | Value |
| --- | ---: |
| Architecture boundary findings | 5 |
| Distinct rules | 1 |
| Distinct files | 3 |

## Findings By Rule

| Rule | Count |
| --- | ---: |
| `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | 5 |

## Findings By Area

| Area | Count |
| --- | ---: |
| Core | 1 |
| Engine | 4 |

## Findings

| Rank | Rule | File | Import | Description |
| ---: | --- | --- | --- | --- |
| 1 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `core/errors.py:2` | `fastapi` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 2 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution.py:7` | `app.models.attribution_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 3 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution.py:13` | `app.models.attribution_responses` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 4 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution_supportability.py:5` | `app.models.attribution_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 5 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution_supportability.py:6` | `app.models.attribution_responses` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |

## Interpretation

The router boundary findings have been cleared: API modules no longer reach directly into `core` or
`engine` for the measured rules. The remaining engine/core findings identify calculation and domain
modules that still import application DTOs, adapters, or FastAPI primitives.

These findings should be fixed through bounded behavior-preserving slices with characterization
tests. The report is not a blocking gate yet; it is the baseline for progressively reducing
boundary drift.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until current findings are
classified and the first remediation slices prove stable.
