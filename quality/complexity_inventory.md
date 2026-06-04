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
python scripts/python_complexity_inventory.py --limit 20
```

## Summary

| Metric | Value |
| --- | ---: |
| Max cyclomatic complexity | 27 |
| High-complexity functions (rank D-F) | 15 |
| Average maintainability index | 55.86 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `calculate_asset_weighted_composite_twr` | function | `engine/composites.py:240` | 27 | D |
| 2 | `_build_schema_example` | function | `app/openapi_enrichment.py:230` | 26 | D |
| 3 | `_prepare_data_from_instruments` | function | `engine/attribution.py:221` | 26 | D |
| 4 | `_calculate_returns_series` | function | `app/services/returns_series_service.py:809` | 25 | D |
| 5 | `resolve_twr_request` | function | `app/services/twr_mode_service.py:44` | 25 | D |
| 6 | `calculate_money_weighted_return` | function | `engine/mwr.py:186` | 25 | D |
| 7 | `build_source_economics_findings` | function | `app/services/inspection/source_economics_findings.py:7` | 24 | D |
| 8 | `resolve_stateful_returns_series_request` | function | `app/services/returns_series_service.py:1012` | 24 | D |
| 9 | `ReturnsSeriesRequest` | class | `app/models/returns_series.py:244` | 22 | D |
| 10 | `analyze_portfolio_position_reconciliation` | function | `app/services/inspection/reconciliation.py:82` | 22 | D |
| 11 | `calculate_benchmark_returns` | function | `engine/benchmarks.py:35` | 22 | D |
| 12 | `validate_selection` | method | `app/models/returns_series.py:318` | 21 | D |
| 13 | `run_twr_inspection` | function | `app/services/inspection/twr_inspection_service.py:64` | 21 | D |
| 14 | `build_integration_capabilities_report` | function | `app/services/integration_capabilities_service.py:92` | 21 | D |
| 15 | `build_stateful_mwr_input_for_window` | function | `app/services/stateful_mwr_input_service.py:100` | 21 | D |
| 16 | `_validate_stateful_portfolio_position_alignment` | function | `app/services/stateful_attribution_input_service.py:283` | 20 | C |
| 17 | `calculate_twr_response` | function | `app/services/twr_service.py:738` | 20 | C |
| 18 | `build_attribution_supportability_evidence` | function | `engine/attribution_supportability.py:42` | 20 | C |
| 19 | `calculate_daily_ror` | function | `engine/ror.py:18` | 20 | C |
| 20 | `_ensure_schema_documentation` | function | `app/openapi_enrichment.py:458` | 19 | C |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 6.89 | C |
| 7 | `app/services/twr_service.py` | 8.18 | C |
| 8 | `app/services/workspace_summary_service.py` | 9.62 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 13.69 | B |
| 11 | `engine/attribution.py` | 15.13 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.24 | B |
| 13 | `app/services/inspection/reconciliation.py` | 17.36 | B |
| 14 | `app/models/runtime_status.py` | 17.43 | B |
| 15 | `app/services/inspection/source_economics_collector.py` | 17.45 | B |
| 16 | `app/services/inspection/calculation_consistency.py` | 17.56 | B |
| 17 | `app/services/inspection/source_quality.py` | 18.55 | B |
| 18 | `app/workers/compute_executor_worker.py` | 18.74 | B |
| 19 | `app/services/inspection/source_economics.py` | 18.96 | B |
| 20 | `app/models/returns_series.py` | 20.02 | A |

## Interpretation

The highest complexity functions are concentrated in composite TWR, OpenAPI schema-example
generation, attribution instrument preparation, returns-series resolution and calculation, TWR mode
resolution, MWR calculation, source-economics inspection, benchmark returns, integration capability
reporting, and stateful input assembly. These are real refactor-planning hotspots, not evidence
that a single local extraction should change behavior.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the baseline is stable,
false positives are understood, and remediation guidance is documented.
