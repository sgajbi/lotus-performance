# Lotus Performance Architecture Boundary Inventory

Report date: 2026-07-10
Branch: `feat/performance-architecture-boundary-refactor`
Mode: mixed architecture-boundary inventory; zero enforced router/core and route-workflow
command-boundary findings are blocked by CI, while application-service concrete-store imports are
measured report-only.

## Purpose

This report captures the measured architecture-boundary findings for API router import direction,
engine/core import direction, API route-to-workflow command mapping, and the next-layer
application-service port seam. It is intended to guide bounded refactor slices and prevent the
hardening stream from relying on subjective architecture claims.

## Command

```powershell
python scripts/python_architecture_boundary_inventory.py --limit 80 --max-findings 0
```

## Summary

| Metric | Value |
| --- | ---: |
| Architecture boundary findings | 63 |
| Enforced findings | 0 |
| Report-only findings | 63 |
| Distinct rules | 1 |
| Distinct files | 44 |

## Findings By Rule

| Rule | Count |
| --- | ---: |
| `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | 63 |

## Findings By Area

| Area | Count |
| --- | ---: |
| Application services | 63 |

## Findings

| Rank | Rule | Posture | File | Import | Description |
| ---: | --- | --- | --- | --- | --- |
| 1 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/async_result_service.py:11` | `app.services.async_result_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 2 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/async_result_service.py:13` | `app.services.compute_job_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 3 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/async_result_service.py:14` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 4 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/attribution_mode_service.py:13` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 5 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/attribution_service.py:23` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 6 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/benchmark_calculation_workflow_service.py:17` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 7 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/benchmark_exposure_context_workflow_service.py:8` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 8 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/benchmark_mode_service.py:13` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 9 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/benchmark_service.py:9` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 10 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/calculation_result_access.py:17` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 11 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/composite_calculation_service.py:5` | `app.services.composite_metadata_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 12 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/composite_inspection_service.py:15` | `app.services.composite_metadata_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 13 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/contribution_evidence.py:10` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 14 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/contribution_mode_service.py:12` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 15 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/contribution_service.py:68` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 16 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/contribution_source_economics.py:10` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 17 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/durability_health_service.py:12` | `app.services.execution_registry` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 18 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/durable_metadata_bootstrap.py:3` | `app.services.async_result_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 19 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/durable_metadata_bootstrap.py:4` | `app.services.composite_metadata_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |
| 20 | `APPLICATION_SERVICE_CONCRETE_STORE_IMPORT` | report-only | `app/services/durable_metadata_bootstrap.py:5` | `app.services.compute_job_store` | Application services should depend on ports/interfaces instead of concrete durable store modules. |

## Interpretation

The measured router, engine, core, and route-workflow boundary findings remain clear for the
enforced scanner rules: API modules do not reach directly into disallowed lower layers, engine/core
modules do not import application DTOs, adapters, or FastAPI primitives for the measured rules, and
TWR, workspace-summary, contribution, benchmark, and returns-series routes no longer pass raw
request DTOs directly into workflow services.

The new application-service rule found `63` report-only concrete durable-store imports across `44`
files. The execution polling workflow is the pilot seam: its route now receives an
`ExecutionPollingStore` through an API dependency, the application service depends on the port, and
the durable store access lives in `app.adapters.execution_polling_store`.

Future boundary drift should be handled through bounded behavior-preserving slices with
characterization tests. The current zero-finding posture is now a blocking architecture boundary
gate in local checks, Feature Lane, PR Merge Gate, and Main Releasability.

## Gate Posture

`make quality-architecture-gate` enforces `--max-findings 0` for enforced router, engine/core, and
route-workflow command-boundary rules. The application-service port-boundary rule is report-only
until the remaining concrete-store imports are reduced and an exception policy is agreed.
