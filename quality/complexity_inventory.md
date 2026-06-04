# Lotus Performance Complexity Inventory

Report date: 2026-06-04
Branch: `feat/performance-hardening-wave-12`
Mode: report-only complexity and maintainability inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures the current cyclomatic complexity and maintainability posture for production
Python paths. It gives the hardening stream repeatable evidence for hotspot selection without
turning the first measurement into a premature merge blocker.

## Command

```powershell
python scripts/python_complexity_inventory.py --limit 15
```

## Summary

| Metric | Value |
| --- | ---: |
| Max cyclomatic complexity | 31 |
| High-complexity functions (rank D-F) | 20 |
| Average maintainability index | 55.87 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `run_twr_inspection` | function | `app/services/inspection/twr_inspection_service.py:54` | 31 | E |
| 2 | `build_runtime_status_response` | function | `app/models/runtime_status.py:613` | 30 | D |
| 3 | `_ensure_operation_documentation` | function | `app/openapi_enrichment.py:363` | 30 | D |
| 4 | `_process_pending_jobs` | function | `app/workers/compute_executor_worker.py:59` | 30 | D |
| 5 | `calculate_contribution` | function | `app/services/contribution_service.py:126` | 29 | D |
| 6 | `_prepare_data_from_instruments` | function | `engine/attribution.py:210` | 28 | D |
| 7 | `_calculate_returns_series` | function | `app/services/returns_series_service.py:723` | 27 | D |
| 8 | `resolve_stateful_returns_series_request` | function | `app/services/returns_series_service.py:935` | 27 | D |
| 9 | `_build_daily_calculation_evidence` | function | `app/services/twr_service.py:166` | 27 | D |
| 10 | `calculate_asset_weighted_composite_twr` | function | `engine/composites.py:240` | 27 | D |
| 11 | `_build_schema_example` | function | `app/openapi_enrichment.py:230` | 26 | D |
| 12 | `resolve_twr_request` | function | `app/services/twr_mode_service.py:44` | 25 | D |
| 13 | `calculate_money_weighted_return` | function | `engine/mwr.py:186` | 25 | D |
| 14 | `build_source_economics_findings` | function | `app/services/inspection/source_economics_findings.py:7` | 24 | D |
| 15 | `ReturnsSeriesRequest` | class | `app/models/returns_series.py:244` | 22 | D |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 6.97 | C |
| 7 | `app/services/twr_service.py` | 8.29 | C |
| 8 | `app/services/workspace_summary_service.py` | 9.62 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 13.69 | B |
| 11 | `engine/attribution.py` | 15.19 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.24 | B |
| 13 | `app/services/inspection/reconciliation.py` | 17.36 | B |
| 14 | `app/services/inspection/source_economics_collector.py` | 17.45 | B |
| 15 | `app/models/runtime_status.py` | 17.53 | B |

## Interpretation

The highest complexity functions are concentrated in TWR inspection, runtime status, OpenAPI
enrichment, worker dispatch, contribution, returns-series resolution and calculation, composite
TWR, attribution, and MWR calculation. These are real refactor-planning hotspots, not evidence that
a single local extraction should change behavior.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the baseline is stable,
false positives are understood, and remediation guidance is documented.
