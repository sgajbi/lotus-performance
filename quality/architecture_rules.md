# Lotus Performance Architecture Rules

Report date: 2026-07-10
Branch: `feat/performance-architecture-boundary-refactor`
Mode: mixed architecture-rule definition; router/core rules are enforced, application-service
port-boundary findings are report-only until the migration baseline is burned down.

## Purpose

This document defines the first measured architecture boundary rules for the performance hardening
stream. The current import-boundary rules are promoted from report-only measurement to blocking
regression gates after the inventory reached zero findings and the scanner gained an explicit
`--max-findings` threshold.

## Rule Set

| Rule | Boundary | Current posture |
| --- | --- | --- |
| `ROUTER_DIRECT_BOUNDARY_IMPORT` | API routers should route through app services/use cases instead of direct domain, engine, or infrastructure imports. | Enforced by `make quality-architecture-gate` with `--max-findings 0`. |
| `DOMAIN_INFRA_OR_FRAMEWORK_IMPORT` | Engine/core modules should stay independent from application DTOs, adapters, and web framework imports. | Enforced by `make quality-architecture-gate` with `--max-findings 0`. |
| `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | Application services should depend on ports/interfaces instead of concrete durable store modules. | Report-only. Current baseline is `63` findings after the execution-polling pilot seam moved behind `ExecutionPollingStore`. |

## Developer Command

```powershell
python scripts/python_architecture_boundary_inventory.py --limit 80 --max-findings 0
```

## Gate Standard

The current strict threshold is zero enforced findings. Report-only application-service
port-boundary findings are intentionally visible in the same inventory, but they do not count
against `--max-findings` until the baseline, exception policy, and migration plan are stable.
If a future framework integration requires an enforced exception, it must be documented in this
rule file and backed by focused tests before the gate is relaxed.

## Non-Goals

This rule set does not yet cover import-linter contracts, DTO persistence leakage, dependency
injection shape, middleware thinness, downstream error mapping, or full domain purity. Request DTO
mapper/use-case command leakage remains a separate issue-driven architecture slice.
