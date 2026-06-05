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
| Max cyclomatic complexity | 16 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 55.72 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `validate_mode_payloads` | method | `app/models/benchmark_analytics_requests.py:229` | 16 | C |
| 2 | `build_runtime_status_response` | function | `app/models/runtime_status.py:660` | 16 | C |
| 3 | `_ensure_operation_documentation` | function | `app/openapi_enrichment.py:493` | 16 | C |
| 4 | `calculate_attribution` | function | `app/services/attribution_service.py:69` | 16 | C |
| 5 | `_classification_map_for_request` | function | `app/services/benchmark_exposure_context_service.py:138` | 16 | C |
| 6 | `calculate_contribution` | function | `app/services/contribution_service.py:261` | 16 | C |
| 7 | `_sum_detailed_cash_flows` | function | `app/services/inspection/source_economics.py:424` | 16 | C |
| 8 | `build_operator_action_lease_snapshot` | function | `app/services/operator_action_lease_service.py:171` | 16 | C |
| 9 | `get_portfolio_timeseries` | method | `app/services/stateful_input_service.py:54` | 16 | C |
| 10 | `validate_mode_payloads` | method | `app/models/attribution_analytics_requests.py:147` | 15 | C |
| 11 | `_compute_queue_response` | function | `app/models/runtime_status.py:613` | 15 | C |
| 12 | `_ensure_operation_response_documentation` | function | `app/openapi_enrichment.py:446` | 15 | C |
| 13 | `calculate_benchmark_workflow` | function | `app/services/benchmark_calculation_workflow_service.py:89` | 15 | C |
| 14 | `_check_portfolio_daily_calculation_evidence` | function | `app/services/inspection/calculation_consistency.py:302` | 15 | C |
| 15 | `_record_taxonomy_samples` | method | `app/services/inspection/source_economics_collector.py:111` | 15 | C |
| 16 | `collect` | method | `app/services/queue_metrics_service.py:227` | 15 | C |
| 17 | `resolve_stateful_returns_series_request` | function | `app/services/returns_series_service.py:1265` | 15 | C |
| 18 | `_position_meta_from_row` | function | `app/services/stateful_attribution_input_service.py:863` | 15 | C |
| 19 | `_build_component_observations` | function | `app/services/stateful_benchmark_input_service.py:474` | 15 | C |
| 20 | `_build_component_observations_from_price_points` | function | `app/services/stateless_benchmark_input_service.py:39` | 15 | C |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 5.59 | C |
| 7 | `app/services/twr_service.py` | 7.72 | C |
| 8 | `app/services/workspace_summary_service.py` | 9.62 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 12.95 | B |
| 11 | `engine/attribution.py` | 14.54 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.24 | B |
| 13 | `app/services/inspection/reconciliation.py` | 16.40 | B |
| 14 | `app/services/inspection/source_economics_collector.py` | 16.66 | B |
| 15 | `app/services/inspection/calculation_consistency.py` | 16.97 | B |
| 16 | `app/models/runtime_status.py` | 17.43 | B |
| 17 | `app/workers/compute_executor_worker.py` | 17.85 | B |
| 18 | `app/services/inspection/source_quality.py` | 18.55 | B |
| 19 | `app/services/twr_mode_service.py` | 18.80 | B |
| 20 | `app/services/inspection/source_economics.py` | 18.96 | B |

## Interpretation

The D/F high-complexity function inventory is now clear. `_build_benchmark_groups`,
`_parse_composition_window`, `_process_pending_jobs`, and
`MoneyWeightedReturnAnalyticsRequest.validate_mode_payloads` dropped out of the top-20 table after
benchmark grouping aggregation, composition-window parsing, compute-worker runtime setup, and MWR
request validation were split into smaller helpers. `TWRAnalyticsRequest.validate_mode_payloads`
also dropped out after TWR request validation and benchmark inclusion rules were split into smaller
helpers. `_infer_example` also dropped out after OpenAPI example inference was split into enum,
typed-schema, formatted-schema, and semantic fallback helpers. `_build_hierarchy_from_adjusted_position_series`
also dropped out after hierarchy summary, adjusted-record, metadata, unclassified-policy, and response-level
assembly were split into smaller helpers. `_record_external_samples` also dropped out after external-flow
normalization, source-signal, timing-contradiction, and mixed-timing sampling were separated.
`_fetch_portfolio_chunk` also dropped out after request-payload construction, snapshot append/de-dupe,
identity extraction, and observation filtering were separated. `calculate_twr_workflow` also dropped
out after resolved identity selection, hash replacement, stateful finalization, and benchmark
return-source normalization were separated. Max cyclomatic complexity is now `16`. The remaining
highest-complexity functions are C-grade service and engine hotspots that should be treated as
future bounded refactor candidates, not as evidence of an immediate behavior defect.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the baseline is stable,
false positives are understood, and remediation guidance is documented.
