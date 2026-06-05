# Lotus Performance Function Size Inventory

Report date: 2026-06-05
Branch: `feat/performance-hardening-wave-13`
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
| 1 | `build_source_economics_findings` | `app/services/inspection/source_economics_findings.py:7` | 389 |
| 2 | `calculate_contribution` | `app/services/contribution_service.py:178` | 335 |
| 3 | `DurableQueueCollector.collect` | `app/services/queue_metrics_service.py:227` | 188 |
| 4 | `build_runtime_status_response` | `app/models/runtime_status.py:660` | 173 |
| 5 | `_build_workspace_summary_response` | `app/services/workspace_summary_service.py:503` | 172 |
| 6 | `DurableQueueCollector.describe` | `app/services/queue_metrics_service.py:67` | 159 |
| 7 | `_calculate_returns_series` | `app/services/returns_series_service.py:1026` | 158 |
| 8 | `calculate_twr_workflow` | `app/services/twr_calculation_service.py:159` | 148 |
| 9 | `aggregate_attribution_results` | `engine/attribution.py:586` | 148 |
| 10 | `calculate_benchmark_workflow` | `app/services/benchmark_calculation_workflow_service.py:89` | 147 |
| 11 | `run_twr_inspection` | `app/services/inspection/twr_inspection_service.py:71` | 147 |
| 12 | `resolve_stateful_returns_series_request` | `app/services/returns_series_service.py:1186` | 143 |
| 13 | `calculate_attribution` | `app/services/attribution_service.py:69` | 142 |
| 14 | `_build_artifacts` | `app/services/composite_inspection_service.py:114` | 135 |
| 15 | `_build_fee_source_economics_findings` | `app/services/inspection/source_economics_findings.py:398` | 130 |

## Interpretation

This is not a cyclomatic-complexity score. It is a deterministic hotspot inventory for refactor
planning. The largest functions are concentrated in source-economics inspection, contribution,
reconciliation, runtime-status assembly, queue metrics, returns-series execution, and TWR workflow
assembly.

Future refactor slices should use this report to choose bounded work where extraction, shared
helpers, or narrower tests can reduce function size while preserving analytics truth and API
contracts.
