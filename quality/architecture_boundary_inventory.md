# Lotus Performance Architecture Boundary Inventory

Report date: 2026-06-02
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
| Architecture boundary findings | 15 |
| Distinct rules | 2 |
| Distinct files | 11 |

## Findings By Rule

| Rule | Count |
| --- | ---: |
| `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | 14 |
| `ROUTER_DIRECT_BOUNDARY_IMPORT` | 1 |

## Findings By Area

| Area | Count |
| --- | ---: |
| API routers | 1 |
| Core | 1 |
| Engine | 13 |

## Findings

| Rank | Rule | File | Import | Description |
| ---: | --- | --- | --- | --- |
| 1 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `core/errors.py:2` | `fastapi` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 2 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution.py:7` | `adapters.api_adapter` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 3 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution.py:8` | `app.models.attribution_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 4 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution.py:14` | `app.models.attribution_responses` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 5 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution_supportability.py:5` | `app.models.attribution_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 6 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/attribution_supportability.py:6` | `app.models.attribution_responses` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 7 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/benchmarks.py:9` | `app.models.benchmark_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 8 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/breakdown.py:6` | `app.precision_policy` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 9 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/composites.py:8` | `app.models.composites` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 10 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/contribution.py:7` | `app.models.contribution_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 11 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/contribution_smoothing.py:4` | `app.models.contribution_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 12 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/mwr.py:8` | `app.models.mwr_requests` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 13 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/mwr.py:9` | `app.models.mwr_responses` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 14 | `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | `engine/runtime.py:8` | `adapters.api_adapter` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. |
| 15 | `ROUTER_DIRECT_BOUNDARY_IMPORT` | `app/api/endpoints/performance.py:48` | `engine.exceptions` | API routers should route through app services/use cases instead of direct domain, engine, or infrastructure imports. |

## Interpretation

The router findings identify API modules that still reach directly into `core` or `engine` instead
of routing entirely through app services/use cases. The engine/core findings identify calculation
and domain modules that still import application DTOs, adapters, or FastAPI primitives.

These findings should be fixed through bounded behavior-preserving slices with characterization
tests. The report is not a blocking gate yet; it is the baseline for progressively reducing
boundary drift.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until current findings are
classified and the first remediation slices prove stable.
