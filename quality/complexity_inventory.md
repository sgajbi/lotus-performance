# Lotus Performance Complexity Inventory

Report date: 2026-06-12
Branch: `refactor/lp-cr-845-benchmark-request-resolution`
Mode: report-only complexity and maintainability inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures the current cyclomatic complexity and maintainability posture for production
Python paths. It gives the hardening stream repeatable evidence for hotspot selection without
turning the first measurement into a premature merge blocker.

## Command

```powershell
python scripts/python_complexity_inventory.py --limit 25
```

## Summary

| Metric | Value |
| --- | ---: |
| Max cyclomatic complexity | 9 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 55.26 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `_runtime_retention_payload_identity_matches` | function | `app/services/operator_action_replay_service.py:191` | 9 | B |
| 2 | `parse_stateful_portfolio_timeseries_payload` | function | `app/services/portfolio_source_service.py:59` | 9 | B |
| 3 | `build_returns_series_execution_window` | function | `app/services/returns_series_calculation_workflow_service.py:55` | 9 | B |
| 4 | `detect_gaps` | function | `app/services/returns_series_service.py:277` | 9 | B |
| 5 | `_validate_manifest_entry` | function | `app/services/runtime_retention_history_service.py:197` | 9 | B |
| 6 | `_position_market_value_pair` | function | `app/services/stateful_attribution_input_service.py:371` | 9 | B |
| 7 | `build_stateful_benchmark_input` | function | `app/services/stateful_benchmark_input_service.py:39` | 9 | B |
| 8 | `_load_component_price_series` | function | `app/services/stateful_benchmark_input_service.py:354` | 9 | B |
| 9 | `_build_component_observation` | function | `app/services/stateful_benchmark_input_service.py:532` | 9 | B |
| 10 | `get_benchmark_return_series` | method | `app/services/stateful_input_service.py:231` | 9 | B |
| 11 | `get_benchmark_market_series` | method | `app/services/stateful_input_service.py:398` | 9 | B |
| 12 | `get_fx_rates` | method | `app/services/stateful_input_service.py:478` | 9 | B |
| 13 | `get_index_price_series` | method | `app/services/stateful_input_service.py:599` | 9 | B |
| 14 | `get_risk_free_series` | method | `app/services/stateful_input_service.py:683` | 9 | B |
| 15 | `_fetch_position_chunk` | method | `app/services/stateful_input_service.py:882` | 9 | B |
| 16 | `_component_points_by_index` | method | `app/services/stateful_input_service.py:1101` | 9 | B |
| 17 | `_collect_stateful_mwr_cash_flows` | function | `app/services/stateful_mwr_input_service.py:184` | 9 | B |
| 18 | `split_position_cash_flows_in_value_basis` | function | `app/services/stateful_position_row_service.py:14` | 9 | B |
| 19 | `_build_price_point_observation` | function | `app/services/stateless_benchmark_input_service.py:87` | 9 | B |
| 20 | `build_twr_benchmark_supportability_evidence` | function | `app/services/twr_benchmark_supportability.py:18` | 9 | B |
| 21 | `calculate_twr_workflow` | function | `app/services/twr_calculation_service.py:258` | 9 | B |
| 22 | `resolve_twr_request` | function | `app/services/twr_mode_service.py:80` | 9 | B |
| 23 | `_build_workspace_summary_response` | function | `app/services/workspace_summary_service.py:502` | 9 | B |
| 24 | `_lineage_worker_runtime` | function | `app/workers/lineage_worker.py:69` | 9 | B |
| 25 | `resolve_workspace_periods` | function | `core/workspace_periods.py:56` | 9 | B |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 3.54 | C |
| 7 | `app/services/twr_service.py` | 6.43 | C |
| 8 | `app/services/workspace_summary_service.py` | 10.70 | B |
| 9 | `app/services/execution_registry.py` | 10.84 | B |
| 10 | `app/services/stateful_benchmark_input_service.py` | 12.90 | B |
| 11 | `engine/attribution.py` | 14.14 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.95 | B |
| 13 | `app/services/inspection/calculation_consistency.py` | 16.16 | B |
| 14 | `app/services/inspection/reconciliation.py` | 16.40 | B |
| 15 | `app/services/inspection/source_economics_collector.py` | 17.35 | B |
| 16 | `app/services/inspection/source_economics.py` | 17.49 | B |
| 17 | `app/workers/compute_executor_worker.py` | 18.03 | B |
| 18 | `app/services/twr_mode_service.py` | 18.52 | B |
| 19 | `app/services/inspection/source_quality.py` | 18.55 | B |
| 20 | `app/models/runtime_status.py` | 19.85 | A |
| 21 | `app/models/returns_series.py` | 20.22 | A |
| 22 | `app/services/inspection/twr_inspection_service.py` | 20.47 | A |
| 23 | `engine/composites.py` | 22.41 | A |
| 24 | `app/services/stateful_mwr_input_service.py` | 22.67 | A |
| 25 | `engine/mwr.py` | 23.41 | A |

## Interpretation

The D/F high-complexity function inventory is now clear. `calculate_benchmark_returns` dropped out
of the top-20 table after component contribution projection, daily aggregation, cumulative linking,
and weight diagnostics were split into named stages, reducing the measured maximum cyclomatic
complexity from `15` to `14`. `_lineage_queue_response` also dropped out after optional lineage
queue stats and storage-capacity projection were split into a dedicated measurement helper.
`_parse_reclaimed_event_payload` also dropped out after post-filter reclaimed-event field-shape
validation was split into a dedicated predicate. `collect_runtime_degradation_reasons` also dropped
out after queue, recovery-drill, and retention reason prefixing were routed through one structural
component-status helper. `build_portfolio_source_quality_evidence` also dropped out after
unsupported cashflow taxonomy traversal was split into a dedicated count helper.
`_collect_stateful_mwr_cash_flows` also dropped out after source-flow eligibility and evidence
component projection were split into a dedicated helper.
`portfolio_timeseries_to_valuation_points` also dropped out after fee/external/unsupported cashflow
classification and timing aggregation were split into a dedicated totals helper.
`_apply_overrides` also dropped out after override targeting and field application/counting were
split into reusable policy helpers.
`build_hierarchical_contribution_result` also dropped out after Carino residual eligibility,
proportion calculation, and weighted allocation were split into a dedicated calculation helper.
`_build_twr_results_by_period` also dropped out after benchmark-period and relative-performance
assembly were split behind a typed benchmark-period context, reducing the measured maximum
cyclomatic complexity from `14` to `13`.
`_build_artifacts` also dropped out after customer-consumable composite-period return row
projection and optional-value formatting were split into a dedicated helper, reducing the measured
maximum cyclomatic complexity from `13` to `12`.
`_summarize_currency_source` also dropped out after position and benchmark component currency
filtering, de-duplication, and ordering were routed through a shared source-currency normalizer.
`_build_benchmark_groups`,
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
`_build_composite_period_fact_set` also dropped out after ready/excluded member classification and
aggregate fact metadata assembly were separated into independently testable helpers.
`run_calculations` also dropped out after effective-period/daily-return attachment, policy outlier
flagging, reset-event projection, and diagnostics assembly were separated from the public engine
orchestrator.
`_calculate_dietz_mwr_result` also dropped out after Dietz method selection, annualized rate
calculation, and XIRR fallback metadata construction were separated into independently testable
helpers.
`_latest_attribution_observation_date` also dropped out after portfolio, instrument,
portfolio-group, and benchmark-group observation date extraction were split into dedicated
supportability helpers.
`calculate_attribution` also dropped out again after response meta construction, calculation
supportability construction/metric recording, and benchmark-context projection were split into
dedicated helpers.
`_record_taxonomy_samples` also dropped out after repeated dated sample append branches were routed
through reusable taxonomy sampling helpers. `DurableQueueCollector.collect` also dropped out after
availability and runtime-retention preview metric emission were separated from queue/storage/history
metric collection. `ContributionAnalyticsRequest.validate_mode_payloads` also dropped out after
legacy payload-shape checks and stateless/stateful contribution payload checks were split into
dedicated helpers. `TWRBenchmarkRequest` also dropped out after stateless/stateful benchmark payload
checks and calculated/vendor-series stateless rules were split into dedicated helpers.
`_build_contribution_smoothing_evidence` also dropped out after smoothing status/reason-code policy
and Carino factor range extraction were split into dedicated helpers. `_record_fee_samples` also
dropped out after fee normalization, fee source-signal, and fee timing sample routing were split
into dedicated helpers. `validate_history_manifest_header` also dropped out after manifest filename
and retention-field validation were split into dedicated helpers. `_summarize_benchmark_classification`
also dropped out after benchmark classification label indexing and classified component counting
were split into dedicated helpers. `process_pending_jobs` also dropped out after leased-payload
materialization outcome handling and retry-budget policy were split into dedicated helpers.
`resolve_period` also dropped out after explicit, calendar, trailing-year, and rolling period
resolution policy were split into dedicated helpers. `_build_benchmark_breakdowns` also dropped out
after daily/non-daily grouping, breakdown item construction, and period-label policy were split into
dedicated helpers. `_check_relative_block` also dropped out after relative summary checks,
per-frequency cardinality checks, and row-level relative arithmetic were split into dedicated
helpers. `build_source_economics_findings` also dropped out after observation-contract,
explicit-amount-contract, and detailed cash-flow contract finding groups were split into dedicated
helpers. `_map_workflow_pack_run` also dropped out after run-id validation, finding projection,
string-list filtering, replacement-run-id projection, and posture boolean policy were split into
dedicated helpers. `run_twr_inspection` also dropped out after subject-resolution stage lifecycle
handling and subject identity evidence were split into a dedicated helper. Max cyclomatic
complexity is now `14`. `build_source_preconverted_mwr_currency_evidence` also dropped out after
market-value collection validation, cash-flow index validation, and cash-flow response evidence
projection were split into dedicated helpers. `_recovery_drill_payload_matches_entry` also dropped
out after recovery-drill evidence shape checks and entry-identity checks were split into dedicated
helpers. `DurableQueueCollector.collect` also dropped out after compute queue, lineage queue,
lineage storage, and storage-threshold metric emission were routed through a dedicated core metrics
helper. `_calculate_returns_series` also dropped out after initial hash/window, benchmark context,
stateful resolution, and execution-identity setup were moved into a dedicated execution-context
helper. `resolve_stateful_returns_series_request` also dropped out after stateful normalization,
normalization-stage details, identity payload construction, and resolved stateless request assembly
were moved into a dedicated helper. Attribution `_position_meta_from_row` also dropped out after
dynamic position-dimension normalization was moved into a dedicated helper. The remaining
highest-complexity function `_build_component_observations` also dropped out after per-component
validation and return projection were moved into a dedicated helper. The remaining C-grade service
and engine hotspot `_build_component_observations_from_price_points` also dropped out after
price-pair validation and stateless return projection were moved into a dedicated helper. The
remaining C-grade hotspot `resolve_twr_request` also dropped out after retrieval-to-normalization
conversion and normalization-stage detail assembly were moved into a typed dedicated helper. The
remaining C-grade hotspot `_resolve_twr_benchmark_source_input` also dropped out after benchmark
assignment identity resolution and evidence were moved into a typed dedicated helper. The remaining
C-grade hotspot `_resolve_workspace_benchmark_input` also dropped out after TWR and workspace
benchmark-assignment policy was promoted into one shared source-boundary service. The remaining
C-grade hotspot `_build_compute_job_runtime` also dropped out after calculator and execution-store
dependency wiring were moved into a dedicated execution-context builder. The remaining C-grade
contribution `_position_meta_from_row` hotspot also dropped out after source-contract identity,
currency, and FX metadata normalization were moved into a dedicated helper.
`_build_workspace_summary_response` also dropped out after benchmark-window gating, benchmark
summary assembly, and active net/gross return projection were moved into a dedicated helper.
`_build_instrument_attribution_panel` also dropped out after return-column naming, same-currency
local/FX backfill, and percentage scaling were moved into a dedicated helper.
`aggregate_attribution_results` also dropped out after per-period active return calculation,
linking status policy, invalid-chain fallback, geometric scaling, and granular effect totals were
moved into a dedicated aggregation-base helper.
`_prepare_dataframe` also dropped out after precision-mode numeric coercion was moved into a
dedicated engine-input preparation helper.
`_xirr` also dropped out after no-root, multiple-root, and successful-root result projection was
moved into a dedicated solver-outcome helper, reducing the measured maximum cyclomatic complexity
from `12` to `11`.
`BenchmarkPerformanceRequest` also dropped out after analysis-window validation and return-source
payload exclusivity were moved into dedicated request-policy helpers.
`_ensure_error_response_examples` also dropped out after error-code detection and eligible
validation-error JSON content selection were split into dedicated helpers.
`calculate_benchmark_artifacts` also moved from C-grade CC `11` to B-grade CC `10` after calculated
and vendor-series source artifact assembly were moved into a typed helper.
`_build_exposure_rows` also dropped out after per-point validation, grouping, weight accumulation,
and label/component-id capture were moved into a dedicated helper.
`get_queue_stats` also dropped out after aggregate-row count defaulting, age projection, and
reclaimable-count projection were moved into a dedicated queue-stats mapper.
`calculate_contribution_workflow` also dropped out after promoted stateful replay, sync
registration, resolved-request finalization, and stateful error mapping were moved into a dedicated
workflow helper.
`_build_residual_adjusted_position_timeseries` also dropped out after per-position residual
allocation, weight fallback, and adjusted daily row projection were moved into a dedicated helper.
`calculate_returns_series_workflow` also dropped out after promoted stateful replay, sync
registration, resolved-request finalization, async offload decisioning, and failure mapping were
moved into a dedicated workflow helper.
`retrieve_stateful_attribution_source_input` also dropped out after benchmark assignment override,
upstream assignment retrieval, 404 mapping, source failure mapping, and payload validation were
moved into a dedicated benchmark-id resolver.
`_position_market_value_totals_by_date` also dropped out after per-row market-value pair selection,
reporting-currency preference, portfolio-currency fallback, and incomplete-row handling were moved
into a dedicated helper.
`_validate_stateful_position_inception_support` also dropped out after ordered first-row selection
and per-position deduplication were moved into a dedicated helper.
`_load_fx_maps_for_components` also dropped out after benchmark-currency comparison,
non-benchmark component currency detection, and FX pair deduplication were moved into a dedicated
helper.
`_build_normalized_component_series` also dropped out after per-component point filtering,
requested-window date handling, local-price capture, FX normalization, and requested-date coverage
collection were moved into a dedicated helper.
`_fetch_position_chunk` also dropped out after position request-payload assembly and upstream
snapshot append/de-duplication were moved into dedicated helpers.
`register_async_submission_or_raise` also dropped out after async submission stage completion and
replay self-healing policy were moved into a dedicated lifecycle helper.
`build_twr_execution_window` also dropped out after optional benchmark identity, input-mode,
return-source, and work-unit projection were moved into a dedicated benchmark-field helper.
`process_pending_jobs` also dropped out after lineage worker dependency/default resolution was
moved into a typed runtime assembly helper.
`generate_performance_breakdowns` also dropped out after daily breakdown row period-label and
summary projection were moved into a dedicated helper.
`_flag_outliers` also dropped out after rolling median/MAD bounds, ignored-date filtering, and
outlier mask construction were moved into a dedicated helper, reducing the measured maximum
cyclomatic complexity from `11` to `10`.
`to_stateless_attribution_request` also dropped out after stateless input source selection,
explicit override precedence, and nested/legacy fallback were moved into a typed resolver helper.
`to_stateless_mwr_request` also dropped out after explicit override precedence, nested stateless
payload fallback, and legacy payload fallback were moved into a typed resolver helper.
`_infer_description` also dropped out after schema-property description inference was split into
named semantic rules and a small rule resolver.
`calculate_benchmark_artifacts` also dropped out after benchmark period slicing, cumulative
linking, summary construction, breakdown construction, and optional timeseries projection were
moved into a dedicated period-result helper.
`calculate_benchmark_workflow` also dropped out after promoted stateful replay, sync registration,
resolved stateful finalization, optional offload, and response calculation were moved into a
dedicated workflow branch helper.
`resolve_benchmark_request` also dropped out after stateless source-detail counting, input-count
selection, calculated observation normalization, and final benchmark request projection were moved
into a dedicated stateless resolver.
`_resolve_stateless_twr_benchmark_request` also dropped out after stateless benchmark request
eligibility, required stateless benchmark input selection, and vendor/calculated payload projection
were moved into dedicated helpers.
`_resolve_twr_benchmark_source_input` also dropped out after stateful benchmark engine-request
projection was moved into a dedicated helper.
`_iter_frequency_windows` also dropped out after daily grouping and resampled frequency-label
selection were moved into dedicated helpers.
`_build_portfolio_breakdowns` also dropped out after per-window portfolio breakdown item projection
was moved into a dedicated helper.
`_build_twr_results_by_period` also dropped out after portfolio period-block assembly and reset-event
window filtering were moved into dedicated helpers.
`_valuation_cashflow_totals` also dropped out after per-flow valuation cashflow total projection
was moved into a dedicated helper.
`workspace_longest_requested_window_days` also dropped out after since-inception default-window and
assumed-start selection policy were moved into dedicated helpers.
`_queue_stats_from_aggregate_row` also dropped out after aggregate-row count defaulting and numeric
conversion were moved into a dedicated mapper helper.
`calculate_contribution` also dropped out after hierarchy-period slicing, position total
construction, hierarchy response projection, smoothing evidence, and average-weight methodology
status assembly were moved into a dedicated hierarchy-period result helper.
`generate_twr_inspection_support_brief` also dropped out after lotus-ai response payload
interpretation and workflow-pack run posture mapping were moved into a dedicated result mapper.
`run_twr_inspection` also dropped out after subject request materialization and calculation
consistency loading were moved into a dedicated subject-input resolver.
`_build_twr_inspection_response` also dropped out after finding concatenation, failed-family
evidence projection, no-check finding insertion, and pending-family calculation were moved into a
dedicated finding-context helper.
`validate_mode_fields` also dropped out after explicit and relative returns-window validation
policy were moved into dedicated helpers.
`_validate_returns_series_input_envelopes` also dropped out after stateless and stateful request
envelope policy were moved into dedicated helpers.
`JsonFormatter` also dropped out after structured log payload assembly and extra-field filtering
were moved into dedicated helpers.
`_build_schema_example` also dropped out after `$ref` resolution and recursion handling were moved
into a dedicated schema-example helper.
`_ensure_operation_documentation` also dropped out after OpenAPI path/method filtering was moved
into a dedicated documentable-operation iterator.
`_ensure_property_schema_documentation` also dropped out after Lotus semantic-id and canonical-term
property metadata were moved into a dedicated vocabulary helper.
`calculate_attribution_workflow` also dropped out after resolved stateful finalization and initial
async submission policy were moved into dedicated workflow helpers.
`calculate_attribution` dropped out of the top-25 table after attribution period resolution,
empty-period rejection, master date span calculation, and master request projection were isolated
from the public attribution calculation entrypoint.
`_group_identity` also dropped out after generic classification group identity and issuer group
identity projection were split into dedicated benchmark exposure context helpers.
`reconcile_stale_jobs` also dropped out after stale row mutation and reconciled-record projection
were isolated from the durable compute queue reconciliation query loop.
`_to_record` also dropped out after invalid request/response payload status and error fallback
policy was isolated from durable compute job record projection.
`_rollout_posture_notes` also dropped out after rollout note presence checks were isolated from
ordered reset-aware average-weight diagnostic note assembly.
`_compare_return_values` also dropped out after comparative return mismatch detection was isolated
from TWR inspection finding construction.
`_build_detailed_cashflow_contract_findings` also dropped out after detailed cash-flow source
contract finding definitions were moved into an explicit ordered catalog and the builder was reduced
to catalog application.
`filter_history_entries` also dropped out after exact-filter application and optional filter
normalization were isolated from generated-at bound filtering.
`validate_history_manifest_header` also dropped out after safe latest/retained manifest filename
projection was isolated from retention-field and entry-list validation.
`_read_active_operator_action_lease` also dropped out after active lease payload field validation
was isolated from lock-file identity projection.
The remaining C-grade
hotspots should be treated as future bounded refactor candidates, not as evidence of an immediate
behavior defect.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the baseline is stable,
false positives are understood, and remediation guidance is documented.
