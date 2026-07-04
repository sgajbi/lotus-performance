## Summary

| Metric | Value |
| --- | ---: |
| README required markers present | 8 |
| README required markers expected | 8 |
| Wiki source pages | 21 |
| Markdown documentation files | 234 |
| API catalog files present | 4 |
| API catalog files expected | 4 |
| Major pack README files present | 12 |
| Major pack README files expected | 12 |
| Docs regression test functions | 62 |
| Public definitions scanned | 1343 |
| Public definitions missing docstrings | 1183 |
| Public definition docstring coverage percent | 11.91 |

## Markdown Files By Family

| Family | Files |
| --- | ---: |
| guides | 17 |
| methodologies | 22 |
| operations | 4 |
| RFCs | 110 |
| endpoint certification | 20 |

## Public Docstring Gaps

| Rank | File | Line | Kind | Name |
| ---: | --- | ---: | --- | --- |
| 1 | `app/api/async_openapi.py` | 12 | `FunctionDef` | `async_submission_responses` |
| 2 | `app/api/async_openapi.py` | 30 | `FunctionDef` | `async_result_responses` |
| 3 | `app/api/dependencies/recovery_drill_history.py` | 61 | `FunctionDef` | `build_recovery_drill_history_query` |
| 4 | `app/api/dependencies/runtime_recoveries.py` | 73 | `FunctionDef` | `build_runtime_recoveries_query` |
| 5 | `app/api/dependencies/runtime_retention_history.py` | 79 | `FunctionDef` | `build_runtime_retention_history_query` |
| 6 | `app/api/dependencies/runtime_work_items.py` | 60 | `FunctionDef` | `build_runtime_work_items_query` |
| 7 | `app/api/endpoints/composites.py` | 136 | `FunctionDef` | `calculate_composite_twr` |
| 8 | `app/api/endpoints/composites.py` | 184 | `FunctionDef` | `inspect_composite_twr` |
| 9 | `app/api/endpoints/contribution.py` | 48 | `AsyncFunctionDef` | `calculate_contribution_endpoint` |
| 10 | `app/api/endpoints/contribution.py` | 72 | `AsyncFunctionDef` | `get_contribution_result` |
| 11 | `app/api/endpoints/executions.py` | 34 | `AsyncFunctionDef` | `get_execution` |
| 12 | `app/api/endpoints/inspections.py` | 58 | `FunctionDef` | `submit_twr_inspection` |
| 13 | `app/api/endpoints/inspections.py` | 84 | `FunctionDef` | `get_twr_inspection` |
| 14 | `app/api/endpoints/inspections.py` | 138 | `FunctionDef` | `get_twr_inspection_artifact` |
| 15 | `app/api/endpoints/integration_capabilities.py` | 365 | `ClassDef` | `FeatureCapability` |
| 16 | `app/api/endpoints/integration_capabilities.py` | 372 | `ClassDef` | `WorkflowCapability` |
| 17 | `app/api/endpoints/integration_capabilities.py` | 394 | `ClassDef` | `AnalyticsSurfaceOptionCapability` |
| 18 | `app/api/endpoints/integration_capabilities.py` | 416 | `ClassDef` | `AnalyticsSurfaceCapability` |
| 19 | `app/api/endpoints/integration_capabilities.py` | 459 | `ClassDef` | `IntegrationCapabilitiesResponse` |
| 20 | `app/api/endpoints/integration_capabilities.py` | 491 | `AsyncFunctionDef` | `get_integration_capabilities` |
| 21 | `app/api/endpoints/lineage.py` | 50 | `AsyncFunctionDef` | `get_lineage_data` |
| 22 | `app/api/endpoints/lineage.py` | 106 | `AsyncFunctionDef` | `get_lineage_artifact` |
| 23 | `app/api/endpoints/mandate_health_context.py` | 28 | `FunctionDef` | `evaluate_mandate_performance_health_context_endpoint` |
| 24 | `app/api/endpoints/performance.py` | 90 | `AsyncFunctionDef` | `get_workspace_summary_result` |
| 25 | `app/api/endpoints/performance.py` | 150 | `AsyncFunctionDef` | `get_twr_result` |
| 26 | `app/api/endpoints/performance.py` | 310 | `AsyncFunctionDef` | `get_attribution_result` |
| 27 | `app/api/endpoints/returns_series.py` | 39 | `AsyncFunctionDef` | `get_returns_series` |
| 28 | `app/api/endpoints/returns_series.py` | 56 | `AsyncFunctionDef` | `get_returns_series_result` |
| 29 | `app/api/http_response_adapter.py` | 12 | `FunctionDef` | `to_fastapi_response` |
| 30 | `app/api/operator_context.py` | 22 | `FunctionDef` | `resolve_operator_request_context` |
| 31 | `app/api/time_query_validation.py` | 11 | `FunctionDef` | `validate_utc_query_timestamp_window` |
| 32 | `app/core/application_responses.py` | 17 | `FunctionDef` | `accepted_application_response` |
| 33 | `app/core/config.py` | 10 | `ClassDef` | `Settings` |
| 34 | `app/core/config.py` | 105 | `FunctionDef` | `resolved_core_control_plane_base_url` |
| 35 | `app/enterprise_audit_emission.py` | 11 | `FunctionDef` | `emit_audit_event` |
| 36 | `app/enterprise_audit_middleware.py` | 25 | `ClassDef` | `AuditEventEmitter` |
| 37 | `app/enterprise_audit_middleware.py` | 69 | `FunctionDef` | `build_enterprise_audit_middleware` |
| 38 | `app/enterprise_audit_middleware.py` | 74 | `AsyncFunctionDef` | `middleware` |
| 39 | `app/enterprise_audit_redaction.py` | 38 | `FunctionDef` | `redact_sensitive` |
| 40 | `app/enterprise_authorization.py` | 149 | `FunctionDef` | `authorize_write_request` |
