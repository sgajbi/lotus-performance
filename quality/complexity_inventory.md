# Lotus Performance Complexity Inventory

Report date: 2026-06-05
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
| Max cyclomatic complexity | 20 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 55.81 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `_validate_stateful_portfolio_position_alignment` | function | `app/services/stateful_attribution_input_service.py:283` | 20 | C |
| 2 | `resolve_twr_request` | function | `app/services/twr_mode_service.py:52` | 20 | C |
| 3 | `calculate_twr_response` | function | `app/services/twr_service.py:738` | 20 | C |
| 4 | `build_attribution_supportability_evidence` | function | `engine/attribution_supportability.py:42` | 20 | C |
| 5 | `calculate_daily_ror` | function | `engine/ror.py:18` | 20 | C |
| 6 | `_ensure_schema_documentation` | function | `app/openapi_enrichment.py:510` | 19 | C |
| 7 | `_expected_daily_evidence_semantics` | function | `app/services/inspection/calculation_consistency.py:416` | 19 | C |
| 8 | `analyze_portfolio_position_reconciliation` | function | `app/services/inspection/reconciliation.py:89` | 19 | C |
| 9 | `_calculate_returns_series` | function | `app/services/returns_series_service.py:1026` | 19 | C |
| 10 | `_prepare_hierarchical_data` | function | `engine/contribution.py:152` | 19 | C |
| 11 | `_xirr` | function | `engine/mwr.py:53` | 19 | C |
| 12 | `validate_mode_payloads` | method | `app/models/workspace_summary_requests.py:251` | 18 | C |
| 13 | `append_diagnostic_notes` | method | `app/services/contribution_audit.py:88` | 18 | C |
| 14 | `calculate_contribution` | function | `app/services/contribution_service.py:178` | 18 | C |
| 15 | `build_source_economics_findings` | function | `app/services/inspection/source_economics_findings.py:7` | 18 | C |
| 16 | `_runtime_retention_payload_matches_entry` | function | `app/services/operator_action_replay_service.py:136` | 18 | C |
| 17 | `resolve_stateful_returns_series_request` | function | `app/services/returns_series_service.py:1186` | 18 | C |
| 18 | `_build_benchmark_groups` | function | `app/services/stateful_attribution_input_service.py:588` | 18 | C |
| 19 | `_parse_composition_window` | function | `app/services/stateful_benchmark_input_service.py:209` | 18 | C |
| 20 | `_process_pending_jobs` | function | `app/workers/compute_executor_worker.py:73` | 18 | C |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 6.77 | C |
| 7 | `app/services/twr_service.py` | 8.18 | C |
| 8 | `app/services/workspace_summary_service.py` | 9.62 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 13.69 | B |
| 11 | `engine/attribution.py` | 14.54 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.24 | B |
| 13 | `app/services/inspection/reconciliation.py` | 16.78 | B |
| 14 | `app/models/runtime_status.py` | 17.43 | B |
| 15 | `app/services/inspection/source_economics_collector.py` | 17.45 | B |
| 16 | `app/services/inspection/calculation_consistency.py` | 17.56 | B |
| 17 | `app/services/inspection/source_quality.py` | 18.55 | B |
| 18 | `app/workers/compute_executor_worker.py` | 18.74 | B |
| 19 | `app/services/inspection/source_economics.py` | 18.96 | B |
| 20 | `app/services/twr_mode_service.py` | 19.71 | A |

## Interpretation

The D/F high-complexity function inventory is now clear. The remaining highest-complexity functions
are C-grade service and engine hotspots that should be treated as future bounded refactor candidates,
not as evidence of an immediate behavior defect.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the baseline is stable,
false positives are understood, and remediation guidance is documented.
