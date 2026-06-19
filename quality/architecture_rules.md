# Lotus Performance Architecture Rules

Report date: 2026-06-02
Branch: `lp-cr-1388-source-economics-raw-sampling`
Mode: enforced architecture-rule definition; zero current findings are now blocked by CI.

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

## Developer Command

```powershell
python scripts/python_architecture_boundary_inventory.py --limit 40 --max-findings 0
```

## Gate Standard

The current strict threshold is zero findings. If a future framework integration requires an
exception, it must be documented in this rule file and backed by focused tests before the gate is
relaxed.

## Non-Goals

This rule set does not yet cover import-linter contracts, DTO persistence leakage, dependency
injection shape, middleware thinness, downstream error mapping, or full domain purity. Those should
be added as separate measured rules once the first import-boundary report is stable.
