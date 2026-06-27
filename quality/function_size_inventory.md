# Lotus Performance Function Size Inventory

Report date: 2026-06-27
Branch: `feature/enterprise-backend-refactor-baseline`
Mode: report-only function-size inventory; this artifact introduces no new blocking CI gate.

## Purpose

This report captures the largest production Python functions by source-line span using a
repo-native standard-library script. It gives the refactor health scorecard a measured function-size
hotspot dimension without waiting for external complexity tooling such as `radon` or `xenon`.

## Command

```powershell
python scripts/python_function_size_inventory.py --limit 25
```

## Largest Production Functions

| Rank | Function | File | Lines |
| ---: | --- | --- | ---: |
| 1 | `build_stateful_mwr_input_for_window` | `app/services/stateful_mwr_input_service.py:112` | 62 |
| 2 | `build_benchmark_exposure_context` | `app/services/benchmark_exposure_context_service.py:39` | 61 |
| 3 | `_build_twr_inspection_response` | `app/services/inspection/twr_inspection_service.py:319` | 61 |
| 4 | `_run_subject_assessments` | `app/services/inspection/twr_inspection_service.py:157` | 61 |
| 5 | `LineageService.materialize_payload` | `app/services/lineage_service.py:72` | 61 |
| 6 | `StatefulInputService._fetch_portfolio_chunk` | `app/services/stateful_input_service.py:892` | 61 |
| 7 | `_calculate_dietz_mwr_result` | `engine/mwr.py:436` | 61 |
| 8 | `LineageMetadataStore.list_recent_recoveries` | `app/services/lineage_metadata_store.py:435` | 60 |
| 9 | `retrieve_stateful_portfolio_input` | `app/services/stateful_performance_input_service.py:42` | 60 |
| 10 | `resolve_twr_request` | `app/services/twr_mode_service.py:80` | 60 |
| 11 | `_build_workspace_summary_response` | `app/services/workspace_summary_service.py:547` | 60 |
| 12 | `_calculate_xirr_mwr_attempt` | `engine/mwr.py:355` | 60 |
| 13 | `get_recovery_drill_history` | `app/api/endpoints/recovery_drill_history.py:33` | 59 |
| 14 | `get_runtime_work_items` | `app/api/endpoints/runtime_work_items.py:25` | 59 |
| 15 | `ComputeJobStore._build_queue_stats_statement` | `app/services/compute_job_store.py:863` | 59 |
| 16 | `ComputeJobStore.list_recent_recoveries` | `app/services/compute_job_store.py:715` | 59 |
| 17 | `_build_stateful_calculated_benchmark_input` | `app/services/stateful_benchmark_input_service.py:94` | 59 |
| 18 | `_assemble_completed_twr_response` | `app/services/twr_service.py:1184` | 59 |
| 19 | `calculate_twr_response` | `app/services/twr_service.py:1245` | 59 |
| 20 | `build_attribution_supportability_evidence` | `engine/attribution_supportability.py:63` | 59 |
| 21 | `_build_portfolio_engine_diagnostics` | `app/services/contribution_diagnostics.py:79` | 58 |
| 22 | `_build_position_reconciliation_result` | `app/services/inspection/reconciliation.py:439` | 58 |
| 23 | `_lifecycle_history_metrics` | `app/services/queue_metrics_service.py:442` | 58 |
| 24 | `build_recovery_drill_history_snapshot` | `app/services/recovery_drill_history_service.py:66` | 58 |
| 25 | `execute_runtime_retention_cleanup` | `app/services/runtime_retention_execution_service.py:94` | 58 |

## Interpretation

This is not a cyclomatic-complexity score. It is a deterministic hotspot inventory for refactor
planning. The largest functions are concentrated in source-economics inspection, contribution,
reconciliation, runtime-status assembly, queue metrics, and returns-series execution. TWR workflow
assembly has dropped out of the top-15 table after resolved identity finalization was isolated.
Runtime-status response assembly remains in the top-15 table but moved from `173` to `131` lines
after lineage queue response mapping was isolated. Attribution orchestration remains in the top-15
table but moved from `142` to `133` lines after per-period result assembly was isolated, then moved
from `133` to `120` lines after response meta, supportability, and benchmark-context assembly were
isolated.
LP-CR-1436 isolated lineage inspection status-filter statement dispatch into a focused helper.
`LineageMetadataStore._build_inspection_query_statements(...)` dropped out of the top-25 table, and
the largest production functions are now `_build_twr_inspection_response(...)` and
`StatefulInputService._fetch_portfolio_chunk(...)` at `79` lines each.
LP-CR-1437 isolated TWR inspection support-brief generation, evidence projection, workflow-pack
run projection, and artifact-link refresh into `_attach_support_brief_to_inspection_response(...)`.
`_build_twr_inspection_response(...)` moved from `79` to `61` lines and dropped out of the top-25
table; the extracted helper measures `27` lines, and the largest production function is now
`StatefulInputService._fetch_portfolio_chunk(...)` at `79` lines.
LP-CR-1438 isolated portfolio timeseries page retrieval and request-payload projection into
`StatefulInputService._fetch_portfolio_timeseries_page(...)`, mirroring the existing position
timeseries page-helper boundary. `_fetch_portfolio_chunk(...)` moved from `79` to `71` lines, and
the largest production function is now `build_runtime_retention_history_snapshot(...)` at `78`
lines.
LP-CR-1439 isolated validated runtime-retention manifest projection into
`_available_runtime_retention_history_snapshot_from_manifest(...)`. The public
`build_runtime_retention_history_snapshot(...)` path now owns artifact-directory resolution,
applied-filter construction, manifest read, validation, and unavailable snapshots while the helper
owns entry projection, exact filters, time-window filters, pagination, and available snapshot
assembly. `build_runtime_retention_history_snapshot(...)` dropped out of the top-25 table; the
largest production functions are now `resolve_contribution_request(...)` and
`LineageMetadataStore._lease_pending_payloads_postgresql(...)` at `77` lines each.
LP-CR-1440 isolated contribution retrieval and normalization stage-detail projection into
`_contribution_retrieval_stage_details(...)` and
`_contribution_normalization_stage_details(...)`, mirroring the attribution resolver boundary.
`resolve_contribution_request(...)` moved from `77` to `67` lines and dropped out of the top-25
table; the extracted helpers measure `11` and `7` lines, and the largest production function is
now `LineageMetadataStore._lease_pending_payloads_postgresql(...)` at `77` lines.
LP-CR-1441 isolated PostgreSQL lineage payload lease SQL construction, parameter projection, and
returned-row projection into focused helpers. `_lease_pending_payloads_postgresql(...)` moved from
`77` to `26` lines and dropped out of the top-25 table; the extracted helpers measure `38`, `14`,
and `19` lines, and the largest production function is now
`_build_stateful_calculated_benchmark_input(...)` at `75` lines.
LP-CR-1442 isolated calculated benchmark composition-window loading and parsing into
`_load_calculated_benchmark_composition(...)`. `_build_stateful_calculated_benchmark_input(...)`
moved from `75` to `59` lines and dropped out of the top-25 table; the extracted helper measures
`32` lines, and the largest production functions are now six functions tied at `74` lines.
LP-CR-1443 isolated durable-metadata-unavailable runtime work-item snapshot assembly into
`_unavailable_runtime_work_item_snapshot(...)`. `build_runtime_work_item_snapshot(...)` moved from
`74` to `66` lines and dropped out of the top-25 table; the extracted helper measures `35` lines,
and the largest production functions are now five functions tied at `74` lines.
LP-CR-1444 isolated stateful attribution source-retrieval request projection into
`_retrieve_attribution_source_input(...)`. `resolve_attribution_request(...)` moved from `74` to
`64` lines and dropped out of the top-25 table; the extracted helper measures `25` lines, and the
largest production functions are now four functions tied at `74` lines.
LP-CR-1445 promoted repository hygiene into a blocking lint gate and added a tested cleanup utility.
It did not change production application modules, so the top-25 production function-size table
remains unchanged.
LP-CR-1446 isolated runtime-retention history FastAPI query metadata into named `TypeAlias`
boundaries while keeping UTC timestamp-window validation and query-parameter assembly in
`build_runtime_retention_history_query(...)`. The dependency dropped out of the top-25 table, and
the largest production functions are now three functions tied at `74` lines.
LP-CR-1447 isolated contribution diagnostics candidate canonical reset counting into a focused
helper. `_build_portfolio_engine_diagnostics(...)` dropped out of the top-25 table, and the largest
production functions are now `calculate_contribution(...)` and
`_build_workspace_benchmark_and_active_blocks(...)` at `74` lines each.
LP-CR-1448 isolated contribution calculation execution into `_run_contribution_calculation(...)`.
`calculate_contribution(...)` dropped out of the top-25 table, and the largest production function
is now `_build_workspace_benchmark_and_active_blocks(...)` at `74` lines.
LP-CR-1449 isolated workspace active-return projection into `_build_workspace_active_block(...)`
and `_build_workspace_active_return_summary(...)`. `_build_workspace_benchmark_and_active_blocks(...)`
dropped out of the top-25 table, and the largest production functions are now `calculate_attribution(...)`
and `_build_attribution_supportability_reasons(...)` at `73` lines each.
LP-CR-1450 isolated completed attribution response assembly and lineage completion into
`_build_completed_attribution_response(...)` and `_complete_attribution_execution(...)`.
`calculate_attribution(...)` dropped out of the top-25 table, and the largest production function is
now `_build_attribution_supportability_reasons(...)` at `73` lines.
LP-CR-1451 isolated count-based and status-based attribution supportability reason projection into
`_append_count_based_supportability_reasons(...)` and `_append_status_based_supportability_reasons(...)`.
`_build_attribution_supportability_reasons(...)` dropped out of the top-25 table, and the largest
production functions are now five functions tied at `72` lines.
LP-CR-1452 isolated governed recovery-drill run orchestration into
`run_governed_recovery_drill(...)`, added a transport-neutral `OperatorRequestContext`, and shared
operator-run evidence response projection across recovery drill and runtime retention. The
`run_recovery_drill(...)` API route dropped out of the top-25 table, duplicate hotspots remain `0`,
and the largest production functions are now four functions tied at `72` lines.
LP-CR-1454 isolated completed benchmark response assembly and lineage completion into
`_build_completed_benchmark_response(...)` and `_complete_benchmark_execution(...)`.
`calculate_benchmark_response(...)` dropped out of the top-25 table, duplicate hotspots remain `0`,
and the largest production functions are now three functions tied at `72` lines.
LP-CR-1455 isolated shared contribution period response projection into
`_build_contribution_period_result(...)`. `_build_flat_period_contribution_result(...)` moved from
`72` to `67` lines, `_build_hierarchy_period_contribution_result(...)` moved from `70` to `64`
lines, duplicate hotspots remain `0`, and the largest production functions are now two functions
tied at `72` lines.
LP-CR-1456 isolated stateful MWR identity resolution and MWR lineage completion into
`_resolve_mwr_execution_request(...)` and `_complete_mwr_execution(...)`.
`calculate_mwr_response(...)` moved from `72` to `65` lines, duplicate hotspots remain `0`, and the
largest production function is now `_resolve_stateful_returns_series_benchmark_source(...)` at `72`
lines.
LP-CR-1457 isolated normalized stateful returns-series benchmark source construction into
`_resolve_stateful_normalized_benchmark_source(...)`. The public benchmark-source resolver moved
from `72` to `44` lines, the extracted helper measures `43` lines, duplicate hotspots remain `0`,
and the largest production functions are now `retrieve_stateful_attribution_source_input(...)` and
`StatefulInputService._fetch_portfolio_chunk(...)` at `71` lines each.
LP-CR-1458 isolated stateful attribution portfolio, position, and benchmark retrieval into
`_retrieve_stateful_attribution_sources(...)`. The public attribution source-input retriever moved
from `71` to `49` lines, the extracted helper measures `55` lines, duplicate hotspots remain `0`,
and the largest production function is now `StatefulInputService._fetch_portfolio_chunk(...)` at
`71` lines.
LP-CR-1459 isolated stateful portfolio chunk page accumulation into
`_PortfolioChunkAccumulator` and `_record_portfolio_chunk_payload(...)`.
`StatefulInputService._fetch_portfolio_chunk(...)` moved from `71` to `61` lines, the extracted
helper measures `17` lines, duplicate hotspots remain `0`, and the largest production functions are
now three functions tied at `70` lines.
LP-CR-1460 isolated MWR response supportability construction, solver/supportability metric
emission, and endpoint payload projection into focused helpers. `build_mwr_response(...)` dropped
out of the top-25 table, duplicate hotspots remain `0`, and the largest production functions are
now `_build_workspace_results_by_period(...)` and `_process_pending_jobs(...)` at `70` lines each.
LP-CR-1461 isolated workspace-summary single-period response assembly into
`_build_workspace_period_summary_result(...)`. `_build_workspace_results_by_period(...)` dropped
out of the top-25 table, duplicate hotspots remain `0`, and the largest production function is now
`_process_pending_jobs(...)` at `70` lines.
LP-CR-1462 isolated stale-job reconciliation and single leased-job execution/persistence from
`_process_pending_jobs(...)`. The public worker polling path now focuses on runtime construction,
queue leasing, and processed-count accounting while focused helpers own stale reconciliation and
per-job mark-running, execution, result persistence, completion, and failure routing.
`_process_pending_jobs(...)` dropped out of the top-25 table, duplicate hotspots remain `0`, and the
largest production functions now measure `69` lines.
LP-CR-1463 isolated reset-aware average-weight rollout note specifications from positive-count note
filtering. `AverageWeightShadowAuditState._rollout_posture_notes(...)` dropped out of the top-25
table, duplicate hotspots remain `0`, and the largest production functions continue to measure `69`
lines.
LP-CR-1464 isolated source-economics artifact payload sections into observation-date, fee
cash-flow, external cash-flow, raw cash-flow quality, and cash-flow taxonomy helpers, with a shared
counted-sample projection helper for repeated sample fields. `_build_artifact_payload(...)` dropped
out of the top-25 table, duplicate hotspots remain `0`, and the largest production function is now
`_calculate_promoted_stateful_returns_series(...)` at `69` lines.
LP-CR-1465 isolated resolved promoted stateful returns-series execution-window projection, async
request-payload projection, and finalization dispatch into focused helpers. The promoted stateful
workflow helper dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest
production functions now measure `68` lines.
LP-CR-1466 isolated stateful position chunk row and page-count accumulation into
`_PositionChunkAccumulator` and `_record_position_chunk_payload(...)`, mirroring the portfolio
chunk accumulation boundary. `StatefulInputService._fetch_position_chunk(...)` moved from `68` to
`65` lines, duplicate hotspots remain `0`, and the largest production function is now
`_build_workspace_summary_response(...)` at `68` lines.
LP-CR-1467 isolated workspace summary response metadata projection into
`_workspace_summary_meta(...)`. `_build_workspace_summary_response(...)` dropped out of the top-25
table, duplicate hotspots remain `0`, and the largest production functions now measure `67` lines.
LP-CR-1468 isolated benchmark exposure response metadata projection into
`_benchmark_exposure_metadata(...)`. `build_benchmark_exposure_context(...)` moved from `67` to
`61` lines, duplicate hotspots remain `0`, and the largest production functions continue to
measure `67` lines.
LP-CR-1469 isolated stateless contribution resolution envelope projection into
`_resolved_stateless_contribution_request(...)`. `resolve_contribution_request(...)` moved from
`67` to `62` lines, duplicate hotspots remain `0`, and the largest production function is now
`_build_flat_period_contribution_result(...)` at `67` lines.
LP-CR-1470 isolated reset-aware average-weight shadow audit observation into
`_record_average_weight_shadow_observation(...)`, shared by flat and hierarchy contribution period
builders. `_build_flat_period_contribution_result(...)` moved from `67` to `66` lines,
`_build_hierarchy_period_contribution_result(...)` moved from `64` to `63` lines, duplicate
hotspots remain `0`, and the largest production functions now measure `66` lines.
LP-CR-1471 isolated available runtime work-item snapshot assembly into
`_available_runtime_work_item_snapshot(...)`. `build_runtime_work_item_snapshot(...)` dropped out
of the top-25 table, duplicate hotspots remain `0`, and the largest production function remains
`_build_flat_period_contribution_result(...)` at `66` lines.
LP-CR-1472 isolated runtime-recoveries FastAPI query metadata into named `TypeAlias` boundaries.
`build_runtime_recoveries_query(...)` dropped out of the top-25 table, duplicate hotspots remain
`0`, and the largest production function remains `_build_flat_period_contribution_result(...)` at
`66` lines.
LP-CR-1473 isolated shared contribution period frame, methodology-context, and average-weight audit
preparation into `_prepare_contribution_period(...)`. `_build_flat_period_contribution_result(...)`
and `_build_hierarchy_period_contribution_result(...)` dropped out of the top-25 table, duplicate
hotspots remain `0`, and the largest production functions now measure `65` lines.
LP-CR-1474 isolated promoted stateful benchmark finalization into
`_finalize_promoted_stateful_benchmark_execution(...)`. `_calculate_promoted_stateful_benchmark_workflow(...)`
dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest production
functions continue to measure `65` lines.
LP-CR-1475 isolated source-quality evidence-context assessment into
`_assess_source_quality_evidence_context(...)`. `run_source_quality_checks(...)` dropped out of the
top-25 table, duplicate hotspots remain `0`, and the largest production functions continue to
measure `65` lines.
LP-CR-1476 isolated resolved MWR engine execution and response assembly into
`_calculate_resolved_mwr_response(...)`. `calculate_mwr_response(...)` moved from `65` to `62`
lines, duplicate hotspots remain `0`, and the largest production functions continue to measure
`65` lines.
LP-CR-1477 isolated stateless MWR resolution, stateful source retrieval, stateful normalization,
and resolved stateful request projection into focused helpers in `mwr_mode_service`.
`resolve_mwr_request(...)` moved from `65` to `20` lines and dropped out of the top-25 table; the
extracted helpers measure `31`, `21`, `15`, and `7` lines, and the largest production functions
continue to measure `65` lines.
LP-CR-1478 isolated runtime-retention manifest read, validation, invalid-manifest logging, and
unavailable snapshot projection into `_resolve_runtime_retention_manifest(...)`.
`build_runtime_retention_history_snapshot(...)` moved from `65` to `50` lines and dropped out of
the top-25 table, duplicate hotspots remain `0`, and the largest production function is now
`StatefulInputService._fetch_position_chunk(...)` at `65` lines.
LP-CR-1479 isolated stateful position chunk response projection into
`StatefulInputService._build_position_chunk_payload(...)`.
`StatefulInputService._fetch_position_chunk(...)` dropped out of the top-25 table, duplicate
hotspots remain `0`, and the largest production functions now measure `64` lines.
LP-CR-1480 isolated stateless attribution request projection and resolved stateful attribution
request projection into `_resolve_stateless_attribution_request(...)` and
`_resolved_stateful_attribution_request(...)`. `resolve_attribution_request(...)` dropped out of
the top-25 table, duplicate hotspots remain `0`, and the largest production function remains
`LineageMetadataStore._build_pending_payload_stats_statement(...)` at `64` lines.
LP-CR-1481 isolated lineage pending-payload stats predicates into shared SQL-expression helpers
for pending, active leased, retry-backlog, and reclaimable payloads, then reused the retry and
active-lease predicates in queue inspection and recovery query builders. The lineage stats builder
dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest production
functions now measure `63` lines.
LP-CR-1482 isolated source-economics flow-date, cash-flow quality, and cash-flow taxonomy sample
recording from `_SourceEconomicsSampleCollector._record_taxonomy_samples(...)`. The taxonomy
orchestrator dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest
production functions continue to measure `63` lines.
LP-CR-1483 isolated governed operator-action lease metric source loading from
`_load_durable_queue_metric_sources(...)`. The durable queue metric source loader dropped out of
the top-25 table, duplicate hotspots remain `0`, and the largest production functions continue to
measure `63` lines.
LP-CR-1484 isolated stateful returns-series portfolio, benchmark, and risk-free source retrieval
into `_retrieve_stateful_returns_series_sources(...)`. The public stateful returns-series resolver
dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest production
functions continue to measure `63` lines.
LP-CR-1485 isolated stateful attribution normalization input policy validation from
`build_stateful_attribution_input(...)`. The stateful attribution input builder dropped out of the
top-25 table, duplicate hotspots remain `0`, and the largest production functions continue to
measure `63` lines.
LP-CR-1486 isolated attribution panel resampling and linked-return projection from
`_align_and_prepare_data(...)`. The attribution alignment orchestrator dropped out of the top-25
table, duplicate hotspots remain `0`, and the largest production functions now measure `62` lines.
LP-CR-1487 isolated stateful contribution source retrieval, normalization, and resolved-request
projection from `resolve_contribution_request(...)`. The contribution input-mode resolver dropped
out of the top-25 table, duplicate hotspots remain `0`, and the largest production functions
continue to measure `62` lines.
LP-CR-1488 isolated no-contribution-row smoothing evidence projection into
`_empty_contribution_smoothing_evidence(...)`. `_build_contribution_smoothing_evidence(...)`
dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest production
functions continue to measure `62` lines.
LP-CR-1489 isolated retained-calculation TWR inspection input materialization into
`_existing_calculation_subject_inspection_inputs(...)`. `_resolve_subject_inspection_inputs(...)`
dropped out of the top-25 table, duplicate hotspots remain `0`, and the largest production
functions continue to measure `62` lines.
LP-CR-1490 isolated MWR execution registration and initial identity materialization into
`_register_mwr_execution(...)`. `calculate_mwr_response(...)` dropped out of the top-25 table,
duplicate hotspots remain `0`, and the largest production function is now
`build_stateful_mwr_input_for_window(...)` at `62` lines.
LP-CR-1411 isolated runtime-status degradation policy response projection into focused helpers.
`build_runtime_status_response` moved from `113` to `91` lines, and the largest production
functions moved to the contribution period result builders at `102` lines.
LP-CR-1412 isolated contribution period supportability evidence assembly into a focused helper.
`_build_flat_period_contribution_result` moved from `102` to `92` lines,
`_build_hierarchy_period_contribution_result` moved from `102` to `90` lines, and the largest
production function moved to `_build_analytics_surfaces` at `101` lines.
LP-CR-1416 isolated synchronous integration-capability surface projection into a focused helper.
`_build_analytics_surfaces` moved from `113` to `93` lines and is no longer the largest production
function; the largest production functions are now `retrieve_stateful_attribution_source_input`
and `aggregate_attribution_results` at `98` lines each.
LP-CR-1417 isolated stateful attribution position and benchmark/index source retrieval into
focused helpers. `retrieve_stateful_attribution_source_input` moved from `98` to `71` lines and
dropped out of the top-25 table; `aggregate_attribution_results` is now the largest production
function at `98` lines.
LP-CR-1418 isolated currency-attribution result, totals, and lineage-effect projection into a
focused helper. `aggregate_attribution_results` moved from `98` to `50` lines and dropped out of
the top-25 table; the largest production function is now `build_runtime_retention_history_snapshot`
at `97` lines.
LP-CR-1419 isolated runtime-retention manifest entry projection into a focused helper.
`build_runtime_retention_history_snapshot` moved from `97` to `78` lines, and the largest production
function is now `resolve_attribution_request` at `94` lines.
LP-CR-1420 isolated attribution retrieval and normalization stage-detail projection into focused
helpers. `resolve_attribution_request` moved from `94` to `74` lines, and the largest production
functions are now `_build_analytics_surfaces`, `build_stateful_benchmark_input`, and
`calculate_twr_response` at `93` lines each.
LP-CR-1421 isolated portfolio/workspace analytics surface projection into a focused helper.
`_build_analytics_surfaces` moved from `93` to `52` lines, `_portfolio_analytics_surfaces`
measures `49` lines, and the largest production functions are now
`build_stateful_benchmark_input` and `calculate_twr_response` at `93` lines each.
LP-CR-1422 isolated calculated stateful benchmark input assembly into a focused helper.
`build_stateful_benchmark_input` moved from `93` to `35` lines and dropped out of the top-120
table, `_build_stateful_calculated_benchmark_input` measures `75` lines, and the largest
production function is now `calculate_twr_response` at `93` lines.
Attribution orchestration moved from `120` to `104` lines after execution-window resolution and
master request projection were isolated.
Attribution orchestration dropped out of the top-20 table after failure recording and HTTP
exception mapping were isolated from the public calculation path.
Contribution orchestration moved from `287` to `270` lines after engine input preparation was
isolated, then moved from `270` to `189` lines and is no longer the largest function after
flat-period result assembly was isolated from the public contribution orchestration. Benchmark calculation workflow
dropped out of the top-15 table after resolved benchmark execution context and failure mapping were isolated, and
then stayed out after promoted stateful workflow handling was isolated from the public workflow router.
Workspace summary response assembly moved from `172` to `122` lines after benchmark and active-return
period assembly were isolated.
Attribution result aggregation moved from `148` to `126` lines after active-return/linking policy
and granular effect totals were isolated.
Contribution calculation workflow dropped out of the top-15 table after promoted stateful
execution handling was isolated from the public workflow router.
Contribution orchestration dropped out of the top-15 table again after hierarchy-period result
assembly was isolated from the public contribution calculation function.
Contribution orchestration dropped out of the top-20 table after flat-vs-hierarchy period-result
collection and average-weight residual max tracking were isolated from the public contribution
calculation function.
Stateful attribution source input retrieval dropped out of the top-15 table after benchmark
assignment resolution was isolated from the source-input orchestration path.
It remains in the top-25 function-size table after requested upstream attribution dimension
selection was isolated; future size-focused work should target source retrieval/result projection
only where behavior can be preserved with direct tests.
Stateful position chunk retrieval dropped out of the top-25 table after page request/payload
projection was isolated from the chunk pagination loop.
Durable queue metric collection dropped out of the top-15 table after source loading and
availability/runtime-retention preview metric emission were isolated into dedicated helpers.
Source-economics top-level finding assembly dropped from `258` lines out of the top-15 table after
observation-contract, explicit-amount-contract, and detailed cash-flow contract finding groups were
isolated. `_build_detailed_cashflow_contract_findings` dropped out of the top-20 table after the
detailed cash-flow source contract taxonomy was converted to an explicit ordered catalog.
`_build_external_cashflow_findings` dropped out of the top-20 table after external cash-flow finding
construction was converted to the same explicit ordered catalog pattern.
`_build_fee_source_economics_findings` also dropped out of the top-20 table after fee finding
construction was converted to the same explicit ordered catalog pattern.
TWR inspection orchestration remains in the top-15 table but moved from `147` to `131` lines after
subject-resolution stage lifecycle handling was isolated from the public inspection orchestrator.
TWR inspection orchestration dropped out of the top-15 table after subject request materialization
and calculation-consistency loading were isolated from the public inspection orchestrator.
TWR inspection orchestration dropped out of the top-20 table after optional source-quality,
reconciliation, and source-economics subject assessments were isolated from the public inspection
orchestrator.
TWR calculation workflow dropped out of the top-20 table after resolved response finalization and
final response calculation were isolated from the public workflow function.
Attribution calculation workflow dropped out of the top-20 table after resolved stateful
finalization and initial async submission were isolated from the public workflow orchestrator.
Returns-series calculation orchestration dropped out of the top-15 table after execution-context
resolution was isolated from dataframe preparation, execution, diagnostics, and response assembly.
Stateful returns-series request resolution dropped out of the top-15 table after normalization-stage
completion, identity payload construction, and resolved stateless request assembly were isolated.
Composite inspection artifact assembly moved from `135` to `118` lines after customer-consumable
composite-period return row projection was isolated, then moved from `118` to `89` lines after
member-input and period-weight support artifact row projection were isolated.

Future refactor slices should use this report to choose bounded work where extraction, shared
helpers, or narrower tests can reduce function size while preserving analytics truth and API
contracts.
Runtime-retention manual cleanup orchestration moved from `111` to `93` lines after cleanup
evidence response projection was isolated. It remains a CC `7` hotspot, so future work should
target replay, guard, or lease-context assembly separately rather than claiming the function is
fully remediated.
It then moved from `93` to `83` lines and left the top-25 complexity table after apply-preview and
manual cooldown guard policy were isolated.
Runtime recovery snapshot assembly moved from `84` to `81` lines after common recovery list filters
and safe page-to-queue-state projection were isolated while preserving compute and lineage
queue-specific store filters.
The lifecycle degradation metric extraction did not change the top-20 function-size table; the
largest function remains `DurableQueueCollector.describe` at `159` lines.
The source-quality economic plausibility finding extraction did not change the top-20 function-size
table; the largest function remains `DurableQueueCollector.describe` at `159` lines.
The runtime work-item safe listing extraction did not change the top-20 function-size table; the
largest function remains `DurableQueueCollector.describe` at `159` lines.
The stateful timeseries snapshot append extraction did not change the top-20 function-size table;
the largest function remains `DurableQueueCollector.describe` at `159` lines.
LP-CR-1403 did not change the top-20 function-size table; the largest function remains
`DurableQueueCollector.describe` at `159` lines.
LP-CR-1404 did not change the top-25 function-size table; the largest function remains
`DurableQueueCollector.describe` at `159` lines.
LP-CR-1405 did not change the top-25 function-size table; the largest function remains
`DurableQueueCollector.describe` at `159` lines.
LP-CR-1406 moved common operator-action history snapshot envelope construction into a shared
helper. `build_runtime_retention_history_snapshot` moved from `101` to `97` lines and
`build_recovery_drill_history_snapshot` moved from `85` to `81` lines; the largest function remains
`DurableQueueCollector.describe` at `159` lines.
LP-CR-1407 centralized attribute-backed queue metric sample projection and did not change the
top-25 function-size table; the largest function remains `DurableQueueCollector.describe` at
`159` lines.
LP-CR-1408 isolated durable queue metric descriptor metadata into a deterministic catalog;
`DurableQueueCollector.describe` dropped out of the top-25 table and the largest function moved
from `159` to `131` lines.
LP-CR-1409 isolated runtime-status operator-action reclaim event projection into a shared response
mapper. `build_runtime_status_response` moved from `131` to `113` lines and the largest function
became `_build_analytics_surfaces` at `130` lines.
LP-CR-1410 isolated shared async analytics-surface response projection for integration
capabilities. `_build_analytics_surfaces` moved from `130` to `101` lines and the largest
production function moved to `build_runtime_status_response` at `113` lines.
LP-CR-1413 added the explicit composite TWR capability surface and the reusable demo API
certification command. The capability catalog change intentionally improved API truth but moved
`_build_analytics_surfaces` from `101` to `113` lines and `_build_feature_capabilities` from `75`
to `81` lines, so the next catalog refactor should split published feature/surface descriptors
without changing `/integration/capabilities` behavior.
LP-CR-1425 isolated recovery-drill and runtime-retention status response projection into focused
helpers. `build_runtime_status_response` dropped out of the top-25 table, and the largest
production functions are now `_build_hierarchy_period_contribution_result` and
`_calculate_returns_series` at `90` lines each.
LP-CR-1426 isolated hierarchy contribution residual-adjusted position assembly, series generation,
and hierarchy projection into a focused helper. `_build_hierarchy_period_contribution_result`
dropped out of the top-25 table, and the largest production function is now
`_calculate_returns_series` at `90` lines.
LP-CR-1427 isolated returns-series execution result assembly into a focused helper.
`_calculate_returns_series` moved from `90` to `49` lines and dropped out of the top-25 table;
`_build_returns_series_execution_result` measures `55` lines, and the largest production function
is now `_build_artifacts` at `89` lines.
LP-CR-1428 isolated composite inspection CSV artifact construction, lineage manifest projection,
and support-brief text into focused helpers. `_build_artifacts` moved from `89` to `33` lines and
dropped out of the top-25 table; the largest production function is now `calculate_twr_response`
at `87` lines.
LP-CR-1429 isolated completed TWR response assembly into a focused helper that owns supportability
metric recording, benchmark context projection, response envelope assembly, and lineage completion.
`calculate_twr_response` moved from `87` to `59` lines; `_assemble_completed_twr_response`
measures `59` lines, and the largest production function is now `run_runtime_retention_cleanup`
at `83` lines.
LP-CR-1430 isolated runtime-retention cleanup lease acquisition and evidence execution into a
focused helper. `run_runtime_retention_cleanup` moved from `83` to `54` lines;
`_run_runtime_retention_cleanup_under_lease` measures `50` lines, and the largest production
functions are now `_build_feature_capabilities`, `build_recovery_drill_history_snapshot`, and
`build_runtime_recovery_snapshot` at `81` lines each.
LP-CR-1431 isolated integration-capability feature publication into shared projection and
capability-family helpers while preserving the public feature order and enabled-flag semantics.
`_build_feature_capabilities` dropped out of the top-25 table, and the largest production
functions are now `build_recovery_drill_history_snapshot` and `build_runtime_recovery_snapshot`
at `81` lines each.
LP-CR-1433 isolated recovery-drill manifest entry projection and history filtering into focused
helpers while preserving manifest validation, unavailable-history reason semantics, applied
filters, and pagination. `build_recovery_drill_history_snapshot` dropped out of the top-25 table,
and the largest production function is now `build_runtime_recovery_snapshot` at `81` lines.
LP-CR-1434 isolated runtime recovery snapshot request/filter projection and final snapshot-envelope
assembly into focused helpers while preserving durability outage, queue exclusion, partial queue
failure, filter, and cursor semantics. `build_runtime_recovery_snapshot` dropped out of the
top-25 table, and the largest production functions are now `calculate_contribution` and
`LineageMetadataStore._build_inspection_query_statements` at `80` lines each.
LP-CR-1435 isolated contribution response evidence assembly and contribution execution lineage
handoff into focused helpers while preserving diagnostics, audit counts, supportability metric
recording, source-economics evidence, calculation details, and `/performance/contribution`
behavior. `_build_contribution_response` dropped out of the top-25 table, `calculate_contribution`
moved from `80` to `74` lines, and the largest production function is now
`LineageMetadataStore._build_inspection_query_statements` at `80` lines.
