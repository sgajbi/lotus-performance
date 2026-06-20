# Lotus Performance Function Size Inventory

Report date: 2026-06-20
Branch: `lp-cr-1413-demo-api-certification`
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
| 1 | `_build_analytics_surfaces` | `app/services/integration_capabilities_service.py:381` | 113 |
| 2 | `retrieve_stateful_attribution_source_input` | `app/services/stateful_attribution_input_service.py:71` | 98 |
| 3 | `aggregate_attribution_results` | `engine/attribution.py:704` | 98 |
| 4 | `build_runtime_retention_history_snapshot` | `app/services/runtime_retention_history_service.py:91` | 97 |
| 5 | `resolve_attribution_request` | `app/services/attribution_mode_service.py:31` | 94 |
| 6 | `build_stateful_benchmark_input` | `app/services/stateful_benchmark_input_service.py:57` | 93 |
| 7 | `calculate_twr_response` | `app/services/twr_service.py:1159` | 93 |
| 8 | `_build_flat_period_contribution_result` | `app/services/contribution_service.py:283` | 92 |
| 9 | `build_runtime_status_response` | `app/models/runtime_status.py:838` | 91 |
| 10 | `_build_hierarchy_period_contribution_result` | `app/services/contribution_service.py:377` | 90 |
| 11 | `_calculate_returns_series` | `app/services/returns_series_service.py:1463` | 90 |
| 12 | `_build_artifacts` | `app/services/composite_inspection_service.py:154` | 89 |
| 13 | `run_runtime_retention_cleanup` | `app/services/runtime_retention_run_service.py:112` | 83 |
| 14 | `_build_feature_capabilities` | `app/services/integration_capabilities_service.py:96` | 81 |
| 15 | `build_recovery_drill_history_snapshot` | `app/services/recovery_drill_history_service.py:66` | 81 |
| 16 | `build_runtime_recovery_snapshot` | `app/services/runtime_recovery_service.py:67` | 81 |
| 17 | `calculate_contribution` | `app/services/contribution_service.py:648` | 80 |
| 18 | `LineageMetadataStore._build_inspection_query_statements` | `app/services/lineage_metadata_store.py:529` | 80 |
| 19 | `_build_contribution_response` | `app/services/contribution_service.py:567` | 79 |
| 20 | `_build_twr_inspection_response` | `app/services/inspection/twr_inspection_service.py:305` | 79 |
| 21 | `StatefulInputService._fetch_portfolio_chunk` | `app/services/stateful_input_service.py:877` | 79 |
| 22 | `resolve_contribution_request` | `app/services/contribution_mode_service.py:32` | 77 |
| 23 | `LineageMetadataStore._lease_pending_payloads_postgresql` | `app/services/lineage_metadata_store.py:1043` | 77 |
| 24 | `build_runtime_retention_history_query` | `app/api/dependencies/runtime_retention_history.py:11` | 74 |
| 25 | `_build_portfolio_engine_diagnostics` | `app/services/contribution_diagnostics.py:62` | 74 |

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
LP-CR-1411 isolated runtime-status degradation policy response projection into focused helpers.
`build_runtime_status_response` moved from `113` to `91` lines, and the largest production
functions moved to the contribution period result builders at `102` lines.
LP-CR-1412 isolated contribution period supportability evidence assembly into a focused helper.
`_build_flat_period_contribution_result` moved from `102` to `92` lines,
`_build_hierarchy_period_contribution_result` moved from `102` to `90` lines, and the largest
production function moved to `_build_analytics_surfaces` at `101` lines.
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
