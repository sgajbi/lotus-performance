## Summary

| Metric | Value |
| --- | ---: |
| README required markers present | 8 |
| README required markers expected | 8 |
| Wiki source pages | 20 |
| Markdown documentation files | 232 |
| API catalog files present | 4 |
| API catalog files expected | 4 |
| Docs regression test functions | 57 |
| Public definitions scanned | 1225 |
| Public definitions missing docstrings | 1083 |
| Public definition docstring coverage percent | 11.59 |

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
| 1 | `app/api/dependencies/runtime_recoveries.py` | 11 | `FunctionDef` | `build_runtime_recoveries_query` |
| 2 | `app/api/dependencies/runtime_retention_history.py` | 11 | `FunctionDef` | `build_runtime_retention_history_query` |
| 3 | `app/api/endpoints/composites.py` | 136 | `FunctionDef` | `calculate_composite_twr` |
| 4 | `app/api/endpoints/composites.py` | 184 | `FunctionDef` | `inspect_composite_twr` |
| 5 | `app/api/endpoints/contribution.py` | 40 | `AsyncFunctionDef` | `calculate_contribution_endpoint` |
| 6 | `app/api/endpoints/contribution.py` | 57 | `AsyncFunctionDef` | `get_contribution_result` |
| 7 | `app/api/endpoints/executions.py` | 36 | `AsyncFunctionDef` | `get_execution` |
| 8 | `app/api/endpoints/inspections.py` | 95 | `FunctionDef` | `submit_twr_inspection` |
| 9 | `app/api/endpoints/inspections.py` | 132 | `FunctionDef` | `get_twr_inspection` |
| 10 | `app/api/endpoints/inspections.py` | 180 | `FunctionDef` | `get_twr_inspection_artifact` |
| 11 | `app/api/endpoints/integration_capabilities.py` | 364 | `ClassDef` | `FeatureCapability` |
| 12 | `app/api/endpoints/integration_capabilities.py` | 371 | `ClassDef` | `WorkflowCapability` |
| 13 | `app/api/endpoints/integration_capabilities.py` | 393 | `ClassDef` | `AnalyticsSurfaceOptionCapability` |
| 14 | `app/api/endpoints/integration_capabilities.py` | 415 | `ClassDef` | `AnalyticsSurfaceCapability` |
| 15 | `app/api/endpoints/integration_capabilities.py` | 458 | `ClassDef` | `IntegrationCapabilitiesResponse` |
| 16 | `app/api/endpoints/integration_capabilities.py` | 489 | `AsyncFunctionDef` | `get_integration_capabilities` |
| 17 | `app/api/endpoints/lineage.py` | 187 | `AsyncFunctionDef` | `get_lineage_data` |
| 18 | `app/api/endpoints/lineage.py` | 240 | `AsyncFunctionDef` | `get_lineage_artifact` |
| 19 | `app/api/endpoints/mandate_health_context.py` | 28 | `FunctionDef` | `evaluate_mandate_performance_health_context_endpoint` |
| 20 | `app/api/endpoints/performance.py` | 174 | `AsyncFunctionDef` | `get_workspace_summary_result` |
| 21 | `app/api/endpoints/performance.py` | 237 | `AsyncFunctionDef` | `get_twr_result` |
| 22 | `app/api/endpoints/performance.py` | 391 | `AsyncFunctionDef` | `get_attribution_result` |
| 23 | `app/api/endpoints/returns_series.py` | 31 | `AsyncFunctionDef` | `get_returns_series` |
| 24 | `app/api/endpoints/returns_series.py` | 41 | `AsyncFunctionDef` | `get_returns_series_result` |
| 25 | `app/api/operator_context.py` | 9 | `ClassDef` | `OperatorRequestContext` |
| 26 | `app/api/operator_context.py` | 29 | `FunctionDef` | `resolve_operator_request_context` |
| 27 | `app/api/time_query_validation.py` | 11 | `FunctionDef` | `validate_utc_query_timestamp_window` |
| 28 | `app/core/config.py` | 10 | `ClassDef` | `Settings` |
| 29 | `app/core/config.py` | 94 | `FunctionDef` | `resolved_core_control_plane_base_url` |
| 30 | `app/enterprise_audit_emission.py` | 11 | `FunctionDef` | `emit_audit_event` |
| 31 | `app/enterprise_audit_middleware.py` | 20 | `ClassDef` | `AuditEventEmitter` |
| 32 | `app/enterprise_audit_middleware.py` | 64 | `FunctionDef` | `build_enterprise_audit_middleware` |
| 33 | `app/enterprise_audit_middleware.py` | 69 | `AsyncFunctionDef` | `middleware` |
| 34 | `app/enterprise_audit_redaction.py` | 38 | `FunctionDef` | `redact_sensitive` |
| 35 | `app/enterprise_authorization.py` | 149 | `FunctionDef` | `authorize_write_request` |
| 36 | `app/enterprise_authorization.py` | 161 | `FunctionDef` | `authorize_privileged_read_request` |
| 37 | `app/enterprise_capability_rules.py` | 113 | `FunctionDef` | `load_capability_rules` |
| 38 | `app/enterprise_capability_rules.py` | 120 | `FunctionDef` | `load_privileged_read_rules` |
| 39 | `app/enterprise_feature_flags.py` | 6 | `FunctionDef` | `load_feature_flags` |
| 40 | `app/enterprise_feature_flags.py` | 33 | `FunctionDef` | `is_feature_enabled` |
