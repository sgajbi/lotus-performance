# Lotus Performance Test Taxonomy Inventory

Report date: 2026-09-07
Branch: `fix/wire-the-blocking-gates`
Mode: regression-blocking test taxonomy inventory; `make quality-test-taxonomy-gate` enforces
minimum API/runtime and contract/governance breadth plus the current uncategorized-test ceiling.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 656 --min-contract-governance-tests 136 --max-uncategorized-tests 876
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 322 |
| Test functions inventoried | 3663 |
| Integration/API/runtime test functions | 699 |
| Contract/governance test functions | 178 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 19 |
| e2e | 1 | 21 |
| integration | 28 | 343 |
| unit | 284 | 3280 |

## Test Functions By Family

A module can belong to more than one family - `_families_for_path` returns every family a path
matches - so these counts **overlap by design and do not sum to the total**. The suite table
above does sum to it, because a module belongs to exactly one suite.

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1672 |
| api_or_runtime | 699 |
| contract_or_governance | 178 |
| observability_or_readiness | 375 |
| quality_or_security | 225 |
| uncategorized | 876 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/services/test_returns_series_service.py` | unit | 96 | analytics_domain |
| 2 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 87 | observability_or_readiness |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 70 | analytics_domain |
| 4 | `tests/unit/docs/test_public_docs_contract.py` | unit | 68 | contract_or_governance |
| 5 | `tests/unit/services/test_compute_job_store.py` | unit | 67 | observability_or_readiness |
| 6 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 7 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 60 | uncategorized |
| 8 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 9 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 10 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 11 | `tests/unit/services/test_compute_executor_worker.py` | unit | 51 | uncategorized |
| 12 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 51 | analytics_domain |
| 13 | `tests/unit/services/test_workspace_summary_service.py` | unit | 50 | analytics_domain |
| 14 | `tests/unit/services/test_stateful_input_service.py` | unit | 47 | analytics_domain |
| 15 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 16 | `tests/unit/engine/test_mwr.py` | unit | 44 | analytics_domain |
| 17 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | analytics_domain |
| 18 | `tests/integration/test_contribution_api.py` | integration | 41 | analytics_domain, api_or_runtime |
| 19 | `tests/integration/test_performance_api.py` | integration | 40 | api_or_runtime |
| 20 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 40 | uncategorized |
| 21 | `tests/unit/services/test_benchmark_exposure_context_service.py` | unit | 35 | analytics_domain |
| 22 | `tests/unit/test_observability.py` | unit | 34 | observability_or_readiness |
| 23 | `tests/unit/engine/test_contribution.py` | unit | 33 | analytics_domain |
| 24 | `tests/unit/models/test_twr_requests.py` | unit | 32 | analytics_domain |
| 25 | `tests/unit/services/test_twr_inspection_reconciliation.py` | unit | 32 | analytics_domain |
| 26 | `tests/integration/test_returns_series_api.py` | integration | 31 | analytics_domain, api_or_runtime |
| 27 | `tests/unit/app/test_enterprise_readiness.py` | unit | 31 | observability_or_readiness |
| 28 | `tests/unit/models/test_workspace_summary_models.py` | unit | 31 | analytics_domain |
| 29 | `tests/unit/services/test_twr_inspection_service.py` | unit | 31 | analytics_domain |
| 30 | `tests/unit/services/test_operator_action_replay_service.py` | unit | 30 | uncategorized |

The #502 request-path proof added a module driving the real application over HTTP for tenant admission - admitted, absent, blank and concurrent two-tenant requests, each asserting the outbound Core call - raising inventoried modules to `317`, source test functions to `3634`, and API/runtime tests to `699`. Later review fixes in the same PR added the padded-tenant refusals and the returns-series authority regression, which are counted in those figures. Uncategorized tests are unchanged at `876`: every added module classifies as api_or_runtime, so the ceiling this gate governs was neither approached nor raised.

The container-scan composition proof added one module and one documentation invariant. The module asserts that a workflow job reaches the image scan exactly once and that the judged report is the one produced and uploaded, which is a property of how the lane composes Make targets rather than of any single target. The invariant requires every documented `make` invocation to name a target that exists in the Makefile, so a reference to a target that does not exist fails without anyone having to remember which target was renamed. Inventoried modules rise to `322`, source test functions to `3663`, quality/security tests to `225`, and contract/governance tests to `178`. Uncategorized tests are unchanged at `876`, exactly the ceiling this gate governs: neither addition classifies as uncategorized, so the ceiling was neither approached nor raised.
