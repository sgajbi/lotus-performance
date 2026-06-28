# Lotus Performance Test Taxonomy Inventory

Report date: 2026-06-28
Branch: `feature/performance-diagnostics-projection-boundary`
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
| Test modules inventoried | 278 |
| Test functions inventoried | 3199 |
| Integration/API/runtime test functions | 607 |
| Contract/governance test functions | 111 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 17 |
| e2e | 1 | 21 |
| integration | 24 | 300 |
| unit | 244 | 2861 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1114 |
| api_or_runtime | 607 |
| contract_or_governance | 111 |
| observability_or_readiness | 187 |
| quality_or_security | 118 |
| uncategorized | 1294 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 80 | observability_or_readiness |
| 2 | `tests/unit/services/test_returns_series_service.py` | unit | 75 | uncategorized |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 68 | analytics_domain |
| 4 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 5 | `tests/unit/services/test_compute_job_store.py` | unit | 58 | uncategorized |
| 6 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 7 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 8 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 54 | uncategorized |
| 9 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 10 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 49 | analytics_domain |
| 11 | `tests/unit/docs/test_public_docs_contract.py` | unit | 48 | contract_or_governance |
| 12 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 13 | `tests/unit/services/test_workspace_summary_service.py` | unit | 45 | uncategorized |
| 14 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | uncategorized |
| 15 | `tests/integration/test_contribution_api.py` | integration | 40 | analytics_domain, api_or_runtime |
| 16 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 39 | uncategorized |
| 17 | `tests/integration/test_performance_api.py` | integration | 38 | api_or_runtime |
| 18 | `tests/unit/engine/test_mwr.py` | unit | 38 | analytics_domain |
| 19 | `tests/unit/services/test_compute_executor_worker.py` | unit | 38 | uncategorized |
| 20 | `tests/unit/services/test_stateful_input_service.py` | unit | 36 | uncategorized |
| 21 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 34 | uncategorized |
| 22 | `tests/unit/models/test_twr_requests.py` | unit | 32 | analytics_domain |
| 23 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 32 | analytics_domain |
| 24 | `tests/unit/engine/test_contribution.py` | unit | 31 | analytics_domain |
| 25 | `tests/unit/models/test_workspace_summary_models.py` | unit | 31 | uncategorized |
| 26 | `tests/unit/test_observability.py` | unit | 31 | uncategorized |
| 27 | `tests/unit/engine/test_composites.py` | unit | 29 | analytics_domain |
| 28 | `tests/unit/services/test_operator_action_replay_service.py` | unit | 29 | uncategorized |
| 29 | `tests/unit/services/test_twr_inspection_service.py` | unit | 29 | analytics_domain |
| 30 | `tests/unit/app/test_performance_endpoint_helpers.py` | unit | 28 | api_or_runtime |

## Interpretation

The AST inventory counts test function definitions, while `pytest --collect-only` counts expanded
pytest items including parametrized cases. The two values are intentionally different and
complementary: collected tests show execution breadth, while this report shows source test-module
and test-function distribution. The current suite has meaningful API/runtime and
contract/governance coverage, but 1294 test functions remain uncategorized by the first-wave
taxonomy and should be reviewed before turning taxonomy into a blocking gate.
This slice added three service-boundary tests for execution polling: one proves the application
service reads execution, compute-job, and async-result metadata once for an existing calculation,
one proves missing execution records return `None` without querying optional async stores, and one
pins the legacy not-found detail as named execution polling error vocabulary. It preserves the
public execution polling route, OpenAPI schemas, and legacy typed 404 error payload while moving
durable-record projection out of the API model module.
The same branch also added six CI/domain-product/Docker-context gate tests that prove deterministic API
evaluation is wired into `make check`, `make ci`, Feature Lane, PR Merge Gate, Main Releasability,
platform-contract checkout, domain-product platform-root resolution, Docker build context exclusion
for generated demo/runtime state, and the Quality Baseline workflow without a soft-fail escape
hatch.

## Gate Posture

This is a Phase 1 report-only quality measurement. It does not introduce a CI threshold, branch
failure, or exception policy. Promotion to a blocking gate should wait until the taxonomy labels and
uncategorized-test policy are stable.
