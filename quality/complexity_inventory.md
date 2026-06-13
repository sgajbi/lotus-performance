# Lotus Performance Complexity Inventory

Report date: 2026-06-13
Branch: `refactor/lp-cr-950-mwr-fx-component`
Mode: measured complexity and maintainability inventory; max CC and D-F count are enforced by CI.

## Purpose

This report captures the current cyclomatic complexity and maintainability posture for production
Python paths. It gives the hardening stream repeatable evidence for hotspot selection and backs the
current complexity regression gate. Maintainability index remains report-only until a stable
threshold and exception policy exist.

## Command

```powershell
python scripts/python_complexity_inventory.py --limit 25
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
| Max cyclomatic complexity | 7 |
| High-complexity functions (rank D-F) | 0 |
| Average maintainability index | 55.14 |

## Highest Cyclomatic Complexity

| Rank | Symbol | Type | File | CC | Grade |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `_comparative_return_mismatches` | function | `app/services/inspection/calculation_consistency.py:695` | 7 | B |
| 2 | `_build_position_reconciliation_findings` | function | `app/services/inspection/reconciliation.py:143` | 7 | B |
| 3 | `_select_latest_position_rows` | function | `app/services/inspection/reconciliation.py:431` | 7 | B |
| 4 | `_record_external_mixed_timing_samples` | method | `app/services/inspection/source_economics_collector.py:300` | 7 | B |
| 5 | `_record_external_timing_contradictions` | function | `app/services/inspection/source_economics_collector.py:462` | 7 | B |
| 6 | `_build_external_cashflow_findings` | function | `app/services/inspection/source_economics_findings.py:281` | 7 | B |
| 7 | `_build_fee_source_economics_findings` | function | `app/services/inspection/source_economics_findings.py:423` | 7 | B |
| 8 | `_find_monthly_day_dominance` | function | `app/services/inspection/source_quality.py:576` | 7 | B |
| 9 | `load_existing_twr_calculation_artifacts` | function | `app/services/inspection/subject_materialization.py:34` | 7 | B |
| 10 | `_load_request_payload` | function | `app/services/inspection/subject_materialization.py:109` | 7 | B |
| 11 | `_support_brief_result_from_payload` | function | `app/services/inspection/support_brief_workflow_pack.py:55` | 7 | B |
| 12 | `run_twr_inspection` | function | `app/services/inspection/twr_inspection_service.py:88` | 7 | B |
| 13 | `_synthesize_verdict` | function | `app/services/inspection/twr_inspection_service.py:551` | 7 | B |
| 14 | `_scope_request_to_response_master_window` | function | `app/services/inspection/twr_inspection_service.py:652` | 7 | B |
| 15 | `get_pending_payload_stats` | method | `app/services/lineage_metadata_store.py:416` | 7 | B |
| 16 | `list_inspection_items` | method | `app/services/lineage_metadata_store.py:507` | 7 | B |
| 17 | `materialize_payload` | method | `app/services/lineage_service.py:72` | 7 | B |
| 18 | `_validate_artifact_filename` | method | `app/services/lineage_service.py:171` | 7 | B |
| 19 | `build_mwr_response` | function | `app/services/mwr_calculation_service.py:42` | 7 | B |
| 20 | `_find_latest_runtime_retention_entry` | function | `app/services/operator_action_guard_service.py:128` | 7 | B |
| 21 | `validate_history_entry_strings` | function | `app/services/operator_action_history_manifest.py:173` | 7 | B |
| 22 | `build_operator_action_lease_snapshot` | function | `app/services/operator_action_lease_service.py:185` | 7 | B |
| 23 | `_read_matching_active_operator_action_leases` | function | `app/services/operator_action_lease_service.py:246` | 7 | B |
| 24 | `_active_lease_payload_fields` | function | `app/services/operator_action_lease_service.py:314` | 7 | B |
| 25 | `_read_recent_reclaimed_leases` | function | `app/services/operator_action_lease_service.py:389` | 7 | B |

## Lowest Maintainability Index

| Rank | File | MI | Grade |
| ---: | --- | ---: | --- |
| 1 | `app/services/compute_job_store.py` | 0.00 | C |
| 2 | `app/services/lineage_metadata_store.py` | 0.00 | C |
| 3 | `app/services/returns_series_service.py` | 0.00 | C |
| 4 | `app/services/stateful_attribution_input_service.py` | 0.00 | C |
| 5 | `app/services/stateful_input_service.py` | 0.00 | C |
| 6 | `app/openapi_enrichment.py` | 2.56 | C |
| 7 | `app/services/twr_service.py` | 6.19 | C |
| 8 | `app/services/workspace_summary_service.py` | 10.56 | B |
| 9 | `app/services/stateful_benchmark_input_service.py` | 10.70 | B |
| 10 | `app/services/execution_registry.py` | 10.72 | B |
| 11 | `engine/attribution.py` | 13.95 | B |
| 12 | `app/services/operator_action_lease_service.py` | 15.16 | B |
| 13 | `app/services/inspection/reconciliation.py` | 16.20 | B |
| 14 | `app/services/inspection/calculation_consistency.py` | 16.39 | B |
| 15 | `app/services/inspection/source_economics_collector.py` | 17.04 | B |
| 16 | `app/services/inspection/source_quality.py` | 17.21 | B |
| 17 | `app/services/inspection/source_economics.py` | 17.37 | B |
| 18 | `app/services/twr_mode_service.py` | 18.24 | B |
| 19 | `app/models/runtime_status.py` | 19.85 | A |
| 20 | `app/models/returns_series.py` | 20.36 | A |
| 21 | `app/services/inspection/twr_inspection_service.py` | 20.47 | A |
| 22 | `app/workers/compute_executor_worker.py` | 20.96 | A |
| 23 | `app/services/stateful_mwr_input_service.py` | 22.43 | A |
| 24 | `engine/composites.py` | 22.52 | A |
| 25 | `engine/mwr.py` | 23.00 | A |

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
The remaining C-grade
hotspots should be treated as future bounded refactor candidates, not as evidence of an immediate
behavior defect.

Maintainability index values should be treated as directional hotspot evidence because generated
schemas, persistence-style modules, and dense orchestration files can score poorly even when tests
are strong. Future slices should use this report to prioritize bounded extractions, characterization
tests, and module-boundary cleanup.

## Gate Posture

The max cyclomatic complexity and rank D-F function-count posture is now a blocking CI gate through
`make quality-complexity-gate`. The gate currently enforces max CC `8` and D-F count `0`.
Maintainability index remains report-only until a stable threshold, exception policy, and
remediation workflow exist.
