# Lotus Performance Complexity Inventory

Report date: 2026-06-05
Branch: `feat/performance-hardening-wave-13`
Mode: report-only complexity and maintainability inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures the current cyclomatic complexity and maintainability posture for production
Python paths. It gives the hardening stream repeatable evidence for hotspot selection without
turning the first measurement into a premature merge blocker.

## Command

```powershell
python scripts/python_complexity_inventory.py --limit 20
```

## Summary

| Metric | Value |
| --- | ---: |
| Max cyclomatic complexity | 18 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 55.75 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `_process_pending_jobs` | function | `app/workers/compute_executor_worker.py:73` | 18 | C |
| 2 | `validate_mode_payloads` | method | `app/models/mwr_analytics_requests.py:58` | 17 | C |
| 3 | `validate_mode_payloads` | method | `app/models/twr_requests.py:146` | 17 | C |
| 4 | `_infer_example` | function | `app/openapi_enrichment.py:159` | 17 | C |
| 5 | `_build_hierarchy_from_adjusted_position_series` | function | `app/services/contribution_series.py:146` | 17 | C |
| 6 | `_record_external_samples` | method | `app/services/inspection/source_economics_collector.py:246` | 17 | C |
| 7 | `_fetch_portfolio_chunk` | method | `app/services/stateful_input_service.py:797` | 17 | C |
| 8 | `calculate_twr_workflow` | function | `app/services/twr_calculation_service.py:159` | 17 | C |
| 9 | `validate_mode_payloads` | method | `app/models/benchmark_analytics_requests.py:229` | 16 | C |
| 10 | `build_runtime_status_response` | function | `app/models/runtime_status.py:660` | 16 | C |
| 11 | `_ensure_operation_documentation` | function | `app/openapi_enrichment.py:462` | 16 | C |
| 12 | `calculate_attribution` | function | `app/services/attribution_service.py:69` | 16 | C |
| 13 | `_classification_map_for_request` | function | `app/services/benchmark_exposure_context_service.py:138` | 16 | C |
| 14 | `calculate_contribution` | function | `app/services/contribution_service.py:261` | 16 | C |
| 15 | `_sum_detailed_cash_flows` | function | `app/services/inspection/source_economics.py:424` | 16 | C |
| 16 | `build_operator_action_lease_snapshot` | function | `app/services/operator_action_lease_service.py:171` | 16 | C |
| 17 | `get_portfolio_timeseries` | method | `app/services/stateful_input_service.py:54` | 16 | C |
| 18 | `validate_mode_payloads` | method | `app/models/attribution_analytics_requests.py:147` | 15 | C |
| 19 | `MoneyWeightedReturnAnalyticsRequest` | class | `app/models/mwr_analytics_requests.py:30` | 15 | C |
| 20 | `_compute_queue_response` | function | `app/models/runtime_status.py:613` | 15 | C |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 6.70 | C |
| 7 | `app/services/twr_service.py` | 7.72 | C |
| 8 | `app/services/workspace_summary_service.py` | 9.62 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 12.95 | B |
| 11 | `engine/attribution.py` | 14.54 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.24 | B |
| 13 | `app/services/inspection/reconciliation.py` | 16.40 | B |
| 14 | `app/services/inspection/calculation_consistency.py` | 16.97 | B |
| 15 | `app/models/runtime_status.py` | 17.43 | B |
| 16 | `app/services/inspection/source_economics_collector.py` | 17.45 | B |
| 17 | `app/services/inspection/source_quality.py` | 18.55 | B |
| 18 | `app/workers/compute_executor_worker.py` | 18.74 | B |
| 19 | `app/services/twr_mode_service.py` | 18.80 | B |
| 20 | `app/services/inspection/source_economics.py` | 18.96 | B |

## Interpretation

The D/F high-complexity function inventory is now clear. `_build_benchmark_groups` and
`_parse_composition_window` dropped out of the top-20 table after benchmark grouping aggregation
and composition-window parsing were split into smaller helpers. The remaining highest-complexity
functions are C-grade service and engine hotspots that should be treated as future bounded refactor
candidates, not as evidence of an immediate behavior defect.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the baseline is stable,
false positives are understood, and remediation guidance is documented.
