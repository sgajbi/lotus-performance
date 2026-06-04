# Lotus Performance Test Taxonomy Inventory

Report date: 2026-06-04
Branch: `feat/performance-hardening-wave-9`
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
| Test modules inventoried | 242 |
| Test functions inventoried | 1950 |
| Integration/API/runtime test functions | 453 |
| Contract/governance test functions | 107 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 17 |
| e2e | 1 | 21 |
| integration | 23 | 298 |
| unit | 209 | 1614 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 557 |
| api_or_runtime | 453 |
| contract_or_governance | 107 |
| observability_or_readiness | 165 |
| quality_or_security | 48 |
| uncategorized | 794 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 76 | observability_or_readiness |
| 2 | `tests/unit/docs/test_public_docs_contract.py` | unit | 47 | contract_or_governance |
| 3 | `tests/integration/test_contribution_api.py` | integration | 40 | analytics_domain, api_or_runtime |
| 4 | `tests/integration/test_performance_api.py` | integration | 38 | api_or_runtime |
| 5 | `tests/unit/engine/test_attribution.py` | unit | 31 | analytics_domain |
| 6 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 31 | uncategorized |
| 7 | `tests/unit/services/test_compute_job_store.py` | unit | 27 | uncategorized |
| 8 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 27 | analytics_domain |
| 9 | `tests/integration/test_returns_series_api.py` | integration | 26 | api_or_runtime |
| 10 | `tests/unit/app/test_request_path_runtime_settings.py` | unit | 25 | uncategorized |
| 11 | `tests/unit/services/test_queue_metric_builders.py` | unit | 25 | observability_or_readiness |
| 12 | `tests/unit/services/test_runtime_status_service.py` | unit | 25 | uncategorized |
| 13 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 24 | uncategorized |
| 14 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 24 | analytics_domain |
| 15 | `tests/unit/models/test_twr_requests.py` | unit | 22 | analytics_domain |
| 16 | `tests/unit/models/test_workspace_summary_models.py` | unit | 22 | uncategorized |
| 17 | `tests/e2e/test_workflow_journeys.py` | e2e | 21 | api_or_runtime |
| 18 | `tests/integration/test_attribution_api.py` | integration | 21 | analytics_domain, api_or_runtime |
| 19 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 21 | analytics_domain, api_or_runtime |
| 20 | `tests/unit/app/test_enterprise_readiness.py` | unit | 21 | observability_or_readiness |
| 21 | `tests/unit/engine/test_rules.py` | unit | 21 | analytics_domain |
| 22 | `tests/unit/services/test_compute_executor_worker.py` | unit | 21 | uncategorized |
| 23 | `tests/integration/test_integration_capabilities_api.py` | integration | 20 | api_or_runtime |
| 24 | `tests/unit/services/test_stateful_input_service.py` | unit | 19 | uncategorized |
| 25 | `tests/integration/test_runtime_status_api.py` | integration | 18 | api_or_runtime |
| 26 | `tests/unit/engine/test_contribution.py` | unit | 18 | analytics_domain |
| 27 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 18 | uncategorized |
| 28 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 18 | uncategorized |
| 29 | `tests/unit/services/test_workspace_summary_service.py` | unit | 18 | uncategorized |
| 30 | `tests/unit/engine/test_compute.py` | unit | 17 | analytics_domain |

## Interpretation

The AST inventory counts test function definitions, while `pytest --collect-only` counts expanded
pytest items including parametrized cases. The two values are intentionally different and
complementary: collected tests show execution breadth, while this report shows source test-module
and test-function distribution. The current suite has meaningful API/runtime and
contract/governance coverage, but 794 test functions remain uncategorized by the first-wave
taxonomy and should be reviewed before turning taxonomy into a blocking gate.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the taxonomy labels and
uncategorized-test policy are stable.
