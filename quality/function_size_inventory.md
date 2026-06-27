# Lotus Performance Function Size Inventory

Report date: 2026-06-27
Branch: `lp-cr-1441-lineage-payload-lease-boundary`
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
| 1 | `_build_stateful_calculated_benchmark_input` | `app/services/stateful_benchmark_input_service.py:94` | 75 |
| 2 | `build_runtime_retention_history_query` | `app/api/dependencies/runtime_retention_history.py:11` | 74 |
| 3 | `resolve_attribution_request` | `app/services/attribution_mode_service.py:33` | 74 |
| 4 | `_build_portfolio_engine_diagnostics` | `app/services/contribution_diagnostics.py:62` | 74 |
| 5 | `calculate_contribution` | `app/services/contribution_service.py:773` | 74 |
| 6 | `build_runtime_work_item_snapshot` | `app/services/runtime_work_item_service.py:62` | 74 |
| 7 | `_build_workspace_benchmark_and_active_blocks` | `app/services/workspace_summary_service.py:717` | 74 |
| 8 | `calculate_attribution` | `app/services/attribution_service.py:313` | 73 |
| 9 | `_build_attribution_supportability_reasons` | `engine/attribution_supportability.py:174` | 73 |
| 10 | `run_recovery_drill` | `app/api/endpoints/recovery_drill_history.py:115` | 72 |
| 11 | `calculate_benchmark_response` | `app/services/benchmark_service.py:14` | 72 |
| 12 | `_build_flat_period_contribution_result` | `app/services/contribution_service.py:399` | 72 |
| 13 | `calculate_mwr_response` | `app/services/mwr_calculation_service.py:162` | 72 |
| 14 | `_resolve_stateful_returns_series_benchmark_source` | `app/services/returns_series_service.py:1096` | 72 |
| 15 | `retrieve_stateful_attribution_source_input` | `app/services/stateful_attribution_input_service.py:87` | 71 |
| 16 | `StatefulInputService._fetch_portfolio_chunk` | `app/services/stateful_input_service.py:877` | 71 |
| 17 | `_build_hierarchy_period_contribution_result` | `app/services/contribution_service.py:473` | 70 |
| 18 | `build_mwr_response` | `app/services/mwr_calculation_service.py:42` | 70 |
| 19 | `_build_workspace_results_by_period` | `app/services/workspace_summary_service.py:632` | 70 |
| 20 | `_process_pending_jobs` | `app/workers/compute_executor_worker.py:113` | 70 |
| 21 | `AverageWeightShadowAuditState._rollout_posture_notes` | `app/services/contribution_audit.py:125` | 69 |
| 22 | `_build_artifact_payload` | `app/services/inspection/source_economics.py:413` | 69 |
| 23 | `_calculate_promoted_stateful_returns_series` | `app/services/returns_series_calculation_workflow_service.py:136` | 69 |
| 24 | `StatefulInputService._fetch_position_chunk` | `app/services/stateful_input_service.py:1002` | 68 |
| 25 | `_build_workspace_summary_response` | `app/services/workspace_summary_service.py:547` | 68 |

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
