# Lotus Performance Test Taxonomy Inventory

Report date: 2026-06-29
Branch: `feature/workspace-breakdown-window-boundary`
Mode: regression-blocking test taxonomy inventory; `make quality-test-taxonomy-gate` enforces
minimum API/runtime and contract/governance breadth plus the current uncategorized-test ceiling.

## Purpose

This report captures the shape of the repository test suite using a standard-library AST inventory.
It complements `pytest --collect-only` by measuring test-module and test-function breadth by suite
and quality family without executing tests or requiring coverage data.

## Command

```powershell
python scripts/python_test_taxonomy_inventory.py --limit 30
python scripts/python_test_taxonomy_inventory.py --limit 30 --min-api-runtime-tests 607 --min-contract-governance-tests 111 --max-uncategorized-tests 1294
```

## Summary

| Metric | Value |
| --- | ---: |
| Test modules inventoried | 281 |
| Test functions inventoried | 3219 |
| Integration/API/runtime test functions | 608 |
| Contract/governance test functions | 111 |

## Test Functions By Suite

| Suite | Modules | Test functions |
| --- | ---: | ---: |
| benchmarks | 9 | 17 |
| e2e | 1 | 21 |
| integration | 24 | 300 |
| unit | 247 | 2881 |

## Test Functions By Family

| Family | Test functions |
| --- | ---: |
| analytics_domain | 1125 |
| api_or_runtime | 608 |
| contract_or_governance | 111 |
| observability_or_readiness | 248 |
| quality_or_security | 121 |
| uncategorized | 1238 |

## Largest Test Modules

| Rank | Module | Suite | Test functions | Families |
| ---: | --- | --- | ---: | --- |
| 1 | `tests/unit/app/test_enterprise_readiness_additional.py` | unit | 80 | observability_or_readiness |
| 2 | `tests/unit/services/test_returns_series_service.py` | unit | 75 | uncategorized |
| 3 | `tests/unit/services/test_stateful_attribution_input_service.py` | unit | 68 | analytics_domain |
| 4 | `tests/unit/app/test_openapi_enrichment.py` | unit | 61 | api_or_runtime |
| 5 | `tests/unit/services/test_compute_job_store.py` | unit | 59 | observability_or_readiness |
| 6 | `tests/unit/engine/test_attribution.py` | unit | 57 | analytics_domain |
| 7 | `tests/unit/services/test_twr_inspection_source_economics.py` | unit | 57 | analytics_domain |
| 8 | `tests/unit/services/test_lineage_metadata_store.py` | unit | 54 | uncategorized |
| 9 | `tests/unit/app/test_contribution_endpoint_helpers.py` | unit | 52 | analytics_domain, api_or_runtime |
| 10 | `tests/unit/services/test_twr_inspection_calculation_consistency.py` | unit | 51 | analytics_domain |
| 11 | `tests/unit/docs/test_public_docs_contract.py` | unit | 48 | contract_or_governance |
| 12 | `tests/unit/services/test_workspace_summary_service.py` | unit | 47 | uncategorized |
| 13 | `tests/unit/services/test_twr_mode_service.py` | unit | 45 | analytics_domain |
| 14 | `tests/unit/services/test_stateful_benchmark_input_service.py` | unit | 44 | uncategorized |
| 15 | `tests/integration/test_contribution_api.py` | integration | 40 | analytics_domain, api_or_runtime |
| 16 | `tests/unit/engine/test_mwr.py` | unit | 40 | analytics_domain |
| 17 | `tests/unit/services/test_operator_action_lease_service.py` | unit | 39 | uncategorized |
| 18 | `tests/integration/test_performance_api.py` | integration | 38 | api_or_runtime |
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
contract/governance coverage, but 1238 test functions remain uncategorized by the first-wave
taxonomy and should be reduced through normal refactor slices rather than allowed to grow.

The workspace performance breakdown window boundary slice keeps the promoted gate stable while
strengthening period and cumulative TWR breakdown-window proof in
`tests/unit/services/test_workspace_summary_service.py`.
Current measured breadth is `608` API/runtime test functions, `111` contract/governance test
functions, `248` observability/readiness test functions, `1125` analytics-domain test functions,
and `1238` uncategorized test functions. The enforced command remains at the accepted regression
floor of `607` API/runtime tests and the existing uncategorized ceiling of `1294`; intentional
threshold changes should remain separate, rationale-backed gate-governance work.

This slice promotes the stable part of the taxonomy from report-only measurement to a
regression-blocking evaluation gate. `make quality-test-taxonomy-gate` fails if API/runtime tests
drop below `607`, contract/governance tests drop below `111`, or uncategorized tests rise above
`1294`. `make quality-evaluation-gate` now runs both deterministic demo API certification and this
taxonomy gate, so existing Feature Lane, PR Merge Gate, Main Releasability, local `make check`,
local `make ci`, and Quality Baseline workflow enforcement pick it up without duplicating workflow
logic.

## Gate Posture

This is a Phase 2 regression-blocking quality gate for stable taxonomy breadth. It is intentionally
not a strict maturity score: branch coverage, uncategorized-test remediation, and finer taxonomy
labels remain planned improvements. Exceptions should not be soft-failed in CI; if a supported API
or governance test category is intentionally removed, update the gate threshold, scorecard, and
review ledger in the same PR with explicit rationale.
