# Lotus Performance Complexity Inventory

Report date: 2026-06-28
Branch: `feature/enterprise-backend-refactor-baseline`
Mode: measured complexity and maintainability inventory; max CC and D-F count are enforced by CI.

## Purpose

This report captures the current cyclomatic complexity and maintainability posture for production
Python paths. It gives the hardening stream repeatable evidence for hotspot selection and backs the
current complexity regression gate. Maintainability index remains report-only until a stable
threshold and exception policy exist.

## Command

```powershell
python scripts/python_complexity_inventory.py --limit 25 --max-cc 8 --max-high-complexity 0
```

Blocking CI command:

```powershell
make quality-complexity-gate
```

Gate threshold: max cyclomatic complexity must stay at or below `8`, and rank D-F function count
must stay at `0`.

## Summary

| Metric | Value |
| --- | ---: |
| Max cyclomatic complexity | 5 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 54.91 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `_record_fee_source_consistency_sample` | method | `app/services/inspection/source_economics_collector.py:197` | 5 | A |
| 2 | `_record_external_source_signals` | method | `app/services/inspection/source_economics_collector.py:269` | 5 | A |
| 3 | `_external_explicit_mixed_timing_sample` | function | `app/services/inspection/source_economics_collector.py:350` | 5 | A |
| 4 | `_expected_external_total` | function | `app/services/inspection/source_economics_collector.py:412` | 5 | A |
| 5 | `_append_stale_run_if_needed` | function | `app/services/inspection/source_quality.py:346` | 5 | A |
| 6 | `_assess_return_concentration` | function | `app/services/inspection/source_quality.py:481` | 5 | A |
| 7 | `_find_repeated_move_runs` | function | `app/services/inspection/source_quality.py:540` | 5 | A |
| 8 | `_monthly_day_dominance` | function | `app/services/inspection/source_quality.py:641` | 5 | A |
| 9 | `_find_missing_business_dates` | function | `app/services/inspection/source_quality.py:761` | 5 | A |
| 10 | `load_existing_twr_calculation_artifacts` | function | `app/services/inspection/subject_materialization.py:40` | 5 | A |
| 11 | `extract_performance_request_from_payload` | function | `app/services/inspection/subject_materialization.py:98` | 5 | A |
| 12 | `resolve_twr_inspection_subject` | function | `app/services/inspection/subject_resolution.py:20` | 5 | A |
| 13 | `_completed_support_brief_markdown` | function | `app/services/inspection/support_brief_workflow_pack.py:78` | 5 | A |
| 14 | `_map_workflow_pack_run_finding` | function | `app/services/inspection/support_brief_workflow_pack.py:192` | 5 | A |
| 15 | `_synthesize_verdict` | function | `app/services/inspection/twr_inspection_service.py:643` | 5 | A |
| 16 | `_scope_request_to_response_master_window` | function | `app/services/inspection/twr_inspection_service.py:759` | 5 | A |
| 17 | `get_record` | method | `app/services/lineage_metadata_store.py:249` | 5 | A |
| 18 | `lease_pending_payloads` | method | `app/services/lineage_metadata_store.py:360` | 5 | A |
| 19 | `list_recent_recoveries` | method | `app/services/lineage_metadata_store.py:435` | 5 | A |
| 20 | `_apply_recovery_time_filters` | method | `app/services/lineage_metadata_store.py:698` | 5 | A |
| 21 | `_inspection_timing` | method | `app/services/lineage_metadata_store.py:1044` | 5 | A |
| 22 | `_ensure_payload_lease_columns` | method | `app/services/lineage_metadata_store.py:1070` | 5 | A |
| 23 | `_load_payload_details` | function | `app/services/lineage_metadata_store.py:1238` | 5 | A |
| 24 | `evaluate_mandate_performance_health_context` | function | `app/services/mandate_health_context_service.py:16` | 5 | A |
| 25 | `_stringify_decimal_collection` | function | `app/services/mwr_calculation_service.py:207` | 5 | A |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/openapi_enrichment.py` | 0.00 | C |
| 2 | `app/services/compute_job_store.py` | 0.00 | C |
| 3 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 4 | `app/services/returns_series_service.py` | 0.00 | C |
| 5 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 6 | `app/services/stateful_input_service.py` | 0.00 | C |
| 7 | `app/services/twr_service.py` | 5.69 | C |
| 8 | `app/services/stateful_benchmark_input_service.py` | 8.73 | C |
| 9 | `app/services/workspace_summary_service.py` | 10.08 | B |
| 10 | `app/services/execution_registry.py` | 11.12 | B |
| 11 | `engine/attribution.py` | 11.94 | B |
| 12 | `app/services/operator_action_lease_service.py` | 13.14 | B |
| 13 | `app/services/inspection/source_economics.py` | 14.06 | B |
| 14 | `app/services/inspection/reconciliation.py` | 14.26 | B |
| 15 | `app/services/inspection/source_economics_collector.py` | 15.66 | B |
| 16 | `app/services/inspection/source_quality.py` | 16.49 | B |
| 17 | `app/services/twr_mode_service.py` | 17.66 | B |
| 18 | `app/workers/compute_executor_worker.py` | 18.15 | B |
| 19 | `app/services/inspection/twr_inspection_service.py` | 18.95 | B |
| 20 | `app/models/runtime_status.py` | 19.66 | A |
| 21 | `app/services/inspection/calculation_consistency.py` | 19.69 | A |
| 22 | `app/models/returns_series.py` | 19.70 | A |
| 23 | `engine/composites.py` | 20.75 | A |
| 24 | `engine/mwr.py` | 21.09 | A |
| 25 | `app/services/stateful_mwr_input_service.py` | 21.57 | A |

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
`get_effective_period_start_dates` also dropped out after calendar-period, explicit-period,
fixed-year, and constant-start policies were split into named helpers.
`_calculate_local_daily_return` also dropped out after local numerator, denominator, safe-mask,
zero-series, and division application were split into named helpers, lowering the measured max
cyclomatic complexity from `8` to `7`.
`_allowed_audit_metadata` also dropped out after allowed-audit eligibility, privileged-read audit
eligibility, access-mode projection, and required-capability projection were split into named
helpers.
`to_benchmark_performance_request` also dropped out after component-observation and benchmark-return
point payload fallback projection were split into named helpers.
`get_benchmark_return_series` also dropped out after benchmark, index-price, and risk-free reference
series response point merging was routed through a shared helper.
`get_fx_rates` also dropped out after FX-rate response-to-point projection and date-key
deduplication were routed through a focused helper.
`get_index_catalog` also dropped out after sorted index-catalog snapshot identity and duplicate
suppression were isolated from retrieval orchestration.
`_fetch_position_chunk` also dropped out after position page retrieval/request-payload projection
and snapshot-batch flushing were moved into focused helpers.
`_next_page_token` also dropped out after reusable non-empty string token qualification was isolated.
`_merge_dedup_records_by_fields` also dropped out after multi-field record-key construction was
isolated into a focused helper.
`_component_index_points` also dropped out after component index identifier qualification and
component point-record projection were split into focused helpers.
`_has_single_currency_inputs` also dropped out after portfolio/reporting currency matching was
split into a focused helper.
`retrieve_stateful_portfolio_input` also dropped out after upstream portfolio-timeseries response
source selection was split into a focused helper.
`_build_portfolio_breakdown_item` also dropped out after daily raw-data projection and daily
calculation-evidence projection were split into named helpers.
`_build_twr_results_by_period` also dropped out after single-period result construction, optional
benchmark projection, and reset-event attachment were split into a dedicated period-result helper.
`_valuation_cashflow_total_component` also dropped out after cash-flow amount destination routing
was split into a dedicated role-and-timing helper.
`_prepare_data_from_instruments` also dropped out after instrument panel collection and empty-panel
suppression were split into a dedicated helper.
`_normalize_instrument_return_columns` also dropped out after same-currency local/FX return
backfill was split into a dedicated helper.
`_build_base_weight_series` also dropped out after per-point base-weight record parsing was split
into a dedicated helper.
`_align_and_prepare_data` also dropped out after aligned-frame observation flags, missing-value
normalization, index naming, and benchmark total-return projection were split into a dedicated
finalization helper.
`aggregate_attribution_results` also dropped out after currency-attribution status selection was
split into a dedicated helper and reused for optional currency result assembly.
`_record_external_timing_contradictions` also dropped out after explicit timing contradiction
eligibility and artifact sample projection were split into named helpers.
`_build_external_cashflow_findings` also dropped out after the repeated external cash-flow finding
construction branches were converted to an explicit ordered finding-definition catalog.
`_build_fee_source_economics_findings` also dropped out after the repeated fee finding construction
branches were converted to the same explicit ordered finding-definition catalog.
`_find_monthly_day_dominance` also dropped out after per-month eligibility, total movement,
dominant-day selection, and threshold projection were split into a dedicated helper.
`load_existing_twr_calculation_artifacts` also dropped out after lineage payload response
validation and request materialization were split into a dedicated helper.
`to_stateless_contribution_request` also dropped out after stateless contribution source selection
was split into a named helper.
`TWRInspectionRequest` also dropped out after TWR calculation-subject and request-subject validation
predicates were split into named helpers.
`_validate_stateless_twr_payloads` also dropped out after nested, legacy, and exactly-one stateless
payload shape predicates were split into named helpers.
`_validate_workspace_summary_stateless_inputs` also dropped out after workspace summary nested,
legacy, and exactly-one stateless payload shape predicates were split into named helpers.
`record_mwr_solver_outcome` also dropped out after bounded MWR solver reason-code and label
projection were split into named helpers.
`_validation_error_json_content` also dropped out after generic application/json content selection
was split into a named helper.
`_ensure_request_body_example` also dropped out after request-body enrichment reused the generic
application/json content selector.
`_ensure_model_schema_documentation` also dropped out after schema-property traversal was split into
a dedicated iterator.
`_ensure_property_schema_documentation` also dropped out after property-description enrichment was
split into a dedicated helper.
`calculate_attribution_workflow` also dropped out after resolved attribution result calculation and
stateful finalization handling were split into a dedicated helper.
`calculate_benchmark_workflow` also dropped out after initial benchmark async submission projection
was split into a dedicated helper.
`_classification_map_from_catalog_records` also dropped out after catalog-record label normalization
was split into a dedicated helper.
`_build_exposure_rows` also dropped out after valid component point traversal was split into a
dedicated iterator.
`resolve_benchmark_request` also dropped out after stateful benchmark request projection and
input-count policy were split into dedicated helpers.
`portfolio_timeseries_to_valuation_points` also dropped out after fee/external/unsupported cashflow
classification and timing aggregation were split into a dedicated totals helper.
`_build_artifacts` also dropped out after member-input and period-weight support artifact row
projection were split into dedicated helpers.
`_composite_return_rows` also dropped out after optional customer-consumable artifact field
formatting was split into a dedicated helper.
`register_job` also dropped out after existing compute-job registration replay matching was split
into a dedicated idempotency predicate.
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
`_resolve_workspace_portfolio_input` also dropped out after stateful portfolio input retrieval,
normalization, and source-detail projection were moved into a dedicated helper.
`_trim_portfolio_input_to_master_window` also dropped out after observation date parsing and
master-window eligibility were moved into a dedicated predicate helper.
`_resolve_workspace_benchmark_input` also dropped out after stateful benchmark identity resolution,
retrieval, request projection, and source-detail merging were moved into a dedicated helper.
`_build_workspace_summary_response` also dropped out after audit count projection was moved into a
dedicated helper while preserving input-row, period, portfolio-source, and benchmark-source counts.
`_annualize_percentage` also dropped out after annualization periods-per-year and elapsed-measure
policy were moved into a dedicated helper while preserving business-day and calendar basis behavior.
`_resolve_async_attribution_job_request` also dropped out after persisted resolved-attribution
payload projection and benchmark-context extraction were moved into a dedicated helper.
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
`_build_schema_example` also dropped out after object and array structural example routing was
moved into a dedicated schema-example helper.
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
`_runtime_retention_payload_identity_matches` also dropped out after required and optional
runtime-retention replay identity comparisons were moved into explicit field catalogs.
`parse_stateful_portfolio_timeseries_payload` also dropped out after observation normalization and
optional string extraction were isolated from required open-date enforcement.
`_build_price_point_observation` also dropped out after same-currency and cross-currency
price-point return projection was isolated from observation construction.
`build_twr_benchmark_supportability_evidence` also dropped out after calendar-alignment state,
date deltas, and calendar warning-code projection were isolated from final evidence construction.
`calculate_twr_workflow` also dropped out after resolved response finalization and final TWR
response calculation were moved into a dedicated helper.
`resolve_twr_request` also dropped out after final resolved request assembly and benchmark-id
precedence were moved into dedicated helpers.
`_build_workspace_summary_response` also dropped out after workspace summary diagnostics note
assembly was moved into a dedicated helper.
`_lineage_worker_runtime` also dropped out after repeated explicit-or-default runtime dependency
selection was routed through a shared helper while preserving existing fallback semantics.
`resolve_workspace_periods` also dropped out after explicit, since-inception, YTD, business-day,
month, and year start-date policy was isolated from resolved-period response assembly.
`_prepare_panel_from_groups` also dropped out after per-observation dict/model normalization,
legacy return fallback, group-key projection, and return-presence tagging were isolated from panel
assembly.
`aggregate_attribution_results` also dropped out after hierarchy level totals, group context,
group-result sorting, and response-level totals were isolated from supportability and currency
attribution assembly.
`_blocked_composite_period_result_for_invalid_ready_facts` also dropped out after invalid-ready
blocked-result construction, single metadata selection, and aggregate reason-code projection were
isolated from validation branch ordering.
`_composite_period_fact_metadata` also dropped out after ready-member asset summation, sorted unique
metadata collection, and excluded reason-code collection were routed through named helpers.
`_flag_outliers` also dropped out after outlier diagnostic sample projection and threshold
selection were isolated from policy eligibility and mask computation.
`_compound_ror` also dropped out after period and reset-driven compounding block identity policy
was isolated from growth-factor and cumulative-return arithmetic, reducing the measured maximum
cyclomatic complexity from `9` to `8`.
`_load_and_validate_manifest` also dropped out after durable-record manifest consistency checks
were isolated from manifest file read and schema-validation error mapping.
`to_stateless_attribution_request` also dropped out after final attribution request payload
assembly and reusable optional model/list serialization were isolated from source resolution and
request validation.
`_resolve_mwr_stateless_input` also dropped out after complete explicit override detection and
legacy payload resolution were isolated from nested stateless payload precedence and missing-input
failure handling.
`_validate_returns_series_stateless_selection_inputs` also dropped out after selected benchmark and
risk-free stateless series requirements were routed through one reusable required-series helper.
`WorkspaceBenchmarkRequest` also dropped out after stateless and stateful benchmark payload policy
were split into dedicated workspace benchmark validators.
`_explicit_schema_example` also dropped out after named OpenAPI example extraction was isolated
from direct and list-form schema example precedence.
`resolve_async_result` also dropped out after stored async-result resolution and active compute-job
status policy were isolated from the durable compute-job fallback path.
`AsyncResultStore.get_result` also dropped out after stored response payload state and record
projection were isolated from the row lookup.
`attribution_input_count` also dropped out after nested and legacy stateless input-count projection
was routed through a dedicated helper while preserving stateful zero-count behavior.
`calculate_attribution_workflow` also dropped out after promoted stateful replay and sync-window
source-fingerprint reconstruction were isolated from the public attribution workflow orchestration.
`_inspection_active_since` also dropped out after compute-job inspection timestamp precedence was
routed through an explicit status-to-field policy and shared first-timestamp selector.
`_compute_job_record_payload_state` also dropped out after invalid request/response payload
fail-closed policy, stored/default error selection, and invalid-response detection were split into
explicit helpers.
`record_cutover_assessment` also dropped out after known average-weight rollout blocker counting
was routed through an explicit reason-code-to-counter policy helper.
`_calculate_reset_aware_average_weight_shadow` also dropped out after reset-aware valid portfolio
day selection, reset-relative windowing, shadow-weight application, and delta metric projection
were split into dedicated helpers.
`_build_residual_adjusted_position_timeseries` also dropped out after residual-adjusted row
construction and adjusted-row-to-response-series projection were split into dedicated helpers.
`calculate_contribution` also dropped out after flat-vs-hierarchy period-result collection and
average-weight residual max tracking were moved into a dedicated contribution period-results helper.
`_contribution_smoothing_status_and_reasons` also dropped out after base smoothing status selection
and residual/reconciliation reason-code projection were split into dedicated helpers.
`_available_stateful_economics` also dropped out after cash-flow-derived and metadata-derived
stateful source economics were split into dedicated helpers.
`_cash_flow_type_counts` also dropped out after per-position source cash-flow count map validation
was moved into a dedicated helper.
`_collect_position_continuity_gap_samples` also dropped out after valid position/date row grouping
was moved into a dedicated helper.
`_row_has_transition_activity` also dropped out after transition-activity field eligibility was
isolated from row amount parsing.
`_sum_detailed_cash_flows` also dropped out after detailed cash-flow row recording was isolated
from collection-shape handling and aggregate result projection.
`_record_fee_source_signals` also dropped out after fee-source consistency sampling and positive
fee signal policy were separated.
`run_source_quality_checks` also dropped out after source-quality evidence summary and artifact
payload assembly were moved behind dedicated builders.
`_inspection_timing` also dropped out after active lineage payload lease detection was moved into a
dedicated helper.
`calculate_mwr_response` also dropped out after MWR requested-window projection was moved into a
dedicated helper.
`_validate_component` also dropped out after required source-preconverted FX evidence text-field
validation was moved into a dedicated helper.
`build_applied_history_filters` also dropped out after optional history filter normalization was
moved into a dedicated helper.
`_has_valid_reclaimed_event_fields` also dropped out after reclaimed-event string-field validation
was moved into a dedicated helper.
`_build_resolved_stateful_returns_series_request` also dropped out after resolved stateless request
payload construction was moved into a dedicated helper.
`resolve_stateful_returns_series_request` also dropped out after upstream portfolio-source
retrieval and HTTP error mapping were moved into a dedicated helper.
`runtime_retention_preview_fields` also dropped out after nullable runtime-retention preview summary
field projection was moved into a dedicated helper.
`classify_cashflow_type` also dropped out after canonical, alias, internal, external, and
unsupported cashflow taxonomy policy was moved into an explicit classification-rule catalog.
`_summarize_position_classification` also dropped out after per-row required-dimension detection was
moved into a dedicated predicate.
`_validate_stateful_position_inception_support` also dropped out after acquisition-day unsupported
position detection was moved into a dedicated predicate.
`_build_group_key` also dropped out after benchmark group dimension value resolution, currency
required-label validation, and non-currency unknown fallback were moved into a dedicated helper.
`_position_row_to_daily_point` also dropped out after market-value source selection, reporting
fallback, and value-basis policy were moved into a dedicated helper.
`_position_meta_from_row` also dropped out after position FX-rate metadata projection and Decimal
conversion were moved into a dedicated helper.
`_normalized_price_maps_for_component` also dropped out after per-point date filtering,
index-price validation, local-price parsing, FX normalization, and requested-window membership were
moved into a dedicated helper.
`build_stateful_contribution_input` also dropped out after position-row grouping, usable-point
filtering, and latest metadata projection were moved into a dedicated helper.
`_position_row_to_daily_point` also dropped out after local/reporting/portfolio value-basis
selection and missing-value rejection were moved into a dedicated helper.
The stale contribution `_split_position_cash_flows` helper also dropped out after it was removed;
the runtime path already used `split_position_cash_flows_in_value_basis`, so its test-only coverage
was deleted with the dead helper.
`get_position_timeseries` also dropped out after successful response row merging, de-duplication,
and retrieval metadata projection were moved into a dedicated payload assembly helper.
`build_stateful_mwr_input_for_window` also dropped out after sorted non-zero cash-flow projection
and cash-flow evidence construction were moved into a dedicated helper.
`_cash_flow_conversion_factor` also dropped out after cash-flow/position currency mismatch
validation was moved into a dedicated predicate.
`mark_running` also dropped out after terminal-status and worker-lease transition guards were moved
into a dedicated helper.
`list_inspection_items` also dropped out after inspection status count/item statement selection was
moved into a dedicated helper.
`calculate_contribution_workflow` also dropped out after initial async submission projection was
moved into a dedicated helper.
`_calculate_position_flow_balance_counts` also dropped out after daily cash-flow projection,
portfolio capital-base projection, and residual basis-point sizing were moved into dedicated
helpers.
`_classify_average_weight_shadow_cutover_blockers` also dropped out after structural blocker
condition assembly was moved into a dedicated helper.
`_build_hierarchy_rows` also dropped out after threshold and top-N hierarchy emission partitioning
was moved into a dedicated helper.
`_degraded_stateful_economics` also dropped out after unsupported source cash-flow and
unclassified metadata predicates were moved into dedicated helpers.
`_source_cash_flow_type_counts` also dropped out after source cash-flow count-entry validation was
moved into a dedicated helper.
`check_lineage_storage_ready` also dropped out after lineage storage path unavailable-status
resolution was moved into a dedicated helper.
`record_upstream_snapshots` also dropped out after existing snapshot-id lookup and upstream
snapshot model projection were moved into dedicated helpers.
`_expected_daily_calculation_values` also dropped out after expected daily external-flow totals and
daily return eligibility were moved into dedicated helpers.
`_expected_daily_period_statuses` also dropped out after no-investment period status transition
policy was moved into a dedicated helper.
`_comparative_return_mismatches` also dropped out after component-level absent/equal/different
return mismatch policy was moved into a dedicated helper.
`_build_position_reconciliation_findings` also dropped out after evidence-present finding append
policy was moved into a dedicated lazy helper.
`_select_latest_position_rows` also dropped out after string identity-key validation was moved into
a dedicated helper and selection precedence was covered directly.
`_record_external_mixed_timing_samples` also dropped out after detailed and explicit mixed-timing
sample projection policies were moved into dedicated helpers.
`_load_request_payload` also dropped out after lineage request payload JSON parsing was split into
a dedicated helper while preserving file, compute-job, deadline, and polling fallback behavior.
`_support_brief_result_from_payload` also dropped out after completed support-brief markdown
selection was split into a dedicated helper while preserving action-required and unavailable
workflow-pack posture behavior.
`run_twr_inspection` also dropped out after optional source-quality, reconciliation, and
source-economics subject assessment orchestration was routed through a dedicated helper while
preserving stage lifecycle, evidence merging, artifact payload merging, synthesis, and artifact
materialization behavior.
`_synthesize_verdict` also dropped out after not-supportable severity detection was split into a
dedicated predicate while preserving failed-family, high/critical finding, pending-family, and clean
supportable verdict precedence.
`_scope_request_to_response_master_window` also dropped out after valuation-point window filtering
was moved into a dedicated helper while preserving inclusive master-window boundaries and
no-scoped-point fallback behavior.
`validate_history_entry_strings` also dropped out after required and optional history-entry string
normalization were moved into dedicated helpers while preserving evidence filename safety checks.
`build_operator_action_lease_snapshot` also dropped out after reclaimed lease event loading and
failure mapping were moved into a dedicated helper while preserving active-lease snapshot assembly.
`_read_matching_active_operator_action_leases` also dropped out after active lease candidate
matching, invalid-candidate failure mapping, and action-name filtering moved into a dedicated helper.
`_active_lease_payload_fields` also dropped out after required active-lease payload string
collection was moved into a dedicated helper while preserving optional tenant and timestamp checks.
`_read_recent_reclaimed_leases` also dropped out after reclaim-history payload list validation and
per-event parsing were moved into a dedicated helper while preserving action-name filtering.
`_parse_reclaimed_event_payload` also dropped out after reclaimed-event action-name validation and
filtering were moved into a dedicated helper while preserving field and timestamp validation.
`_reclaim_stale_lock` also dropped out after stale-lock eligibility resolution was moved into a
dedicated helper while preserving lock deletion and reclaim-evidence write behavior.
`_build_returns_series_diagnostics` also dropped out after selected portfolio, benchmark, and
risk-free gap collection was moved into a dedicated helper while preserving coverage, fail-fast,
warning, and diagnostics assembly behavior.
`_resolve_returns_series_execution_context` also dropped out after requested execution-context
identity, window, input-mode, and benchmark context selection were moved into a dedicated helper
while preserving stateful resolution, execution identity updates, and override behavior.
`run_runtime_retention_cleanup` also dropped out after apply-preview and manual cooldown guard
policy were moved into a dedicated helper while preserving replay, guard ordering, lease,
execution, and response behavior.
`runtime_status_from_component_statuses` also dropped out after runtime component availability
selection was moved into a dedicated predicate while preserving draining and durable metadata
precedence.
`_benchmark_group_dimension_value` also dropped out after required benchmark currency
classification validation was moved into a dedicated helper while preserving normalization and
non-currency unknown fallback behavior.
`_position_daily_point_market_values` also dropped out after reporting-currency market-value
fallback selection was moved into a dedicated helper while preserving reporting value-basis
semantics.
`_split_position_cash_flows` also dropped out after supported BOD/EOD cash-flow amount parsing was
moved into a dedicated helper while preserving invalid-flow suppression and Decimal conversion.
`_component_price_series_from_response` also dropped out after component price-series points
validation and dict-point filtering moved into a dedicated helper while preserving upstream status
mapping and series-currency inference.
`_build_component_observations` also dropped out after active composition-segment selection and
sorting moved into a dedicated helper while preserving missing-active-segment rejection and
observation assembly order.
`_position_value_inputs` also dropped out after reporting-currency value-pair fallback selection
was moved into a dedicated helper while preserving LOCAL_ONLY precedence, reporting value basis, and
missing-value suppression.
`_position_contract_meta_from_row` also dropped out after FX-rate metadata Decimal projection moved
into a dedicated helper while preserving security, currency, cash-flow currency, and FX metadata
shape.
`_calculate_period_summary_dict` also dropped out after annualized-return day-count and basis
projection moved into a dedicated helper while preserving cumulative-return inclusion and
positive-day guard behavior.
`_coerce_engine_numeric_columns` also dropped out after numeric column ownership, Decimal-strict
coercion, and standard Pandas coercion moved into dedicated helpers while preserving missing and
invalid numeric value zeroing behavior.
`_xirr_initial_failure` and the extracted `_xirr_initial_failure_reason` also dropped out after
initial XIRR failure reason selection was split from failure payload construction and its economic
content, sign-change, and solver-bound predicates were isolated.
`_apply_ignore_days` also dropped out after single-day ignore carry-forward mutation was split into
a dedicated helper while preserving sorted-date processing, previous-day market-value carry-forward,
cash-flow/fee zeroing, diagnostics counts, and notes.
`_compound_ror` also dropped out after leg growth-factor construction, block-level cumulative
growth selection, and Decimal cumulative product behavior were split into dedicated helpers while
preserving long/short leg behavior, reset block usage, Decimal support, and forward-fill semantics.
`format_breakdowns_for_response` also dropped out after response summary payload mapping and
optional daily-data projection were split into dedicated helpers while preserving daily timeseries
gating and response model shape.
`submit_twr_inspection` also dropped out after inspection portfolio identity resolution and
requested-window projection were split into dedicated helpers while preserving existing-calculation
fallback identity and durable submission metadata.
`get_lineage_data` also dropped out after terminal and completed lineage response resolution moved
behind a dedicated helper while preserving storage-integrity validation, controlled artifact links,
and endpoint-level exception mapping.
`get_lineage_artifact` also dropped out after complete-record and declared-artifact eligibility
moved behind a dedicated helper while preserving manifest consistency and file-existence checks.
`_workspace_requested_benchmark_work_units` also dropped out after stateless calculated-versus-vendor
benchmark work-unit counting was centralized and reused by workspace-summary and TWR offload policy.
`calculate_workspace_summary_endpoint` also dropped out after durable requested-window projection
and async offload-reason selection moved into dedicated deterministic helpers.
`_normalized_capability_rule_overrides` also dropped out after single-rule string validation,
whitespace normalization, and blank-value rejection moved into a dedicated security-policy helper.
`_enterprise_runtime_config_issues` also dropped out after secret-rotation range validity and
write-authorization primary-key readiness moved into dedicated security predicates.
`_validate_stateless_input_shape` also dropped out after nested-versus-legacy attribution envelope
selection and its authored validation messages moved into a dedicated issue-selector helper.
`AttributionLevelResult` also dropped out after typed-versus-mapping level-total normalization moved
into a dedicated response-contract helper while preserving authoritative total-field backfill.
`CompositeMembership` also dropped out after effective-window ordering and non-included status-reason
requirements moved into dedicated composite-governance predicates.
`_validate_stateless_contribution_payloads` also dropped out after nested-versus-legacy contribution
envelope issue selection moved into a dedicated compatibility-policy helper.
`_stateless_contribution_envelope_issue` also dropped out after exact-one contribution input-shape
selection moved into a dedicated predicate while preserving authored validation messages.
`_resolved_stateless_contribution_inputs` also dropped out after complete input-pair recognition and
override/nested/legacy precedence moved into dedicated selection policy.
The remaining measured `_resolved_stateless_contribution_inputs` entry later dropped out after
nested stateless input-pair projection moved into a dedicated helper while preserving source
precedence.
`build_execution_response` also dropped out after optional compute-job response projection moved
into a dedicated helper while preserving execution polling payload shape.
`TWRInspectionRequest` also dropped out after inspection subject-mode validation message selection
moved into a dedicated issue helper while preserving accepted subject shapes.
`_stateless_mwr_envelope_issue` also dropped out after exact-one MWR input-shape selection moved
into a dedicated predicate while preserving authored validation messages.
`_validate_stateful_mwr_payloads` also dropped out after stateful MWR payload issue ordering moved
into a dedicated selector while preserving validation-message priority.
`_validate_stateless_mwr_payloads` also dropped out after nested-versus-legacy MWR envelope issue
selection moved into a dedicated compatibility-policy helper.
`_validate_stateless_twr_payloads` also dropped out after nested-versus-legacy TWR envelope issue
selection moved into a dedicated compatibility-policy helper.
`_validate_twr_benchmark_inclusion` also dropped out after stateless benchmark-config requirements
moved into a dedicated inclusion-policy predicate.
`to_stateless_performance_request` and aggregate `TWRAnalyticsRequest` also dropped out after
explicit/nested/legacy valuation-point precedence moved into a dedicated resolver.
`_validate_workspace_summary_stateless_inputs` also dropped out after nested-versus-legacy workspace
valuation envelope issue selection moved into a dedicated compatibility-policy helper.
`_json_log_payload` also dropped out after correlation, request, and trace context projection moved
into a dedicated observability helper.
`_typed_schema_example` also dropped out after scalar schema defaults moved into a dedicated
OpenAPI example-policy helper.
`_semantic_string_example` also dropped out after date and time example selection moved into a
dedicated temporal example-policy helper.
`_build_schema_example` also dropped out after composed-before-structural example selection moved
into a dedicated derived-example policy helper.
`_ensure_request_body_example` also dropped out after operation override, authored example, and
schema-generated example selection moved into a dedicated request-body example-policy helper.
`_iter_documentable_operations` also dropped out after HTTP method eligibility, operation-shape
validation, and identity normalization moved into a dedicated operation-projection helper.
`resolve_async_result` also dropped out after missing, active, failed, and completed compute-job
fallback resolution moved into a dedicated state-policy helper.
`build_single_period_attribution_response` also dropped out after optional currency result and
totals projection moved into a dedicated response-policy helper.
`_count_attribution_input_rows` and the intermediate portfolio counter also dropped out after
direct portfolio and optional nested-source row counting moved into dedicated workload helpers.
`resolve_benchmark_identity` also dropped out after assignment response status, payload identity,
and evidence projection moved into a dedicated assignment-policy helper.
`_resolved_assignment_identity` also dropped out after assignment status handling and benchmark-id
payload validation were split into dedicated helpers.
`calculate_benchmark_artifacts` also dropped out after resolved-period result collection was split
into a dedicated helper while preserving empty-period suppression and per-period frequency routing.
`_benchmark_period_result` also dropped out after optional daily and component timeseries response
projection was split into a dedicated helper while preserving output gating and empty component
suppression.
`_calculate_benchmark_return_from_slice` also dropped out after optional local and FX benchmark
return component projection was split into a dedicated helper while preserving missing and all-null
component suppression.
`_group_benchmark_breakdown_rows` also dropped out after daily row projection and calendar
resampling were split into dedicated helpers while preserving date normalization and grouped-row
shape.
`build_benchmark_exposure_context` also dropped out after market-series status mapping and
component-series payload parsing were moved into a dedicated response-policy helper.
`_benchmark_id_from_assignment_response` also dropped out after assignment response status mapping
and benchmark-id payload extraction were split into dedicated helpers while preserving 422/503
semantics.
`_classification_map_for_request` also dropped out after catalog payload records-list validation
and classification-map construction moved into a dedicated helper while preserving source-failure
mapping.
`_index_ids_for_component_series` also dropped out after component index-id qualification moved
into a dedicated iterator while preserving duplicate suppression and deterministic sorting.
`calculate_benchmark_artifacts` also dropped out after daily and optional component artifact date
normalization moved into a dedicated source-artifact normalization helper.
`_benchmark_period_result` also dropped out after inclusive daily slicing, empty-window suppression,
chronological sorting, and Decimal cumulative linking moved into a dedicated period-preparation helper.
`calculate_benchmark_workflow` also dropped out after initial synchronous registration, resolution,
identity persistence, response projection, and failure mapping moved into a dedicated lifecycle helper.
`_resolve_benchmark_id` also dropped out after exposure-context-specific assignment status and payload
validation moved into a dedicated assignment-response policy helper.
`_classification_labels_from_catalog_record` also dropped out after null filtering and string
normalization moved into a dedicated classification-label helper.
`build_calculation_supportability` and the intermediate state-policy helper also dropped out after
supportability precedence and degraded-source detection moved into dedicated policy helpers.
`_reconcile_stale_job_row` also dropped out after retry-exhaustion status, message, and completion
selection moved into a dedicated stale-job outcome policy.
`calculate_contribution_workflow` also dropped out after initial synchronous registration,
resolution, execution, and failure mapping moved into a dedicated lifecycle helper.
`_is_average_weight_shadow_cutover_candidate` also dropped out after exact clean-bookkeeping
qualification moved into a dedicated methodology helper.
`_calculate_position_total_return_pct` also dropped out after optional-position handling and
inclusive period valuation-point slicing moved into a dedicated preparation helper.
The durable JSON object and string-list loaders now share a single JSON decode/logging helper while
preserving their separate shape-validation policies. `load_json_string_list_or_default` then
dropped out after non-empty string-list payload qualification was split into a typed predicate;
`load_json_object_or_none` remains the first measured B-grade CC `6` candidate after object-payload
qualification was split into a typed predicate because absent, empty, invalid JSON, and non-object
fallback policies still live in the public loader.
`record_upstream_snapshots` also dropped out after per-snapshot duplicate suppression, nested
insert, integrity-collision handling, and existing-id tracking were moved into a dedicated helper.
`_is_replay_of_existing_execution` also dropped out after durable execution replay identity was
centralized into stored/requested replay-signature helpers.
`_check_portfolio_daily_calculation_evidence` also dropped out after per-daily-breakdown
calculation-evidence row checking and mismatch finding projection were moved into a dedicated
helper.
`execute_runtime_retention_cleanup` also dropped out after runtime-retention execution identity and
history-policy assembly were moved into dedicated helpers while preserving evidence identity
normalization, settings defaults, explicit runtime overrides, cleanup execution, and persisted
evidence contract behavior.
`_persist_evidence_history` also dropped out after retained evidence-file discovery and
retention-limit pruning were moved into dedicated helpers while preserving latest/history writes,
age pruning, manifest rebuild inputs, and stale-file deletion behavior.
`_prune_old_evidence` also dropped out after evidence timestamp parsing and per-file stale-pruning
policy were moved into dedicated helpers while preserving disabled policy behavior, control-file
preservation, malformed-payload warning semantics, and stale-file deletion.
`_validate_manifest_entry` also dropped out after validated runtime-retention manifest-entry
projection was moved into a dedicated helper while preserving required string validation,
trigger-mode defaulting, integer metric validation, optional identity fields, and payload shape.
`run_runtime_retention_cleanup` also dropped out after manual replay result projection and governed
lease-target construction were moved into dedicated helpers while preserving replay-before-guard
ordering, manual guard enforcement, lease metadata, execution, and response behavior.
`build_recovery_drill_status` also dropped out after recovery-drill history snapshot projection was
moved into a dedicated helper while preserving missing-artifact degradation, unavailable-history
projection, latest-entry freshness evaluation, active-run evidence, and degradation detail
assembly.
`build_runtime_retention_status` also dropped out after runtime-retention history snapshot
projection was moved into a dedicated helper while preserving missing-artifact degradation,
unavailable-history projection, latest-entry freshness evaluation, active-run evidence, preview
summary fields, and degradation detail assembly.
`_record_source_quality_observation` also dropped out after source-quality date/value recording was
moved into a dedicated helper while preserving source classification counting, missing-field skip
behavior, invalid numeric/date skip behavior, normalized-date recording, and per-date market-value
conflict evidence.
`retrieve_stateful_attribution_source_input` also dropped out after requested upstream attribution
dimension selection was moved into a dedicated helper while preserving explicit dimension requests,
supported upstream `group_by` expansion, duplicate suppression, deterministic ordering, and
non-upstream grouping exclusion.
`_resolve_stateful_attribution_benchmark_id` also dropped out after assignment-payload
benchmark-id validation was moved into a dedicated helper while preserving override precedence,
assignment 404 mapping, upstream failure mapping, missing-id service-unavailable behavior, and
assigned benchmark identity projection.
`_sum_internal_cash_flow_abs_in_alignment_basis` also dropped out after per-flow internal cash-flow
amount projection was moved into a dedicated helper while preserving non-list and non-dict
suppression, missing-amount suppression, internal-only taxonomy filtering, conversion-factor
application, and absolute amount aggregation.
`_classified_component_count` also dropped out after required classification-label qualification
was moved into a shared predicate while preserving missing index suppression, missing/blank/non-string
label rejection, complete-label counting, and the same required-dimension policy used by position
classification.
`_build_benchmark_groups` also dropped out after benchmark group response projection was moved into
a dedicated helper while preserving empty-observation validation, benchmark return calculation,
classification-label lookup, grouped bucket aggregation, deterministic key/date ordering, and
per-date return projection.
`_position_row_to_base_weight_point` also dropped out after beginning market-value and value-basis
selection was moved into a dedicated helper while preserving valuation-date eligibility,
reporting-currency preference, reporting-to-portfolio fallback, portfolio-mode behavior, BOD
cash-flow conversion basis, and base-weight point projection.
`_position_meta_from_row` also dropped out after position identity/currency metadata projection was
moved into a dedicated helper with reusable non-empty group-value normalization while preserving
security id retention, currency normalization, empty/non-string currency suppression, FX metadata,
and dimension metadata merging.
`_validate_stateful_both_currency_support` in stateful attribution also dropped out after
non-reporting-currency FX requirement detection was moved into a dedicated predicate while
preserving missing report currency rejection, missing position currency rejection, same-currency
suppression, and mixed-currency FX requirement behavior.
`_benchmark_return_points_from_payload` also dropped out after single-point return-series projection
was moved into a dedicated helper while preserving malformed point suppression, missing date/return
suppression, ISO date parsing, and float return projection.
`_parse_composition_segment` also dropped out after required composition-segment field projection
was moved into a dedicated helper while preserving required-field error detail, date parsing,
window-overlap filtering, segment weight Decimal conversion, and segment model projection.
`_fx_rate_map_from_payload` also dropped out after single-point FX rate projection was moved into
a dedicated helper while preserving missing points-list rejection, malformed point suppression,
missing date/rate suppression, ISO date parsing, and Decimal FX-rate projection.
`_normalized_component_price_point_from_payload` also dropped out after component price point
date-scope resolution was moved into a dedicated helper while preserving malformed point
suppression, missing date suppression, prior-day allowance, end-date cutoff, missing price
rejection, FX normalization, and requested-date classification.
`_validate_stateful_both_currency_support` in stateful contribution also dropped out after
non-reporting-currency FX requirement detection was moved into a dedicated predicate while
preserving missing report currency rejection, missing position currency rejection, same-currency
suppression, and mixed-currency FX requirement behavior.
`Periods` also dropped out after conditional period definition requirements were moved into a
dedicated issue selector with direct coverage for non-conditional period types.
`_workspace_period_start_date` also dropped out after direct explicit, since-inception, and YTD
start-date policies were moved into a dedicated helper with direct coverage for fixed-lookback
fallback behavior.
`_build_instrument_attribution_panel` also dropped out after instrument beginning-capital selection
was moved into a dedicated helper with direct coverage for explicit base-weight points and engine
capital fallback behavior.
`_build_instrument_attribution_groups` also dropped out after group-key projection and observation
record projection were routed through dedicated helpers with direct coverage for exported
instrument group observations.
`_prepare_panel_from_groups` also dropped out after attribution group observation traversal was
moved into a dedicated helper with direct coverage for multi-key group observation projection.
`_determine_attribution_supportability_status` also dropped out after attribution coverage-gap
detection was moved into a dedicated predicate with direct status-precedence coverage.
`_component_contributions_dataframe` also dropped out after benchmark component observation record
projection was moved into a dedicated helper with direct coverage for base-only and local/FX fields.
`_blocked_composite_period_result_for_invalid_ready_facts` also dropped out after invalid ready-fact
blocking was routed through ordered, named policy helpers with direct no-ready precedence coverage.
`_composite_calculation_status` also dropped out after all-ready and calculated-period status
predicates were separated with direct coverage for ready, degraded, and blocked aggregate outcomes.
`calculate_asset_weighted_composite_twr` also dropped out after blocked-vs-ready period
calculation was moved into a dedicated helper with direct blocked and ready period coverage.
`_extract_policy_inputs` also dropped out after data-policy payload projection and ignored-date
flattening were split into dedicated helpers with direct coverage for missing policies, missing
payload sections, and projected override/ignore-day sections.
`_apply_overrides` also dropped out after market-value and cash-flow override group application
were routed through a shared helper with direct coverage for matching-field counts and no-match
suppression.
`_flag_outliers` also dropped out after outlier policy eligibility and window/MAD parameter
projection were isolated with direct coverage for enabled FLAG policy projection, non-FLAG
suppression, and default parameter selection.
`_apply_hedging_to_fx_return` also dropped out after ratio-hedge series eligibility and hedge-ratio
date mapping were isolated with direct coverage for configured ratio-series projection,
missing-date zero hedge defaults, and no-hedge pass-through behavior.
`ReturnsWindow` also dropped out after legacy relative-period alias normalization moved into a
dedicated helper with direct coverage for canonical aliases, already-canonical periods, non-string
period values, and non-dict validator input.
`_validate_returns_series_stateless_benchmark_override` also dropped out after stateless benchmark
override issue selection was split from validation raising and stateful-mode suppression, with
direct coverage for stateful benchmark override allowance, default stateless allowance, benchmark-id
rejection, and vendor-series source rejection.
`_validate_vendor_series_stateless_twr_benchmark_payload` also dropped out after vendor-series
stateless benchmark payload issue selection was split from validation raising, with direct coverage
for missing benchmark returns, component-observation rejection, component-price rejection, and valid
vendor-series payload acceptance.
`_validate_stateless_twr_benchmark_payloads` also dropped out after stateless TWR benchmark envelope
issue selection was split from calculated/vendor payload dispatch, with direct coverage for missing
stateless input, stateful-input conflict priority, missing benchmark-id rejection, and valid
stateless benchmark envelope acceptance.
`_stateless_twr_envelope_issue` also dropped out after invalid-shape message selection was split
from exact-one stateless TWR payload eligibility, with direct coverage for ambiguous and missing
payload messages.
`_workspace_summary_stateless_envelope_issue` also dropped out after invalid-shape message selection
was split from exact-one workspace-summary payload eligibility, with direct coverage for ambiguous
and missing payload messages.
`_bounded_mwr_solver_outcome_labels` also dropped out after reusable metric-label cardinality
bounding was extracted, with direct coverage for allowed label preservation and unsafe value
collapse.
`resolve_trace_id` also dropped out after traceparent parsing was split from trace-id precedence and
fallback resolution, with direct coverage for valid, missing, malformed, and short traceparent
values.
`propagation_headers` also dropped out after propagation header identity resolution was split from
header-envelope assembly, with direct coverage for override, context, request-id, and trace-id
fallback behavior.
`_included_router_route_name` also dropped out after matched route-name resolution was split from
included-router route scanning, with direct coverage for full-match and partial-match route
candidates.
`_infer_example` also dropped out after schema-hint example selection was split from named-key and
semantic fallback selection, with direct coverage for enum, typed, formatted, and no-hint
branches.
`_explicit_schema_example` also dropped out after list-valued explicit example selection was split
from direct `example` and named-example selection, with direct coverage for non-empty, empty, and
non-list `examples` values.
`_named_schema_example` also dropped out after named example value extraction was split from
named-example map validation, with direct coverage for value-bearing, missing-value, and non-dict
entries.
`_composed_schema_example` also dropped out after composed-schema first-variant selection and
dict-variant validation were split from composed example building, with direct coverage for `oneOf`,
`anyOf`, empty, non-list, and non-dict variant inputs.
`_build_schema_example` also dropped out after non-reference schema example selection was split from
`$ref` handling, with direct coverage for explicit, derived, and inferred fallback examples.
`_validation_error_json_content` also dropped out after authored JSON example detection was split
from HTTP validation-error schema selection, with direct coverage for singular `example`, plural
`examples`, and undocumented content.
`_request_body_example` also dropped out after operation-specific request example lookup was split
from authored-example suppression and schema fallback building, with direct coverage for override
copy semantics and missing override behavior.
`_ensure_json_success_response_example` also dropped out after operation response override lookup
and response schema fallback example building were split from success-response example assignment,
with direct coverage for override copy behavior, authored example preservation, invalid schema
suppression, and semantic schema fallback values.
`_ensure_operation_response_documentation` also dropped out after success-response iteration and
response-shape filtering were split from error defaulting and response documentation enrichment,
with direct coverage for success status-code selection, numeric response codes, and non-dict
response suppression.
`_ensure_operation_metadata` also dropped out after operation description resolution was split from
summary and tag assignment, with direct coverage for default descriptions, existing descriptions,
and the metrics-specific Prometheus description override.
`_iter_documentable_operations` also dropped out after path/method traversal was split from
documentable operation eligibility, with direct coverage for malformed path entries, method maps,
and non-dict operation candidates.
`_ensure_operation_documentation` also dropped out after per-operation metadata/request/response
enrichment was split from top-level OpenAPI paths traversal, with direct coverage for metadata,
request-body example enrichment, and response default enrichment on a single documentable operation.
`_ensure_schema_documentation` also dropped out after component/schema-map resolution and model
schema iteration were split from schema documentation dispatch, with direct coverage for malformed
component shapes, malformed schema maps, non-dict schema entries, and problem-detail schema
insertion.
`_ensure_model_schema_documentation` also dropped out after model-level schema metadata enrichment
was split from property-documentation dispatch, with direct coverage for generated descriptions,
generated enum descriptions, authored metadata preservation, and non-enum schemas.
`_ensure_property_schema_documentation` also dropped out after property example assignment was split
from property description, vocabulary, and enum-description enrichment, with direct coverage for
authored singular examples, authored plural examples, and generated schema fallback examples.
`_resolve_compute_job_result` also dropped out after missing compute-job validation was split into a
dedicated guard helper, with direct coverage for retained jobs and missing-job 404 behavior.
`_async_result_record_payload_state` also dropped out after invalid stored-payload detection was
split into a dedicated predicate, with direct coverage for source JSON with missing loaded payload,
valid loaded payloads, and absent source JSON.
`build_attribution_execution_window` also dropped out after optional source/benchmark metadata
projection was split into a dedicated helper, with direct coverage for absent optional metadata,
present optional metadata, and public execution-window merge behavior.
`calculate_attribution_workflow` also dropped out after sync execution registration and
resolution/error mapping were split into dedicated workflow-stage helpers, with direct coverage for
sync fencing payload projection and resolved attribution response delegation.
`_portfolio_group_observation_dates` also dropped out after portfolio-group observation iteration
and per-observation date qualification were split into dedicated helpers, with direct coverage for
missing and empty date suppression.
`_build_attribution_results_by_period` also dropped out after single-period attribution response
assembly and period-lineage recording were split into dedicated helpers, with direct coverage for
empty-slice suppression before aggregation.
`_resolve_attribution_execution_window` also dropped out after master-window date projection and
master request copying were split into a dedicated helper, with direct coverage for copied request
date projection.
`calculate_attribution` also dropped out after failure recording and HTTP exception mapping were
split into dedicated helpers, with direct coverage for engine, validation, existing HTTP, and
unexpected failure mapping.
`_calculate_promoted_stateful_contribution` also dropped out after promoted sync-start preparation
and resolved response calculation were split into dedicated workflow-stage helpers, with direct
coverage for replay suppression of sync registration and first-run sync registration metadata.
`_calculate_position_flow_balance_counts` also dropped out after daily cash-flow source eligibility
and missing-portfolio-flow fallback counting were split into dedicated helpers, with direct coverage
for residual-day-only fallback output.
`_classify_average_weight_methodology_status` also dropped out after material-period status
precedence was split from non-material shadow detection, with direct coverage for promoted status
winning over blocker reason codes once materiality is established.
`_has_clean_average_weight_shadow_bookkeeping` also dropped out after reset-alignment cleanliness
was split into a dedicated helper and the remaining guardrail checks were expressed as an explicit
`all(...)` checklist, with direct coverage for both reset-mismatch directions.
`_calculate_reset_aware_period_portfolio_return` also dropped out after portfolio and position
period engine return calculation were routed through a shared period engine helper, with direct
coverage for result scaling, period-type projection, and base-only execution for currency mode
`BOTH`.
`_build_residual_adjusted_position_timeseries` also dropped out after residual-adjusted target
total projection was split into a dedicated helper, with direct coverage for percentage-point to
ratio conversion before residual allocation.
`_build_residual_adjusted_daily_contribution_series` also dropped out after residual-adjusted daily
total aggregation was split into a dedicated helper, with direct coverage for multi-position
same-day aggregation and negative contribution preservation before sorted response projection.
`_build_hierarchy_from_adjusted_position_series` also dropped out after hierarchy eligibility was
split into a dedicated guard helper, with direct coverage for hierarchy, period-row, and adjusted
position-series prerequisites.
`_daily_hierarchy_metadata` also dropped out after hierarchy metadata column selection was split
into a dedicated helper, with direct coverage for base metadata preservation and duplicate
hierarchy-level suppression.
`_collect_position_continuity_gap_samples` also dropped out after per-position adjacent-row pairing
was moved into a dedicated iterator, with direct coverage for date ordering, invalid-row
suppression, and multi-position continuity-gap sample projection.
`_build_position_continuity_gap_sample` also dropped out after material gap qualification,
tolerance suppression, transition-activity suppression, gap percentage calculation, and sample
payload projection were split into focused helpers with direct policy coverage.
`_collect_duplicate_snapshot_samples` also dropped out after duplicate-count state tracking and
sample payload projection were split from the collector, with direct coverage for invalid-row
suppression and duplicate-count updates beyond two rows.
`record_taxonomy_signal` also dropped out after missing/canonical taxonomy predicates and taxonomy
sample-row projection were split from accumulator mutation, with direct coverage for missing,
canonical, governed-alias, and unsupported cash-flow type classifications.
`add_amount` also dropped out after unsupported suppression, fee timing accumulation, beginning-of-day
fee timing sample projection, and external amount routing were split into focused accumulator
helpers with direct coverage for fee BOD/EOD routing, unsupported suppression, and current non-fee
external bucket behavior.
`_collect_noncanonical_cashflow_types` also dropped out after per-sample cash-flow type extraction
and string-value qualification were split into a focused helper with direct coverage for invalid
sample shapes, non-string suppression, de-duplication, and sorted artifact output.
`_resolve_observation_valuation_date` also dropped out after ISO date qualification and invalid
observation-date sample projection were split into focused helpers with direct coverage for valid
ISO strings, invalid strings, non-string values, and missing valuation-date samples.
`_record_detailed_cash_flow` also dropped out after detailed cash-flow row qualification was split
from taxonomy/economics routing with direct coverage for normalized row qualification and invalid
amount evidence. The extracted row qualifier remains a top CC `5` candidate for a future narrower
shape-sampling cleanup.
`_qualified_detailed_cash_flow_row` also dropped out after cash-flow timing normalization and
supported BOD/EOD timing qualification were split into focused helpers with direct coverage for
trimmed string timing, non-string preservation, and supported-timing checks.
`_sample_raw_collection_value` also dropped out after scalar sample qualification was isolated into
a focused helper with direct coverage for string, boolean, numeric, `None`, dict, and non-scalar
fallback behavior.
The source-quality economic plausibility finding extraction did not change the max cyclomatic
complexity posture; the measured repository maximum remains `5`.
LP-CR-1437 isolated TWR inspection support-brief response projection into a focused helper.
`_build_twr_inspection_response(...)` dropped out of the top-25 complexity table, while the
measured repository maximum remains `5` and high-complexity functions remain `0`.
LP-CR-1438 isolated portfolio timeseries page retrieval and request-payload projection into
`StatefulInputService._fetch_portfolio_timeseries_page(...)`. The measured repository maximum
remains `5`, high-complexity functions remain `0`, and average maintainability index remains
`55.08`.
LP-CR-1446 isolated runtime-retention history query metadata from dependency assembly. The measured
repository maximum remains `5`, high-complexity functions remain `0`, and average maintainability
index measures `54.88`.
The runtime work-item safe listing extraction did not change the max cyclomatic complexity posture;
the measured repository maximum remains `5`.
The stateful timeseries snapshot append extraction did not change the max cyclomatic complexity
posture; the measured repository maximum remains `5`.
The runtime-retention lease/execution extraction did not change the max cyclomatic complexity
posture; the measured repository maximum remains `5`.
The integration-capability feature publication extraction did not change the max cyclomatic
complexity posture; the measured repository maximum remains `5`.
The remaining C-grade
hotspots should be treated as future bounded refactor candidates, not as evidence of an immediate
behavior defect.
LP-CR-1406 removed the recovery-drill/runtime-retention unavailable snapshot duplicate builder
through a shared operator-action history snapshot helper. The measured max cyclomatic complexity
remains `5`, high-complexity functions remain `0`, and average maintainability index moved from
`54.96` to `55.14`.
LP-CR-1407 removed the final duplicate function-body hotspot by centralizing attribute-backed
queue metric sample projection. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.13`.
LP-CR-1408 isolated durable queue metric descriptor metadata from the Prometheus collector
`describe` method. The measured max cyclomatic complexity remains `5`, high-complexity functions
remain `0`, and average maintainability index measured `55.14`.
LP-CR-1409 isolated runtime-status operator-action reclaim event projection from the public
runtime-status response mapper. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.14`.
LP-CR-1411 isolated runtime-status degradation policy response projection from the public
runtime-status response mapper. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.14`.
LP-CR-1412 isolated contribution period supportability evidence assembly from the flat and
hierarchy contribution period result builders. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.13`.
LP-CR-1447 isolated contribution diagnostics candidate canonical reset counting from the portfolio
engine diagnostics mapper. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `54.87`.
LP-CR-1448 isolated contribution calculation execution from response assembly and lineage
completion. The measured max cyclomatic complexity remains `5`, high-complexity functions remain
`0`, and average maintainability index measured `54.87`.
LP-CR-1452 isolated recovery-drill run orchestration from the API route while sharing operator-run
evidence response projection with runtime retention. The measured max cyclomatic complexity remains
`5`, high-complexity functions remain `0`, and average maintainability index measured `55.17`.
LP-CR-1454 isolated completed benchmark response assembly and benchmark lineage completion from the
public benchmark calculation orchestrator. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.16`.
LP-CR-1455 isolated shared contribution period response projection from the flat and hierarchy
period builders. The measured max cyclomatic complexity remains `5`, high-complexity functions
remain `0`, and average maintainability index measured `55.16`.
LP-CR-1456 isolated stateful MWR identity resolution and MWR lineage completion from the public MWR
calculation orchestrator. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `55.15`.
LP-CR-1457 isolated normalized stateful returns-series benchmark source construction from the
public benchmark-source resolver. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.15`.
LP-CR-1458 isolated stateful attribution portfolio, position, and benchmark source retrieval from
the public attribution source-input retriever. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.15`.
LP-CR-1459 isolated stateful portfolio chunk page accumulation from the paginated chunk fetcher.
The measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`, and
average maintainability index measured `55.15`.
LP-CR-1460 isolated MWR response supportability construction, solver/supportability metric
emission, and endpoint payload projection from the public MWR response builder. The measured max
cyclomatic complexity remains `5`, high-complexity functions remain `0`, and average
maintainability index measured `55.15`.
LP-CR-1461 isolated workspace-summary single-period response assembly from the period-results
mapper. The measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`,
and average maintainability index measured `55.15`.
LP-CR-1462 isolated stale-job reconciliation and single leased-job execution/persistence from the
compute worker polling path. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `55.15`.
LP-CR-1463 isolated reset-aware average-weight rollout note specification from positive-count
filtering. The measured max cyclomatic complexity remains `5`, high-complexity functions remain
`0`, and average maintainability index measured `55.15`.
LP-CR-1464 isolated source-economics artifact payload section projection from the aggregate
artifact payload builder. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `55.15`.
LP-CR-1465 isolated resolved promoted stateful returns-series execution-window and payload
projection from the promoted workflow helper. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `55.15`.
LP-CR-1466 isolated stateful position chunk row/page accumulation from the paginated position chunk
fetcher. The measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`,
and average maintainability index measured `55.15`.
LP-CR-1467 isolated workspace summary metadata projection from the response assembly helper. The
measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`, and average
maintainability index measured `55.15`.
LP-CR-1469 isolated stateless contribution request envelope projection from the contribution mode
resolver. The measured max cyclomatic complexity remains `5`, high-complexity functions remain
`0`, and average maintainability index measured `55.14`.
LP-CR-1470 isolated contribution average-weight shadow audit observation from the flat and
hierarchy period builders. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `55.14`.
LP-CR-1471 isolated available runtime work-item snapshot assembly from the durable metadata-ready
path. The measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`,
and average maintainability index measured `55.14`.
LP-CR-1472 isolated runtime-recoveries query metadata from the FastAPI dependency signature. The
measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`, and average
maintainability index measured `54.97`.
LP-CR-1473 isolated shared contribution period frame, methodology-context, and average-weight audit
preparation from the flat and hierarchy contribution period builders. The measured max cyclomatic
complexity remains `5`, high-complexity functions remain `0`, and average maintainability index
measured `54.97`.
LP-CR-1474 isolated promoted stateful benchmark finalization from the promoted benchmark workflow.
The measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`, and
average maintainability index measured `54.97`.
LP-CR-1475 isolated source-quality evidence-context assessment from the source-quality check
orchestrator. The measured max cyclomatic complexity remains `5`, high-complexity functions remain
`0`, and average maintainability index measured `54.97`.
LP-CR-1476 isolated resolved MWR engine execution and response assembly from the public MWR
calculation workflow. The measured max cyclomatic complexity remains `5`, high-complexity functions
remain `0`, and average maintainability index measured `54.96`.
LP-CR-1477 isolated stateless MWR resolution, stateful source retrieval, stateful normalization,
and resolved stateful request projection from the public MWR mode resolver. The measured max
cyclomatic complexity remains `5`, high-complexity functions remain `0`, and average
maintainability index measured `54.96`.
LP-CR-1478 isolated runtime-retention manifest read, validation, invalid-manifest logging, and
unavailable snapshot projection from the public runtime-retention history snapshot builder. The
measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`, and average
maintainability index measured `54.95`.
LP-CR-1479 isolated stateful position chunk response projection from the paginated position
chunk retrieval path. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `54.95`.
LP-CR-1480 isolated stateless and resolved stateful attribution request projection from the public
attribution mode resolver. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `54.95`.
LP-CR-1481 isolated lineage pending-payload stats predicates from the stats and inspection query
builders. The measured max cyclomatic complexity remains `5`, high-complexity functions remain
`0`, and average maintainability index measured `54.95`.
LP-CR-1482 isolated source-economics flow-date, cash-flow quality, and cash-flow taxonomy sample
recording from the taxonomy-sample collector orchestrator. The measured max cyclomatic complexity
remains `5`, high-complexity functions remain `0`, and average maintainability index measured
`54.94`.
LP-CR-1483 isolated governed operator-action lease metric source loading from the durable queue
metric source loader. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `54.94`.
LP-CR-1484 isolated stateful returns-series portfolio, benchmark, and risk-free source retrieval
from the public stateful returns-series resolver. The measured max cyclomatic complexity remains
`5`, high-complexity functions remain `0`, and average maintainability index measured `54.94`.
LP-CR-1485 isolated stateful attribution normalization input policy validation from the stateful
attribution input builder. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `54.94`.
LP-CR-1486 isolated attribution panel resampling and linked-return projection from the attribution
alignment orchestrator. The measured max cyclomatic complexity remains `5`, high-complexity
functions remain `0`, and average maintainability index measured `54.94`.
LP-CR-1487 isolated stateful contribution source retrieval, normalization, and resolved-request
projection from the contribution input-mode resolver. The measured max cyclomatic complexity
remains `5`, high-complexity functions remain `0`, and average maintainability index measured
`54.93`.
LP-CR-1488 isolated no-contribution-row smoothing evidence projection from the contribution
smoothing evidence builder. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `54.93`.
LP-CR-1489 isolated retained-calculation TWR inspection input materialization from the subject
inspection input resolver. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `54.93`.
LP-CR-1490 isolated MWR execution registration and initial identity materialization from the public
MWR calculation workflow. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `54.93`.
LP-CR-1491 isolated stateful MWR market-value evidence projection from the stateful MWR input
builder. The measured max cyclomatic complexity remains `5`, high-complexity functions remain `0`,
and average maintainability index measured `54.93`.
LP-CR-1492 isolated benchmark market-series retrieval and component-series response mapping from
the benchmark exposure context builder. The measured max cyclomatic complexity remains `5`,
high-complexity functions remain `0`, and average maintainability index measured `54.92`.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

The max cyclomatic complexity and rank D-F function-count posture is now a blocking CI gate through
`make quality-complexity-gate`. The gate currently enforces max CC `8` and D-F count `0`; the
measured repository maximum is now `5`.
Maintainability index remains report-only until a stable threshold, exception policy, and
remediation workflow exist.
