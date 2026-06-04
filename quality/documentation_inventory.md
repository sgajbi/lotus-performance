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
| Public definitions missing docstrings | 988 |
| Public definition docstring coverage percent | 12.02 |

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
| 1 | `app/api/endpoints/composites.py` | 136 | `FunctionDef` | `calculate_composite_twr` |
| 2 | `app/api/endpoints/composites.py` | 184 | `FunctionDef` | `inspect_composite_twr` |
| 3 | `app/api/endpoints/contribution.py` | 129 | `AsyncFunctionDef` | `calculate_contribution_endpoint` |
| 4 | `app/api/endpoints/contribution.py` | 269 | `AsyncFunctionDef` | `get_contribution_result` |
| 5 | `app/api/endpoints/executions.py` | 36 | `AsyncFunctionDef` | `get_execution` |
| 6 | `app/api/endpoints/inspections.py` | 51 | `FunctionDef` | `submit_twr_inspection` |
| 7 | `app/api/endpoints/inspections.py` | 99 | `FunctionDef` | `get_twr_inspection` |
| 8 | `app/api/endpoints/inspections.py` | 147 | `FunctionDef` | `get_twr_inspection_artifact` |
| 9 | `app/api/endpoints/integration_capabilities.py` | 341 | `ClassDef` | `FeatureCapability` |
| 10 | `app/api/endpoints/integration_capabilities.py` | 348 | `ClassDef` | `WorkflowCapability` |
| 11 | `app/api/endpoints/integration_capabilities.py` | 370 | `ClassDef` | `AnalyticsSurfaceOptionCapability` |
| 12 | `app/api/endpoints/integration_capabilities.py` | 392 | `ClassDef` | `AnalyticsSurfaceCapability` |
| 13 | `app/api/endpoints/integration_capabilities.py` | 435 | `ClassDef` | `IntegrationCapabilitiesResponse` |
| 14 | `app/api/endpoints/integration_capabilities.py` | 483 | `AsyncFunctionDef` | `get_integration_capabilities` |
| 15 | `app/api/endpoints/lineage.py` | 102 | `AsyncFunctionDef` | `get_lineage_data` |
| 16 | `app/api/endpoints/lineage.py` | 196 | `AsyncFunctionDef` | `get_lineage_artifact` |
| 17 | `app/api/endpoints/mandate_health_context.py` | 28 | `FunctionDef` | `evaluate_mandate_performance_health_context_endpoint` |
| 18 | `app/api/endpoints/performance.py` | 305 | `AsyncFunctionDef` | `get_workspace_summary_result` |
| 19 | `app/api/endpoints/performance.py` | 513 | `AsyncFunctionDef` | `get_twr_result` |
| 20 | `app/api/endpoints/performance.py` | 922 | `AsyncFunctionDef` | `get_attribution_result` |
| 21 | `app/api/endpoints/returns_series.py` | 118 | `AsyncFunctionDef` | `get_returns_series` |
| 22 | `app/api/endpoints/returns_series.py` | 218 | `AsyncFunctionDef` | `get_returns_series_result` |
| 23 | `app/api/operator_context.py` | 9 | `ClassDef` | `OperatorRequestContext` |
| 24 | `app/api/operator_context.py` | 15 | `FunctionDef` | `resolve_operator_request_context` |
| 25 | `app/api/time_query_validation.py` | 11 | `FunctionDef` | `validate_utc_query_timestamp_window` |
| 26 | `app/core/config.py` | 10 | `ClassDef` | `Settings` |
| 27 | `app/core/config.py` | 94 | `FunctionDef` | `resolved_core_control_plane_base_url` |
| 28 | `app/enterprise_audit_emission.py` | 11 | `FunctionDef` | `emit_audit_event` |
| 29 | `app/enterprise_audit_middleware.py` | 20 | `ClassDef` | `AuditEventEmitter` |
| 30 | `app/enterprise_audit_middleware.py` | 64 | `FunctionDef` | `build_enterprise_audit_middleware` |
| 31 | `app/enterprise_audit_middleware.py` | 69 | `AsyncFunctionDef` | `middleware` |
| 32 | `app/enterprise_audit_redaction.py` | 38 | `FunctionDef` | `redact_sensitive` |
| 33 | `app/enterprise_authorization.py` | 110 | `FunctionDef` | `authorize_write_request` |
| 34 | `app/enterprise_authorization.py` | 122 | `FunctionDef` | `authorize_privileged_read_request` |
| 35 | `app/enterprise_capability_rules.py` | 100 | `FunctionDef` | `load_capability_rules` |
| 36 | `app/enterprise_capability_rules.py` | 107 | `FunctionDef` | `load_privileged_read_rules` |
| 37 | `app/enterprise_feature_flags.py` | 6 | `FunctionDef` | `load_feature_flags` |
| 38 | `app/enterprise_feature_flags.py` | 33 | `FunctionDef` | `is_feature_enabled` |
| 39 | `app/enterprise_readiness.py` | 215 | `FunctionDef` | `emit_audit_event` |
| 40 | `app/enterprise_readiness.py` | 254 | `FunctionDef` | `build_enterprise_audit_middleware` |
