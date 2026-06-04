## Summary

| Metric | Value |
| --- | ---: |
| README required markers present | 8 |
| README required markers expected | 8 |
| Wiki source pages | 20 |
| Markdown documentation files | 230 |
| API catalog files present | 4 |
| API catalog files expected | 4 |
| Docs regression test functions | 56 |
| Public definitions scanned | 1123 |
| Public definitions missing docstrings | 1001 |
| Public definition docstring coverage percent | 10.86 |

## Markdown Files By Family

| Family | Files |
| --- | ---: |
| guides | 16 |
| methodologies | 22 |
| operations | 4 |
| RFCs | 110 |
| endpoint certification | 20 |

## Public Docstring Gaps

| Rank | File | Line | Kind | Name |
| ---: | --- | ---: | --- | --- |
| 1 | `app/api/endpoints/benchmark.py` | 63 | `AsyncFunctionDef` | `calculate_benchmark_endpoint` |
| 2 | `app/api/endpoints/benchmark.py` | 219 | `AsyncFunctionDef` | `get_benchmark_result` |
| 3 | `app/api/endpoints/benchmark_exposure_context.py` | 28 | `AsyncFunctionDef` | `get_benchmark_exposure_context` |
| 4 | `app/api/endpoints/composites.py` | 136 | `FunctionDef` | `calculate_composite_twr` |
| 5 | `app/api/endpoints/composites.py` | 184 | `FunctionDef` | `inspect_composite_twr` |
| 6 | `app/api/endpoints/contribution.py` | 129 | `AsyncFunctionDef` | `calculate_contribution_endpoint` |
| 7 | `app/api/endpoints/contribution.py` | 269 | `AsyncFunctionDef` | `get_contribution_result` |
| 8 | `app/api/endpoints/executions.py` | 36 | `AsyncFunctionDef` | `get_execution` |
| 9 | `app/api/endpoints/health.py` | 16 | `AsyncFunctionDef` | `health` |
| 10 | `app/api/endpoints/health.py` | 26 | `AsyncFunctionDef` | `health_live` |
| 11 | `app/api/endpoints/health.py` | 39 | `AsyncFunctionDef` | `health_ready` |
| 12 | `app/api/endpoints/inspections.py` | 51 | `FunctionDef` | `submit_twr_inspection` |
| 13 | `app/api/endpoints/inspections.py` | 99 | `FunctionDef` | `get_twr_inspection` |
| 14 | `app/api/endpoints/inspections.py` | 147 | `FunctionDef` | `get_twr_inspection_artifact` |
| 15 | `app/api/endpoints/integration_capabilities.py` | 341 | `ClassDef` | `FeatureCapability` |
| 16 | `app/api/endpoints/integration_capabilities.py` | 348 | `ClassDef` | `WorkflowCapability` |
| 17 | `app/api/endpoints/integration_capabilities.py` | 370 | `ClassDef` | `AnalyticsSurfaceOptionCapability` |
| 18 | `app/api/endpoints/integration_capabilities.py` | 392 | `ClassDef` | `AnalyticsSurfaceCapability` |
| 19 | `app/api/endpoints/integration_capabilities.py` | 435 | `ClassDef` | `IntegrationCapabilitiesResponse` |
| 20 | `app/api/endpoints/integration_capabilities.py` | 483 | `AsyncFunctionDef` | `get_integration_capabilities` |
| 21 | `app/api/endpoints/lineage.py` | 102 | `AsyncFunctionDef` | `get_lineage_data` |
| 22 | `app/api/endpoints/lineage.py` | 196 | `AsyncFunctionDef` | `get_lineage_artifact` |
| 23 | `app/api/endpoints/mandate_health_context.py` | 28 | `FunctionDef` | `evaluate_mandate_performance_health_context_endpoint` |
| 24 | `app/api/endpoints/performance.py` | 305 | `AsyncFunctionDef` | `get_workspace_summary_result` |
| 25 | `app/api/endpoints/performance.py` | 513 | `AsyncFunctionDef` | `get_twr_result` |
| 26 | `app/api/endpoints/performance.py` | 922 | `AsyncFunctionDef` | `get_attribution_result` |
| 27 | `app/api/endpoints/recovery_drill_history.py` | 43 | `AsyncFunctionDef` | `get_recovery_drill_history` |
| 28 | `app/api/endpoints/recovery_drill_history.py` | 114 | `AsyncFunctionDef` | `run_recovery_drill` |
| 29 | `app/api/endpoints/returns_series.py` | 118 | `AsyncFunctionDef` | `get_returns_series` |
| 30 | `app/api/endpoints/returns_series.py` | 218 | `AsyncFunctionDef` | `get_returns_series_result` |
| 31 | `app/api/endpoints/runtime_recoveries.py` | 27 | `AsyncFunctionDef` | `get_runtime_recoveries` |
| 32 | `app/api/endpoints/runtime_retention_history.py` | 46 | `AsyncFunctionDef` | `get_runtime_retention_history` |
| 33 | `app/api/endpoints/runtime_retention_history.py` | 137 | `AsyncFunctionDef` | `run_runtime_retention_cleanup` |
| 34 | `app/api/endpoints/runtime_status.py` | 23 | `AsyncFunctionDef` | `get_runtime_status` |
| 35 | `app/api/endpoints/runtime_work_items.py` | 25 | `AsyncFunctionDef` | `get_runtime_work_items` |
| 36 | `app/api/operator_context.py` | 9 | `ClassDef` | `OperatorRequestContext` |
| 37 | `app/api/operator_context.py` | 15 | `FunctionDef` | `resolve_operator_request_context` |
| 38 | `app/api/time_query_validation.py` | 11 | `FunctionDef` | `validate_utc_query_timestamp_window` |
| 39 | `app/core/config.py` | 10 | `ClassDef` | `Settings` |
| 40 | `app/core/config.py` | 94 | `FunctionDef` | `resolved_core_control_plane_base_url` |
