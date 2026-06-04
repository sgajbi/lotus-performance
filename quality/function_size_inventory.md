# Lotus Performance Function Size Inventory

Report date: 2026-06-04
Branch: `feat/performance-hardening-wave-12`
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
| 1 | `build_source_economics_findings` | `app/services/inspection/source_economics_findings.py:7` | 509 |
| 2 | `build_integration_capabilities_report` | `app/services/integration_capabilities_service.py:92` | 354 |
| 3 | `calculate_contribution` | `app/services/contribution_service.py:178` | 335 |
| 4 | `analyze_portfolio_position_reconciliation` | `app/services/inspection/reconciliation.py:82` | 250 |
| 5 | `resolve_stateful_returns_series_request` | `app/services/returns_series_service.py:962` | 226 |
| 6 | `_process_pending_jobs` | `app/workers/compute_executor_worker.py:59` | 219 |
| 7 | `_calculate_returns_series` | `app/services/returns_series_service.py:759` | 201 |
| 8 | `run_twr_inspection` | `app/services/inspection/twr_inspection_service.py:64` | 197 |
| 9 | `DurableQueueCollector.collect` | `app/services/queue_metrics_service.py:227` | 188 |
| 10 | `build_attribution_supportability_evidence` | `engine/attribution_supportability.py:42` | 184 |
| 11 | `build_runtime_status_response` | `app/models/runtime_status.py:660` | 173 |
| 12 | `_build_workspace_summary_response` | `app/services/workspace_summary_service.py:503` | 172 |
| 13 | `resolve_twr_request` | `app/services/twr_mode_service.py:44` | 165 |
| 14 | `DurableQueueCollector.describe` | `app/services/queue_metrics_service.py:67` | 159 |
| 15 | `calculate_twr_response` | `app/services/twr_service.py:612` | 151 |

## Interpretation

This is not a cyclomatic-complexity score. It is a deterministic hotspot inventory for refactor
planning. The largest functions are concentrated in source-economics inspection, contribution,
integration capability reporting, TWR inspection, reconciliation, async worker dispatch,
returns-series resolution, and runtime-status assembly.

Future refactor slices should use this report to choose bounded work where extraction, shared
helpers, or narrower tests can reduce function size while preserving analytics truth and API
contracts.

