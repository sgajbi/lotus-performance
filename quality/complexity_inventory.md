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
| Max cyclomatic complexity | 15 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 55.70 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `collect` | method | `app/services/queue_metrics_service.py:227` | 15 | C |
| 2 | `resolve_stateful_returns_series_request` | function | `app/services/returns_series_service.py:1265` | 15 | C |
| 3 | `_position_meta_from_row` | function | `app/services/stateful_attribution_input_service.py:863` | 15 | C |
| 4 | `_build_component_observations` | function | `app/services/stateful_benchmark_input_service.py:474` | 15 | C |
| 5 | `_build_component_observations_from_price_points` | function | `app/services/stateless_benchmark_input_service.py:39` | 15 | C |
| 6 | `resolve_twr_request` | function | `app/services/twr_mode_service.py:60` | 15 | C |
| 7 | `_resolve_twr_benchmark_source_input` | function | `app/services/twr_mode_service.py:353` | 15 | C |
| 8 | `_resolve_workspace_benchmark_input` | function | `app/services/workspace_summary_service.py:314` | 15 | C |
| 9 | `_build_compute_job_runtime` | function | `app/workers/compute_executor_worker.py:156` | 15 | C |
| 10 | `calculate_benchmark_returns` | function | `engine/benchmarks.py:35` | 15 | C |
| 11 | `_lineage_queue_response` | function | `app/models/runtime_status.py:691` | 14 | C |
| 12 | `TWRBenchmarkRequest` | class | `app/models/twr_requests.py:34` | 14 | C |
| 13 | `_parse_reclaimed_event_payload` | function | `app/services/operator_action_lease_service.py:415` | 14 | C |
| 14 | `collect_runtime_degradation_reasons` | function | `app/services/runtime_status_degradation.py:257` | 14 | C |
| 15 | `build_portfolio_source_quality_evidence` | function | `app/services/source_quality_evidence.py:13` | 14 | C |
| 16 | `_collect_stateful_mwr_cash_flows` | function | `app/services/stateful_mwr_input_service.py:184` | 14 | C |
| 17 | `_build_twr_results_by_period` | function | `app/services/twr_service.py:673` | 14 | C |
| 18 | `portfolio_timeseries_to_valuation_points` | function | `app/services/valuation_points_service.py:12` | 14 | C |
| 19 | `build_hierarchical_contribution_result` | function | `engine/contribution.py:298` | 14 | C |
| 20 | `_apply_overrides` | function | `engine/policies.py:38` | 14 | C |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 5.43 | C |
| 7 | `app/services/twr_service.py` | 7.72 | C |
| 8 | `app/services/workspace_summary_service.py` | 9.62 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 12.95 | B |
| 11 | `engine/attribution.py` | 14.54 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.51 | B |
| 13 | `app/services/inspection/reconciliation.py` | 16.40 | B |
| 14 | `app/services/inspection/calculation_consistency.py` | 16.96 | B |
| 15 | `app/services/inspection/source_economics.py` | 17.49 | B |
| 16 | `app/workers/compute_executor_worker.py` | 17.85 | B |
| 17 | `app/services/inspection/source_economics_collector.py` | 18.02 | B |
| 18 | `app/services/inspection/source_quality.py` | 18.55 | B |
| 19 | `app/models/runtime_status.py` | 18.75 | B |
| 20 | `app/services/twr_mode_service.py` | 18.80 | B |

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
return-source normalization were separated. `BenchmarkAnalyticsRequest.validate_mode_payloads` also
dropped out after analysis selection, stateless calculated, stateless vendor-series, and stateful
payload validation were separated. `build_runtime_status_response` also dropped out after lineage
queue stats, storage, anchors, and recovery-event mapping were separated from the aggregate runtime
response builder. `_ensure_operation_documentation` also dropped out after summary, description,
metrics description, and tag inference were separated into operation metadata helpers.
`calculate_attribution` also dropped out after per-period slicing, aggregation, lineage prefixing,
and response conversion were separated into a dedicated results-by-period helper.
`_classification_map_for_request` also dropped out after index-catalog requirement detection,
index-id extraction, and catalog-record normalization were separated into helpers.
`calculate_contribution` also dropped out after period resolution, master-window derivation,
hierarchical engine input preparation, daily contribution calculation, and date normalization were
separated into a preparation helper. `_sum_detailed_cash_flows` also dropped out after detailed
cash-flow row quality tracking, taxonomy samples, and fee/external amount accumulation were routed
through a dedicated accumulator. `build_operator_action_lease_snapshot` also dropped out after
active lock scanning and available/unavailable snapshot construction were separated into helpers.
`get_portfolio_timeseries` also dropped out after successful portfolio timeseries response assembly
was separated from chunk planning, parallel fetch, and failure handling.
`AttributionAnalyticsRequest.validate_mode_payloads` also dropped out after legacy input-shape
detection and stateless/stateful exclusivity checks were separated into helpers.
`_compute_queue_response` also dropped out after compute queue stats, inspection anchors, and
recovery-event response projection were separated into helpers.
`_ensure_operation_response_documentation` also dropped out after error-response detection, metrics
response content, JSON success examples, and success-response enrichment were separated into
smaller helpers. `calculate_benchmark_workflow` also dropped out after resolved benchmark execution
context construction and workflow failure mapping were separated from fencing and offload decisions.
`_check_portfolio_daily_calculation_evidence` also dropped out after expected daily calculation
values and daily evidence mismatch assembly were separated from portfolio breakdown traversal.
`_record_taxonomy_samples` also dropped out after repeated dated sample append branches were routed
through reusable taxonomy sampling helpers. Max
cyclomatic complexity is now `15`. The remaining
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
