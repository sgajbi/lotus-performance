# Lotus Performance Function Size Inventory

Report date: 2026-06-12
Branch: `refactor/lp-cr-845-benchmark-request-resolution`
Mode: report-only function-size inventory; this artifact introduces no new blocking CI gate.

## Purpose

This report captures the largest production Python functions by source-line span using a
repo-native standard-library script. It gives the refactor health scorecard a measured function-size
hotspot dimension without waiting for external complexity tooling such as `radon` or `xenon`.

## Command

```powershell
python scripts/python_function_size_inventory.py --limit 20
```

## Largest Production Functions

| Rank | Function | File | Lines |
| ---: | --- | --- | ---: |
| 1 | `DurableQueueCollector.describe` | `app/services/queue_metrics_service.py:193` | 159 |
| 2 | `_build_external_cashflow_findings` | `app/services/inspection/source_economics_findings.py:281` | 140 |
| 3 | `build_runtime_status_response` | `app/models/runtime_status.py:767` | 131 |
| 4 | `_build_fee_source_economics_findings` | `app/services/inspection/source_economics_findings.py:423` | 130 |
| 5 | `_build_analytics_surfaces` | `app/services/integration_capabilities_service.py:327` | 130 |
| 6 | `aggregate_attribution_results` | `engine/attribution.py:607` | 126 |
| 7 | `_build_workspace_summary_response` | `app/services/workspace_summary_service.py:502` | 122 |
| 8 | `_build_artifacts` | `app/services/composite_inspection_service.py:114` | 118 |
| 9 | `run_runtime_retention_cleanup` | `app/services/runtime_retention_run_service.py:32` | 111 |
| 10 | `calculate_contribution` | `app/services/contribution_service.py:525` | 107 |
| 11 | `run_source_quality_checks` | `app/services/inspection/source_quality.py:91` | 106 |
| 12 | `calculate_twr_workflow` | `app/services/twr_calculation_service.py:258` | 106 |
| 13 | `calculate_attribution` | `app/services/attribution_service.py:206` | 104 |
| 14 | `_build_flat_period_contribution_result` | `app/services/contribution_service.py:200` | 102 |
| 15 | `_build_hierarchy_period_contribution_result` | `app/services/contribution_service.py:304` | 102 |
| 16 | `build_runtime_retention_history_snapshot` | `app/services/runtime_retention_history_service.py:87` | 101 |
| 17 | `_calculate_position_flow_balance_counts` | `app/services/contribution_diagnostics.py:183` | 99 |
| 18 | `_calculate_returns_series` | `app/services/returns_series_service.py:1308` | 97 |
| 19 | `retrieve_stateful_attribution_source_input` | `app/services/stateful_attribution_input_service.py:62` | 97 |
| 20 | `run_twr_inspection` | `app/services/inspection/twr_inspection_service.py:88` | 95 |

## Interpretation

This is not a cyclomatic-complexity score. It is a deterministic hotspot inventory for refactor
planning. The largest functions are concentrated in source-economics inspection, contribution,
reconciliation, runtime-status assembly, queue metrics, and returns-series execution. TWR workflow
assembly has dropped out of the top-15 table after resolved identity finalization was isolated.
Runtime-status response assembly remains in the top-15 table but moved from `173` to `131` lines
after lineage queue response mapping was isolated. Attribution orchestration remains in the top-15
table but moved from `142` to `133` lines after per-period result assembly was isolated, then moved
from `133` to `120` lines after response meta, supportability, and benchmark-context assembly were
isolated.
Attribution orchestration moved from `120` to `104` lines after execution-window resolution and
master request projection were isolated.
Contribution orchestration moved from `287` to `270` lines after engine input preparation was
isolated, then moved from `270` to `189` lines and is no longer the largest function after
flat-period result assembly was isolated from the public contribution orchestration. Benchmark calculation workflow
dropped out of the top-15 table after resolved benchmark execution context and failure mapping were isolated, and
then stayed out after promoted stateful workflow handling was isolated from the public workflow router.
Workspace summary response assembly moved from `172` to `122` lines after benchmark and active-return
period assembly were isolated.
Attribution result aggregation moved from `148` to `126` lines after active-return/linking policy
and granular effect totals were isolated.
Contribution calculation workflow dropped out of the top-15 table after promoted stateful
execution handling was isolated from the public workflow router.
Contribution orchestration dropped out of the top-15 table again after hierarchy-period result
assembly was isolated from the public contribution calculation function.
Stateful attribution source input retrieval dropped out of the top-15 table after benchmark
assignment resolution was isolated from the source-input orchestration path.
Durable queue metric collection dropped out of the top-15 table after source loading and
availability/runtime-retention preview metric emission were isolated into dedicated helpers.
Source-economics top-level finding assembly dropped from `258` lines out of the top-15 table after
observation-contract, explicit-amount-contract, and detailed cash-flow contract finding groups were
isolated. `_build_detailed_cashflow_contract_findings` dropped out of the top-20 table after the
detailed cash-flow source contract taxonomy was converted to an explicit ordered catalog.
TWR inspection orchestration remains in the top-15 table but moved from `147` to `131` lines after
subject-resolution stage lifecycle handling was isolated from the public inspection orchestrator.
TWR inspection orchestration dropped out of the top-15 table after subject request materialization
and calculation-consistency loading were isolated from the public inspection orchestrator.
Attribution calculation workflow dropped out of the top-20 table after resolved stateful
finalization and initial async submission were isolated from the public workflow orchestrator.
Returns-series calculation orchestration dropped out of the top-15 table after execution-context
resolution was isolated from dataframe preparation, execution, diagnostics, and response assembly.
Stateful returns-series request resolution dropped out of the top-15 table after normalization-stage
Composite inspection artifact assembly moved from `135` to `118` lines after customer-consumable
composite-period return row projection was isolated.
completion, identity payload construction, and resolved stateless request assembly were isolated.

Future refactor slices should use this report to choose bounded work where extraction, shared
helpers, or narrower tests can reduce function size while preserving analytics truth and API
contracts.
