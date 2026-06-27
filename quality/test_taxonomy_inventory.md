# Lotus Performance Test Taxonomy Inventory

Report date: 2026-06-27
Branch: `feature/enterprise-backend-refactor-baseline`
Mode: report-only test taxonomy inventory; no blocking CI gate is introduced by this artifact.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 274 |
| Test functions inventoried | 3045 |
| Integration/API/runtime test functions | 600 |
| Contract/governance test functions | 108 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 17 |
| e2e | 1 | 21 |
| integration | 24 | 300 |
| unit | 240 | 2707 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1051 |
| api_or_runtime | 600 |
| contract_or_governance | 108 |
| observability_or_readiness | 186 |
| quality_or_security | 107 |
| uncategorized | 1223 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 80 | observability_or_readiness |
| 2 | `tests/unit/services/test_returns_series_service.py` | unit | 69 | uncategorized |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 65 | analytics_domain |
| 4 | `tests/unit/app/test_openapi_enrichment.py` | unit | 59 | api_or_runtime |
| 5 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 6 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 50 | analytics_domain, api_or_runtime |
| 7 | `tests/unit/services/test_compute_job_store.py` | unit | 50 | uncategorized |
| 8 | `tests/unit/engine/test_attribution.py` | unit | 49 | analytics_domain |
| 9 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 49 | analytics_domain |
| 10 | `tests/unit/docs/test_public_docs_contract.py` | unit | 48 | contract_or_governance |
| 11 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 43 | uncategorized |
| 12 | `tests/integration/test_contribution_api.py` | integration | 40 | analytics_domain, api_or_runtime |
| 13 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 39 | uncategorized |
| 14 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 39 | uncategorized |
| 15 | `tests/integration/test_performance_api.py` | integration | 38 | api_or_runtime |
| 16 | `tests/unit/services/test_compute_executor_worker.py` | unit | 38 | uncategorized |
| 17 | `tests/unit/services/test_twr_mode_service.py` | unit | 38 | analytics_domain |
| 18 | `tests/unit/services/test_workspace_summary_service.py` | unit | 38 | uncategorized |
| 19 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 33 | uncategorized |
| 20 | `tests/unit/engine/test_mwr.py` | unit | 32 | analytics_domain |
| 21 | `tests/unit/models/test_twr_requests.py` | unit | 32 | analytics_domain |
| 22 | `tests/unit/models/test_workspace_summary_models.py` | unit | 31 | uncategorized |
| 23 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 31 | analytics_domain |
| 24 | `tests/unit/services/test_stateful_input_service.py` | unit | 30 | uncategorized |
| 25 | `tests/unit/engine/test_composites.py` | unit | 29 | analytics_domain |
| 26 | `tests/unit/services/test_operator_action_replay_service.py` | unit | 29 | uncategorized |
| 27 | `tests/integration/test_returns_series_api.py` | integration | 26 | api_or_runtime |
| 28 | `tests/unit/services/test_queue_metric_builders.py` | unit | 26 | observability_or_readiness |
| 29 | `tests/unit/services/test_twr_inspection_service.py` | unit | 26 | analytics_domain |
| 30 | `tests/unit/app/test_performance_endpoint_helpers.py` | unit | 25 | api_or_runtime |

## Interpretation

The AST inventory counts test function definitions, while `pytest --collect-only` counts expanded
pytest items including parametrized cases. The two values are intentionally different and
complementary: collected tests show execution breadth, while this report shows source test-module
and test-function distribution. The current suite has meaningful API/runtime and
contract/governance coverage, but 1223 test functions remain uncategorized by the first-wave
taxonomy and should be reviewed before turning taxonomy into a blocking gate.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the taxonomy labels and
uncategorized-test policy are stable.
