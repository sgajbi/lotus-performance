# Lotus Performance Function Size Inventory

Report date: 2026-06-05
Branch: `feat/performance-hardening-wave-14`
Mode: report-only function-size inventory; this artifact introduces no new blocking CI gate.

## Purpose

This report captures the largest production Python functions by source-line span using a
repo-native standard-library script. It gives the refactor health scorecard a measured function-size
hotspot dimension without waiting for external complexity tooling such as `radon` or `xenon`.

## Command

```powershell
python scripts/python_function_size_inventory.py --limit 15
```

## Largest Production Functions

| Rank | Function | File | Lines |
| ---: | --- | --- | ---: |
| 1 | `calculate_contribution` | `app/services/contribution_service.py:421` | 189 |
| 2 | `_build_detailed_cashflow_contract_findings` | `app/services/inspection/source_economics_findings.py:112` | 186 |
| 3 | `_build_workspace_summary_response` | `app/services/workspace_summary_service.py:503` | 172 |
| 4 | `DurableQueueCollector.describe` | `app/services/queue_metrics_service.py:193` | 159 |
| 5 | `aggregate_attribution_results` | `engine/attribution.py:586` | 148 |
| 6 | `_build_external_cashflow_findings` | `app/services/inspection/source_economics_findings.py:300` | 140 |
| 7 | `_build_artifacts` | `app/services/composite_inspection_service.py:114` | 135 |
| 8 | `build_runtime_status_response` | `app/models/runtime_status.py:737` | 131 |
| 9 | `run_twr_inspection` | `app/services/inspection/twr_inspection_service.py:71` | 131 |
| 10 | `_build_fee_source_economics_findings` | `app/services/inspection/source_economics_findings.py:442` | 130 |
| 11 | `_build_analytics_surfaces` | `app/services/integration_capabilities_service.py:327` | 130 |
| 12 | `calculate_contribution_workflow` | `app/services/contribution_calculation_workflow_service.py:98` | 127 |
| 13 | `calculate_attribution` | `app/services/attribution_service.py:168` | 120 |
| 14 | `resolve_twr_request` | `app/services/twr_mode_service.py:60` | 120 |
| 15 | `_resolve_workspace_benchmark_input` | `app/services/workspace_summary_service.py:314` | 118 |

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
Contribution orchestration moved from `287` to `270` lines after engine input preparation was
isolated, then moved from `270` to `189` lines and is no longer the largest function after
flat-period result assembly was isolated from the public contribution orchestration. Benchmark calculation workflow
dropped out of the top-15 table after resolved benchmark execution context and failure mapping were isolated.
Durable queue metric collection dropped out of the top-15 table after source loading and
availability/runtime-retention preview metric emission were isolated into dedicated helpers.
Source-economics top-level finding assembly dropped from `258` lines out of the top-15 table after
observation-contract, explicit-amount-contract, and detailed cash-flow contract finding groups were
isolated. `_build_detailed_cashflow_contract_findings` remains a large follow-up hotspot at `186`
lines because this slice preserved finding text and ordering rather than converting the source
contract taxonomy to a data-driven table.
TWR inspection orchestration remains in the top-15 table but moved from `147` to `131` lines after
subject-resolution stage lifecycle handling was isolated from the public inspection orchestrator.
Returns-series calculation orchestration dropped out of the top-15 table after execution-context
resolution was isolated from dataframe preparation, execution, diagnostics, and response assembly.
Stateful returns-series request resolution dropped out of the top-15 table after normalization-stage
completion, identity payload construction, and resolved stateless request assembly were isolated.

Future refactor slices should use this report to choose bounded work where extraction, shared
helpers, or narrower tests can reduce function size while preserving analytics truth and API
contracts.
